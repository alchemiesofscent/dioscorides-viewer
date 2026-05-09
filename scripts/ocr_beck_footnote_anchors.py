#!/usr/bin/env python3
"""Targeted OCR rescue for unresolved Beck footnote anchors."""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def bbox_parts(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = value.split()
    if len(parts) != 4:
        return None
    try:
        return tuple(int(float(part)) for part in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def markerish(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return False
    if "^" in raw or "*" in raw:
        return True
    if re.search(r"[\^*'\u2019\u201d]+(\d{1,3})$", raw):
        return True
    if re.search(r"(?<![A-Za-z])['\u2019\u201d]{2,}$", raw):
        return True
    return False


def unresolved_rows(audit_dir: Path) -> list[dict[str, str]]:
    path = audit_dir / "footnotes.csv"
    if not path.exists():
        raise SystemExit(f"Missing footnote audit CSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("status") or "").startswith("unresolved")]


def source_tokens_by_page(source: Path) -> dict[int, list[dict[str, object]]]:
    root = ET.parse(source).getroot()
    page = 0
    tokens: defaultdict[int, list[dict[str, object]]] = defaultdict(list)
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            page = int(element.get("seq") or page or 0)
        elif tag == "tok":
            bbox = bbox_parts(element.get("bbox"))
            if bbox:
                tokens[page].append(
                    {
                        "id": element.get("id") or "",
                        "text": normalize_ws("".join(element.itertext())),
                        "bbox": bbox,
                    }
                )
    return tokens


def page_note_floor(rows: list[dict[str, str]]) -> dict[int, int]:
    floor: dict[int, int] = {}
    for row in rows:
        page = int(row.get("page") or 0)
        summary = row.get("candidate_summary") or ""
        coords = re.findall(r"@(\d+),(\d+):", summary)
        if coords:
            continue
        if page:
            floor.setdefault(page, 2200)
    return floor


def run_tesseract(image_path: Path, psm: int) -> list[dict[str, str]]:
    cmd = ["tesseract", str(image_path), "stdout", "--psm", str(psm), "tsv"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    lines = result.stdout.splitlines()
    if not lines:
        return []
    reader = csv.DictReader(lines, delimiter="\t")
    return [row for row in reader if row.get("text")]


def nearest_source_token(
    word: dict[str, str],
    source_tokens: list[dict[str, object]],
    crop_top: int,
) -> tuple[str, str]:
    try:
        x = int(float(word.get("left") or 0))
        y = int(float(word.get("top") or 0)) + crop_top
    except ValueError:
        return "", ""
    best: tuple[int, dict[str, object]] | None = None
    for token in source_tokens:
        left, top, right, bottom = token["bbox"]  # type: ignore[misc]
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        distance = abs(cx - x) + abs(cy - y)
        if best is None or distance < best[0]:
            best = (distance, token)
    if best is None or best[0] > 80:
        return "", ""
    token = best[1]
    return str(token.get("id") or ""), str(token.get("text") or "")


def ocr_page(image: Path, note_floor: int, source_tokens: list[dict[str, object]]) -> list[dict[str, str]]:
    try:
        from PIL import Image
    except ImportError:
        return []

    rows: list[dict[str, str]] = []
    with Image.open(image) as img:
        width, height = img.size
        crop_bottom = min(max(1, note_floor - 20), height)
        crop = img.crop((0, 0, width, crop_bottom))
        with tempfile.TemporaryDirectory() as tmpdir:
            crop_path = Path(tmpdir) / "main_text.png"
            crop.save(crop_path)
            for psm in (6, 11):
                for word in run_tesseract(crop_path, psm):
                    text = word.get("text") or ""
                    if not markerish(text):
                        continue
                    token_id, source_text = nearest_source_token(word, source_tokens, 0)
                    rows.append(
                        {
                            "psm": str(psm),
                            "ocr_text": text,
                            "conf": word.get("conf") or "",
                            "left": word.get("left") or "",
                            "top": word.get("top") or "",
                            "width": word.get("width") or "",
                            "height": word.get("height") or "",
                            "source_token_id": token_id,
                            "source_token_text": source_text,
                        }
                    )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Input Beck OCR/XML source")
    parser.add_argument("--images", required=True, help="Directory of Beck page images")
    parser.add_argument("--audit", required=True, help="Beck footnote audit directory")
    args = parser.parse_args()

    source = Path(args.source)
    images = Path(args.images)
    audit_dir = Path(args.audit)
    rows = unresolved_rows(audit_dir)
    source_tokens = source_tokens_by_page(source)
    floors = page_note_floor(rows)
    pages = sorted({int(row.get("page") or 0) for row in rows if row.get("page")})

    output = audit_dir / "ocr_candidates.csv"
    fieldnames = [
        "note_source_id",
        "page",
        "n",
        "evidence_status",
        "psm",
        "ocr_text",
        "conf",
        "left",
        "top",
        "width",
        "height",
        "source_token_id",
        "source_token_text",
    ]
    evidence: list[dict[str, str]] = []
    rows_by_page: defaultdict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_page[int(row.get("page") or 0)].append(row)

    for page in pages:
        image = images / f"beck-{page}.jpg"
        page_evidence: list[dict[str, str]] = []
        if image.exists():
            page_evidence = ocr_page(image, floors.get(page, 2200), source_tokens.get(page, []))
        for note in rows_by_page[page]:
            note_rows = page_evidence or [
                {
                    "psm": "",
                    "ocr_text": "",
                    "conf": "",
                    "left": "",
                    "top": "",
                    "width": "",
                    "height": "",
                    "source_token_id": "",
                    "source_token_text": "",
                }
            ]
            for item in note_rows:
                evidence.append(
                    {
                        "note_source_id": note.get("source_id") or "",
                        "page": str(page),
                        "n": note.get("n") or "",
                        "evidence_status": "ocr-candidate" if item.get("ocr_text") else "no-candidate-found",
                        **item,
                    }
                )

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(evidence)

    print(f"Unresolved pages OCR-scanned: {len(pages)}")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
