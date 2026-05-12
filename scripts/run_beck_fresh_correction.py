#!/usr/bin/env python3
"""Run or prepare Beck fresh-OCR model-correction chunks.

The script consumes only the fresh PDF-derived OCR stream: page images, hOCR,
plain OCR text, QA metrics, and footnote-link evidence under ``ocr/beck2020_fresh``.
It does not read ``beck.xml`` or the older generated Beck TEI.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_beck_fresh_pilot import DEFAULT_PAGES, HocrPage, normalize_ws, parse_hocr, parse_pages


DEFAULT_OCR_DIR = "ocr/beck2020_fresh"
DEFAULT_MANIFEST = "editions/beck2020_fresh/manifest.json"
DEFAULT_PROMPT = "prompts/beck_fresh_system.md"
DEFAULT_OUTPUT_DIR = "ocr/beck2020_fresh/correction/chunks"


def load_text(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:limit] if limit else text


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def chunk_pages(pages: list[int], chunk_size: int) -> list[list[int]]:
    return [pages[index : index + chunk_size] for index in range(0, len(pages), chunk_size)]


def hocr_line_evidence(page: HocrPage, max_lines: int) -> str:
    rows = []
    for line in page.lines[:max_lines]:
        bbox = " ".join(str(part) for part in line.bbox) if line.bbox else ""
        rows.append(f"- l{line.index} bbox={bbox}: {line.text}")
    if len(page.lines) > max_lines:
        rows.append(f"- ... {len(page.lines) - max_lines} additional hOCR lines omitted from prompt")
    return "\n".join(rows)


def page_entry_by_pdf(manifest: dict) -> dict[int, dict]:
    return {
        int(page["pdf_page"]): page
        for page in manifest.get("pages", [])
        if str(page.get("pdf_page", "")).isdigit()
    }


def footnote_rows_by_page(rows: list[dict[str, str]]) -> dict[int, list[dict[str, str]]]:
    by_page: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        page = row.get("page") or ""
        if page.isdigit():
            by_page.setdefault(int(page), []).append(row)
    return by_page


def assemble_prompt(
    pages: list[int],
    manifest_pages: dict[int, dict],
    footnotes: dict[int, list[dict[str, str]]],
    ocr_dir: Path,
    hocr_line_limit: int,
) -> str:
    parts = [
        f"Correct the following Beck 2020 fresh-OCR chunk for PDF pages {pages[0]}-{pages[-1]}.",
        "",
        "Use the attached page images as the authority. Use hOCR coordinates and OCR text as evidence only.",
        "Do not consult or reproduce older Beck XML/output artifacts.",
        "",
        "Return only a TEI XML fragment for these pages.",
    ]

    for page in pages:
        entry = manifest_pages.get(page, {})
        txt_path = ocr_dir / "txt" / f"beck-{page:04d}.txt"
        hocr_path = ocr_dir / "hocr" / f"beck-{page:04d}.hocr"
        parts.extend(
            [
                "",
                f"## PDF Page {page}",
                "",
                "### Manifest",
                "```json",
                json.dumps(entry, ensure_ascii=False, indent=2),
                "```",
                "",
                "### OCR Text",
                "```text",
                load_text(txt_path, limit=6000),
                "```",
            ]
        )
        if hocr_path.exists():
            parsed = parse_hocr(hocr_path, page)
            parts.extend(["", "### hOCR line evidence", "```text", hocr_line_evidence(parsed, hocr_line_limit), "```"])
        page_footnotes = footnotes.get(page, [])
        if page_footnotes:
            parts.extend(["", "### Footnote candidates", "```json", json.dumps(page_footnotes, ensure_ascii=False, indent=2), "```"])

    return "\n".join(parts)


def strip_xml_output(output: str) -> str:
    text = output.strip()
    if "```xml" in text:
        start = text.index("```xml") + len("```xml")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()
    return text.replace("ϑ", "θ")


def run_chunk(
    chunk: list[int],
    prompt: str,
    system_prompt: Path,
    ocr_dir: Path,
    output_dir: Path,
    model: str,
    dry_run: bool,
) -> dict:
    chunk_id = f"beck_fresh_{chunk[0]:04d}_{chunk[-1]:04d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = output_dir / f"{chunk_id}_prompt.txt"
    out_path = output_dir / f"{chunk_id}.xml"
    full_prompt = load_text(system_prompt) + "\n\n---\n\n" + prompt

    if dry_run:
        prompt_path.write_text(full_prompt, encoding="utf-8")
        return {"chunk_id": chunk_id, "status": "dry_run", "prompt_file": str(prompt_path)}

    response_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix=f"{chunk_id}_", delete=False)
    response_path = response_file.name
    response_file.close()
    cmd = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--output-last-message",
        response_path,
    ]
    if model:
        cmd.extend(["--model", model])
    for page in chunk:
        image = ocr_dir / "images" / f"beck-{page:04d}.png"
        if image.exists():
            cmd.extend(["-i", str(image)])
    cmd.extend(["--", full_prompt])

    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        elapsed = round(time.time() - started, 1)
        if result.returncode != 0:
            return {
                "chunk_id": chunk_id,
                "status": "error",
                "elapsed": elapsed,
                "error": normalize_ws((result.stderr or result.stdout)[-2000:]),
            }
        output = load_text(Path(response_path)) or result.stdout
        out_path.write_text(strip_xml_output(output), encoding="utf-8")
        return {"chunk_id": chunk_id, "status": "success", "elapsed": elapsed, "output_file": str(out_path)}
    except subprocess.TimeoutExpired:
        return {"chunk_id": chunk_id, "status": "timeout"}
    finally:
        try:
            os.unlink(response_path)
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", default=DEFAULT_OCR_DIR)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--system-prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--pages", default=DEFAULT_PAGES)
    parser.add_argument("--chunk-size", type=int, default=2)
    parser.add_argument("--hocr-lines", type=int, default=120)
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ocr_dir = Path(args.ocr_dir)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    manifest_pages = page_entry_by_pdf(manifest)
    available_pages = set(manifest_pages)
    selected_pages = [page for page in parse_pages(args.pages) if page in available_pages]
    missing_pages = sorted(set(parse_pages(args.pages)) - available_pages)
    if missing_pages:
        raise SystemExit(f"Pages are not present in the fresh manifest/OCR stream: {missing_pages[:20]}")
    if not selected_pages:
        raise SystemExit("No pages selected")

    footnotes = footnote_rows_by_page(load_csv(ocr_dir / "qa" / "footnote_links.csv"))
    chunks = chunk_pages(selected_pages, max(1, args.chunk_size))
    output_dir = Path(args.output_dir)
    print(f"Processing {len(chunks)} Beck fresh correction chunks ({'dry run' if args.dry_run else 'live'})")

    tasks = [
        (
            chunk,
            assemble_prompt(chunk, manifest_pages, footnotes, ocr_dir, args.hocr_lines),
        )
        for chunk in chunks
    ]
    results = []
    if args.max_parallel <= 1 or args.dry_run:
        for chunk, prompt in tasks:
            result = run_chunk(chunk, prompt, Path(args.system_prompt), ocr_dir, output_dir, args.model, args.dry_run)
            results.append(result)
            print(f"  {result['chunk_id']}: {result['status']}")
    else:
        with ThreadPoolExecutor(max_workers=args.max_parallel) as pool:
            futures = {
                pool.submit(run_chunk, chunk, prompt, Path(args.system_prompt), ocr_dir, output_dir, args.model, args.dry_run): chunk
                for chunk, prompt in tasks
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                print(f"  {result['chunk_id']}: {result['status']}")

    log_path = output_dir / "run_log.json"
    log_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    success = sum(1 for result in results if result["status"] in {"success", "dry_run"})
    print(f"Done. {success}/{len(results)} completed. Log: {log_path}")
    return 0 if success == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
