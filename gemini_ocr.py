#!/usr/bin/env python3
"""OCR JP2 page scans into diplomatic TEI XML with Gemini 2.5 Pro."""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
DEFAULT_DELAY_SECONDS = 35.0

SYSTEM_PROMPT = """Transcribe this page diplomatically as TEI XML.

Rules:
- Mark italic text with <hi rend="italic"> — mark ONLY the exact characters printed in italic. Do not extend italic ranges to adjacent words.
- Use a conservative italic policy: when in doubt whether a word is italic, do NOT mark it. It is better to miss an italic word than to over-tag roman text. Do not tag a word merely because it is a proper name, author name, plant name, Greek/Latin title, or scholarly term.
- Hyphenated line breaks: <lb break="no"/> (no hyphen character in text). Place the break inside any enclosing element (e.g. <foreign>), not outside it.
- Non-hyphenated line breaks: <lb/>
- Footnote references in body: <ref target="#fn1">¹</ref>
- Footnotes in <note xml:id="fn1" n="1" place="foot">
- Tag Greek passages with <foreign xml:lang="grc">
- Tag Arabic/Hebrew with appropriate xml:lang
- Do NOT output a full TEI document. Output only the content for this page as a fragment, starting with <pb n="[PAGE_NUMBER]"/> followed by the page content. No <?xml?> declaration, no <TEI>, no <teiHeader>, no <text>, no <body> tags. For <pb n="">, use the printed Arabic numeral page number. If none is visible, use the final numeric filename segment minus 8 (e.g. n="339" from b23982500_0002_0347.jp2). Do not use signature marks (like "Y 2") as page numbers.
- Preserve exact spelling, punctuation, and spacing
- Read reference numbers (page, verse, section) with extreme care — transcribe exactly what is printed, do not guess or correct
- Do not normalize ae/oe to æ/œ or vice versa — reproduce exactly what is printed.
- Do not add diacritical marks to Latin words unless they are clearly printed in the source. Do not invent acute, grave, circumflex, macron, or umlaut marks in Latin prose.
- Do not mark drop caps or initial letters with special markup.

Languages: Latin (primary), Ancient Greek, occasional Arabic and Hebrew."""


FENCE_RE = re.compile(r"^\s*```(?:xml|tei|tei-xml)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.IGNORECASE)
TEI_HEADER_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?teiHeader\b[^>]*>.*?</(?:[A-Za-z_][\w.-]*:)?teiHeader>", re.IGNORECASE | re.DOTALL)
WRAPPER_TAG_RE = re.compile(r"</?(?:[A-Za-z_][\w.-]*:)?(?:TEI|text|body)\b[^>]*>", re.IGNORECASE)
INPUT_RATE_PER_MILLION = 1.25
OUTPUT_RATE_PER_MILLION = 10.00
MERGED_FILENAME = "sprengel_comm_merged.xml"


@dataclass
class Usage:
    prompt_tokens: int = 0
    candidates_tokens: int = 0


@dataclass
class OcrResult:
    text: str
    usage: Usage


@dataclass
class ProjectPaths:
    root: Path
    page_images: Path
    ocr_fragments: Path
    outputs: Path
    costs: Path
    images: list[Path]


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_project_dir(source_path: Path) -> Path:
    source_base = source_path if source_path.is_dir() else source_path.parent
    if (source_base / "sprengel" / "sp-comm").is_dir():
        return source_base.resolve() / "sprengel_comm"
    return source_base.resolve().parent.parent / "sprengel_comm"


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


def initialize_project(
    source_path: Path,
    project_dir: Path,
    costs_path: Path | None = None,
    *,
    link_images: bool = True,
) -> ProjectPaths:
    root = project_dir.resolve()
    page_images = root / "page_images"
    ocr_fragments = root / "ocr_fragments"
    outputs = root / "outputs"
    costs = costs_path.resolve() if costs_path else root / "costs.csv"

    for directory in (root, page_images, ocr_fragments, outputs):
        directory.mkdir(parents=True, exist_ok=True)

    images: list[Path] = []
    if link_images:
        for source_image in discover_images(source_path):
            target = page_images / source_image.name
            if target.exists() or target.is_symlink():
                images.append(target)
                continue
            try:
                target.symlink_to(source_image.resolve())
            except OSError:
                shutil.copy2(source_image, target)
            images.append(target)

    return ProjectPaths(root=root, page_images=page_images, ocr_fragments=ocr_fragments, outputs=outputs, costs=costs, images=images)


def image_to_png_base64(path: Path) -> str:
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Missing dependency: Pillow. Install it with `.venv/bin/python -m pip install Pillow`.") from exc

    with Image.open(path) as image:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def make_payload(encoded_png: str, source_filename: str) -> dict[str, Any]:
    return {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Transcribe the attached scanned page as diplomatic TEI XML.\n"
                            f"Source filename: {source_filename}\n"
                            "If no printed Arabic page number is visible, use the final numeric filename segment "
                            "minus 8 as the <pb n=\"\"> value."
                        )
                    },
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": encoded_png,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0,
        },
    }


def post_gemini_request(api_key: str, encoded_png: str, source_filename: str, timeout: int) -> dict[str, Any]:
    response = requests.post(
        GEMINI_URL,
        params={"key": api_key},
        json=make_payload(encoded_png, source_filename),
        timeout=timeout,
    )
    if not response.ok:
        message = response.text[:2000]
        try:
            body = response.json()
        except json.JSONDecodeError:
            pass
        else:
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        raise RuntimeError(f"HTTP {response.status_code}: {message}")
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini API returned invalid JSON: {exc}") from exc


def int_field(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def extract_usage(data: dict[str, Any]) -> Usage:
    metadata = data.get("usageMetadata")
    if not isinstance(metadata, dict):
        return Usage()

    prompt_tokens = int_field(metadata, "promptTokenCount")
    candidate_text_tokens = int_field(metadata, "candidatesTokenCount")
    thinking_tokens = int_field(metadata, "thoughtsTokenCount")
    return Usage(
        prompt_tokens=prompt_tokens,
        candidates_tokens=candidate_text_tokens + thinking_tokens,
    )


def extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini response did not include candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not isinstance(parts, list):
        raise RuntimeError("Gemini response candidate did not include content parts")

    text_parts = [part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "".join(text_parts).strip()
    if not text:
        finish_reason = candidates[0].get("finishReason")
        raise RuntimeError(f"Gemini response did not include text; finishReason={finish_reason!r}")
    return text


def strip_markdown_fence(text: str) -> str:
    match = FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def strip_wrapping(text: str) -> str:
    fragment = strip_markdown_fence(text)
    fragment = XML_DECL_RE.sub("", fragment)
    fragment = TEI_HEADER_RE.sub("", fragment)
    fragment = WRAPPER_TAG_RE.sub("", fragment).strip()
    pb_index = fragment.find("<pb")
    if pb_index > 0:
        fragment = fragment[pb_index:].strip()
    if not fragment.startswith("<pb"):
        fragment = '<pb n=""/>\n' + fragment
    return fragment.strip()


def ocr_image(image_path: Path, api_key: str, timeout: int) -> OcrResult:
    encoded_png = image_to_png_base64(image_path)
    data = post_gemini_request(api_key, encoded_png, image_path.name, timeout)
    return OcrResult(
        text=strip_wrapping(extract_text(data)),
        usage=extract_usage(data),
    )


def append_cost_row(costs_path: Path, filename: str, usage: Usage, status: str) -> None:
    costs_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not costs_path.exists()
    with costs_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(["filename", "prompt_tokens", "candidates_tokens", "status", "timestamp"])
        writer.writerow(
            [
                filename,
                usage.prompt_tokens,
                usage.candidates_tokens,
                status,
                datetime.now(timezone.utc).isoformat(),
            ]
        )


def estimated_cost(prompt_tokens: int, candidates_tokens: int) -> float:
    return (prompt_tokens * INPUT_RATE_PER_MILLION / 1_000_000) + (
        candidates_tokens * OUTPUT_RATE_PER_MILLION / 1_000_000
    )


def fragment_path(project: ProjectPaths, image_path: Path) -> Path:
    return project.ocr_fragments / image_path.with_suffix(".xml").name


def unprocessed_images(project: ProjectPaths, images: list[Path]) -> list[Path]:
    return [image_path for image_path in images if not fragment_path(project, image_path).exists()]


def first_unprocessed_image(project: ProjectPaths) -> Path | None:
    remaining = unprocessed_images(project, project.images)
    if not remaining:
        return None
    return remaining[0]


def merge_fragments(project: ProjectPaths) -> Path:
    fragments = sorted(project.ocr_fragments.glob("*.xml"))
    merged_path = project.outputs / MERGED_FILENAME
    body = "\n".join(fragment.read_text(encoding="utf-8").strip() for fragment in fragments)
    merged = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Sprengel, Commentarius in Dioscoridem</title></titleStmt>
      <publicationStmt><p>Diplomatic transcription</p></publicationStmt>
      <sourceDesc><p>Transcribed from scanned page images via Gemini OCR</p></sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
{body}
    </body>
  </text>
</TEI>
"""
    merged_path.write_text(merged, encoding="utf-8")
    try:
        ET.parse(merged_path)
    except ET.ParseError as exc:
        log(f"MERGE ERROR {merged_path}: not well-formed XML: {exc}")
        raise
    log(f"MERGE OK {merged_path}: {len(fragments)} fragment(s)")
    return merged_path


def wait_between_requests(delay: float) -> None:
    if delay <= 0:
        return
    log(f"Waiting {delay:.0f}s for rate limit")
    time.sleep(delay)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR one JP2 file or a sorted directory of JP2 files into TEI XML with Gemini 2.5 Pro."
    )
    parser.add_argument("input", nargs="?", type=Path, help="Deprecated: use --source-dir instead")
    parser.add_argument("--source-dir", type=Path, default=None, help="Path to a .jp2 file or a directory containing .jp2 files")
    parser.add_argument("--project-dir", type=Path, default=None, help="Project output directory")
    parser.add_argument("--limit", type=int, help="Only inspect the first N sorted JP2 files")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS, help="Seconds to wait between API requests")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP request timeout in seconds")
    parser.add_argument("--costs", type=Path, default=None, help="CSV file for per-page token usage")
    parser.add_argument("--merge", action="store_true", help="Merge existing fragments and exit without OCR")
    parser.add_argument("--test", action="store_true", help="OCR the next unprocessed JP2 page, print it, then merge")
    args = parser.parse_args(argv)
    if args.test and args.merge:
        parser.error("--test cannot be used with --merge; --merge is offline merge-only mode")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater")
    if args.delay < 0:
        raise SystemExit("--delay must be 0 or greater")

    source_path = args.source_dir or args.input or Path.cwd()
    project_dir = args.project_dir or default_project_dir(source_path)
    project = initialize_project(source_path, project_dir, args.costs, link_images=not args.merge)

    if args.merge:
        merge_fragments(project)
        return 0

    log(f"Found {len(project.images)} JP2 image(s) in sorted order")
    log(f"Project directory: {project.root}")

    if args.test:
        image_path = first_unprocessed_image(project)
        if image_path is None:
            log("TEST: no unprocessed JP2 images remain; skipping Gemini request")
            merge_fragments(project)
            return 0

        load_dotenv()
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise SystemExit("Set GOOGLE_API_KEY in the environment or in the repo .env file.")

        output_path = fragment_path(project, image_path)
        try:
            result = ocr_image(image_path, api_key, args.timeout)
        except Exception as exc:
            append_cost_row(project.costs, image_path.name, Usage(), "error")
            log(f"ERROR {image_path.name}: {exc}")
            merge_fragments(project)
            return 1

        output_path.write_text(result.text + "\n", encoding="utf-8")
        append_cost_row(project.costs, image_path.name, result.usage, "ok")
        print(result.text, flush=True)
        log(
            "Test summary: "
            f"file={image_path.name}; "
            f"prompt_tokens={result.usage.prompt_tokens}; "
            f"candidates_tokens={result.usage.candidates_tokens}; "
            f"estimated_paid_cost=${estimated_cost(result.usage.prompt_tokens, result.usage.candidates_tokens):.6f}"
        )
        merge_fragments(project)
        return 0

    load_dotenv()
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise SystemExit("Set GOOGLE_API_KEY in the environment or in the repo .env file.")

    images = project.images
    if args.limit is not None:
        images = images[: args.limit]

    log(f"OCR target window: {len(images)} JP2 image(s)")
    requested = False
    total_prompt_tokens = 0
    total_candidates_tokens = 0

    for image_path in images:
        output_path = fragment_path(project, image_path)
        if output_path.exists():
            log(f"SKIP {image_path.name}: {output_path.name} already exists")
            continue

        if requested:
            wait_between_requests(args.delay)

        try:
            result = ocr_image(image_path, api_key, args.timeout)
        except Exception as exc:
            requested = True
            append_cost_row(project.costs, image_path.name, Usage(), "error")
            log(f"ERROR {image_path.name}: {exc}")
            continue

        output_path.write_text(result.text + "\n", encoding="utf-8")
        append_cost_row(project.costs, image_path.name, result.usage, "ok")
        total_prompt_tokens += result.usage.prompt_tokens
        total_candidates_tokens += result.usage.candidates_tokens
        requested = True
        log(
            f"OK {image_path.name}: wrote {output_path.name}; "
            f"prompt_tokens={result.usage.prompt_tokens}; "
            f"candidates_tokens={result.usage.candidates_tokens}"
        )

    log(
        "Summary: "
        f"input_tokens={total_prompt_tokens}; "
        f"output_tokens={total_candidates_tokens}; "
        f"estimated_paid_cost=${estimated_cost(total_prompt_tokens, total_candidates_tokens):.6f}"
    )
    merge_fragments(project)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
