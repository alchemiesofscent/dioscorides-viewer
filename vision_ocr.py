#!/usr/bin/env python3
"""OCR JP2 page scans with Google Cloud Vision's REST API."""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
LANGUAGE_HINTS = ["la", "grc", "ar", "iw"]
MAX_BATCH_SIZE = 16
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class VisionRequestError(Exception):
    """Raised when the Vision API request fails at the HTTP/request level."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE lines without depending on python-dotenv."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def load_local_env() -> None:
    script_env = Path(__file__).resolve().with_name(".env")
    cwd_env = Path.cwd() / ".env"
    load_env_file(script_env)
    if cwd_env != script_env:
        load_env_file(cwd_env)


def discover_images(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() != ".jp2":
            raise SystemExit(f"Expected a .jp2 file: {input_path}")
        return [input_path]

    if input_path.is_dir():
        images = sorted(path for path in input_path.iterdir() if path.is_file() and path.suffix.lower() == ".jp2")
        if not images:
            raise SystemExit(f"No .jp2 files found in directory: {input_path}")
        return images

    raise SystemExit(f"Input path does not exist: {input_path}")


def chunked(paths: list[Path], batch_size: int) -> list[list[Path]]:
    return [paths[index : index + batch_size] for index in range(0, len(paths), batch_size)]


def image_to_png_base64(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Missing dependency: Pillow. Install it with `python3 -m pip install Pillow`.") from exc

    with Image.open(path) as image:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_request_entry(encoded_png: str) -> dict[str, Any]:
    return {
        "image": {"content": encoded_png},
        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        "imageContext": {"languageHints": LANGUAGE_HINTS},
    }


def post_vision_request(
    api_key: str,
    request_entries: list[dict[str, Any]],
    *,
    max_retries: int,
    initial_backoff: float,
    timeout: int,
) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise SystemExit("Missing dependency: requests. Install it with `python3 -m pip install requests`.") from exc

    payload = {"requests": request_entries}
    params = {"key": api_key}
    backoff = initial_backoff
    last_error = ""

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(VISION_URL, params=params, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_error = str(exc)
            retryable = True
        else:
            retryable = response.status_code in RETRY_STATUS_CODES
            if response.ok:
                try:
                    return response.json()
                except json.JSONDecodeError as exc:
                    raise VisionRequestError(f"Vision API returned invalid JSON: {exc}") from exc
            last_error = f"HTTP {response.status_code}: {response.text[:1000]}"
            if not retryable:
                raise VisionRequestError(last_error, status_code=response.status_code)

        if attempt >= max_retries:
            break
        log(f"Vision request failed ({last_error}); retrying in {backoff:.1f}s")
        time.sleep(backoff)
        backoff *= 2

    raise VisionRequestError(last_error or "Vision request failed")


def is_payload_too_large(error: VisionRequestError) -> bool:
    return error.status_code == 400 and "payload size exceeds" in str(error).lower()


def extract_text(response_entry: dict[str, Any]) -> str:
    annotation = response_entry.get("fullTextAnnotation") or {}
    text = annotation.get("text")
    if isinstance(text, str):
        return text
    return ""


def word_count(text: str) -> int:
    return len(text.split())


def write_ocr_text(image_path: Path, text: str) -> Path:
    output_path = image_path.with_suffix(".txt")
    output_path.write_text(text, encoding="utf-8")
    return output_path


def process_batch(
    image_paths: list[Path],
    *,
    api_key: str,
    max_retries: int,
    initial_backoff: float,
    timeout: int,
) -> None:
    request_entries: list[dict[str, Any]] = []
    request_paths: list[Path] = []

    for image_path in image_paths:
        try:
            encoded_png = image_to_png_base64(image_path)
        except Exception as exc:
            log(f"ERROR {image_path.name}: could not convert JP2 to PNG: {exc}")
            continue
        request_entries.append(make_request_entry(encoded_png))
        request_paths.append(image_path)

    if not request_entries:
        return

    try:
        data = post_vision_request(
            api_key,
            request_entries,
            max_retries=max_retries,
            initial_backoff=initial_backoff,
            timeout=timeout,
        )
    except VisionRequestError as exc:
        if len(request_paths) > 1 and is_payload_too_large(exc):
            midpoint = len(request_paths) // 2
            log(
                "Splitting oversized batch "
                f"{request_paths[0].name}-{request_paths[-1].name} into "
                f"{len(request_paths[:midpoint])} and {len(request_paths[midpoint:])} images"
            )
            process_batch(
                request_paths[:midpoint],
                api_key=api_key,
                max_retries=max_retries,
                initial_backoff=initial_backoff,
                timeout=timeout,
            )
            process_batch(
                request_paths[midpoint:],
                api_key=api_key,
                max_retries=max_retries,
                initial_backoff=initial_backoff,
                timeout=timeout,
            )
            return
        log(f"ERROR batch {request_paths[0].name}-{request_paths[-1].name}: {exc}")
        return

    responses = data.get("responses")
    if not isinstance(responses, list):
        log(f"ERROR batch {request_paths[0].name}-{request_paths[-1].name}: missing responses array")
        return

    for image_path, response_entry in zip(request_paths, responses):
        if not isinstance(response_entry, dict):
            log(f"ERROR {image_path.name}: malformed response entry")
            continue

        error = response_entry.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            log(f"ERROR {image_path.name}: {message}")
            continue

        text = extract_text(response_entry)
        output_path = write_ocr_text(image_path, text)
        log(f"OK {image_path.name}: {word_count(text)} words -> {output_path.name}")

    if len(responses) < len(request_paths):
        for image_path in request_paths[len(responses) :]:
            log(f"ERROR {image_path.name}: no response returned")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR one JP2 file or a directory of JP2 files with Google Cloud Vision DOCUMENT_TEXT_DETECTION."
    )
    parser.add_argument("input", type=Path, help="Path to a .jp2 file or a directory containing .jp2 files")
    parser.add_argument("--batch-size", type=int, default=MAX_BATCH_SIZE, help="Images per API request, max 16")
    parser.add_argument("--limit", type=int, help="Only process the first N images after sorting")
    parser.add_argument("--retries", type=int, default=4, help="Retries for rate limits and transient API failures")
    parser.add_argument("--backoff", type=float, default=2.0, help="Initial retry backoff in seconds")
    parser.add_argument("--timeout", type=int, default=180, help="HTTP request timeout in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.batch_size < 1 or args.batch_size > MAX_BATCH_SIZE:
        raise SystemExit(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    if args.retries < 0:
        raise SystemExit("--retries must be 0 or greater")
    if args.backoff <= 0:
        raise SystemExit("--backoff must be greater than 0")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater")

    load_local_env()
    api_key = os.environ.get("GOOGLE_CLOUD_API_KEY")
    if not api_key:
        raise SystemExit("Set GOOGLE_CLOUD_API_KEY in the environment or in a local .env file.")

    images = discover_images(args.input)
    if args.limit is not None:
        images = images[: args.limit]
    log(f"Found {len(images)} JP2 image(s); sending batches of up to {args.batch_size}")

    for batch_number, batch_paths in enumerate(chunked(images, args.batch_size), start=1):
        log(f"Batch {batch_number}: {batch_paths[0].name} ... {batch_paths[-1].name}")
        process_batch(
            batch_paths,
            api_key=api_key,
            max_retries=args.retries,
            initial_backoff=args.backoff,
            timeout=args.timeout,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
