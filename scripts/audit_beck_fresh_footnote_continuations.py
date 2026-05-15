#!/usr/bin/env python3
"""Audit likely cross-page footnote continuations in the fresh Beck diplomatic build."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from beck_fresh_diplomatic import (
    DEFAULT_DIPLOMATIC_MANIFEST,
    DEFAULT_DIPLOMATIC_OUTPUT,
    DEFAULT_FRESH_DIR,
    XML_ID,
    bbox_top,
    local_name,
    load_manifest,
    parse_bbox,
    read_csv_rows,
)
from ocr_beck_fresh_pilot import (
    Line,
    HocrPage,
    bbox_str,
    line_type,
    normalize_ws,
    output_paths,
    parse_hocr,
    raw_note_label,
)


FIELDS = [
    "page",
    "image_path",
    "separator_bbox",
    "line_index",
    "line_bbox",
    "line_text",
    "emitted_as_body",
    "suggested_previous_page",
    "suggested_previous_note_xml_id",
    "suggested_previous_n",
    "previous_note_tail",
    "candidate_strength",
    "reason",
]

NOTE_LABELISH_RE = re.compile(r"^\s*[^\w\u0370-\u03ff\u1f00-\u1fff\d]{0,4}\d{1,3}\b")
CONTINUATION_PUNCTUATION = (",", ";", ":", "-")
TERMINAL_PUNCTUATION_RE = re.compile(r"""[.!?。]['"”’)]*$""")


def page_width(page: HocrPage) -> int:
    if page.bbox:
        return max(0, page.bbox[2] - page.bbox[0])
    boxes = [line.bbox for line in page.lines if line.bbox is not None]
    if not boxes:
        return 0
    return max(box[2] for box in boxes) - min(box[0] for box in boxes)


def footnote_separator(page: HocrPage, page_height: int) -> tuple[int, int, int, int] | None:
    width = page_width(page)
    min_rule_width = max(300, int(width * 0.25)) if width else 300
    for separator in sorted(page.separators, key=lambda bbox: bbox[1]):
        left, top, right, bottom = separator
        rule_width = right - left
        rule_height = bottom - top
        if top < page_height * 0.55 or bottom > page_height * 0.97:
            continue
        if rule_width < min_rule_width or rule_height > 20:
            continue
        return separator
    return None


def initial_lines_below_separator(
    page: HocrPage,
    page_height: int,
    separator: tuple[int, int, int, int],
    max_gap: int,
) -> list[Line]:
    _left, _top, _right, bottom = separator
    selected: list[Line] = []
    for line in page.lines:
        if line.bbox is None or line.bbox[1] <= bottom:
            continue
        if line.bbox[1] - bottom > max_gap:
            if selected:
                break
            continue
        role, place = line_type(line, page_height)
        if role == "pageNum" and place == "bottom":
            continue
        if raw_note_label(line, allow_ocr_one=True) or NOTE_LABELISH_RE.match(line.text):
            break
        selected.append(line)
    return selected


def continuation_strength(previous_text: str, lines: list[Line]) -> tuple[str, str]:
    if not previous_text or not lines:
        return "weak", "below footnote rule without a printed note label"
    previous = normalize_ws(previous_text)
    first_text = normalize_ws(lines[0].text)
    reasons = ["below footnote rule without a printed note label", "previous page has an accepted bottom note"]
    if previous.endswith(CONTINUATION_PUNCTUATION):
        reasons.append("previous accepted note ends with continuation punctuation")
        return "strong", "; ".join(reasons)
    if not TERMINAL_PUNCTUATION_RE.search(previous):
        reasons.append("previous accepted note lacks terminal punctuation")
        return "strong", "; ".join(reasons)
    if first_text and first_text[:1].islower():
        reasons.append("continuation begins lowercase")
    return "weak", "; ".join(reasons)


def element_by_id(root: ET.Element) -> dict[str, ET.Element]:
    return {
        element.get(XML_ID) or element.get("xml:id") or "": element
        for element in root.iter()
        if element.get(XML_ID) or element.get("xml:id")
    }


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def is_body_line(element: ET.Element | None, parents: dict[ET.Element, ET.Element]) -> bool:
    if element is None or local_name(element.tag) != "ab":
        return False
    if element.get("type") != "line":
        return False
    current = element
    while current is not None:
        if local_name(current.tag) == "note" and current.get("type") == "footnote":
            return False
        current = parents.get(current)
    return True


def previous_note_lookup(fresh_dir: Path) -> dict[int, dict[str, str]]:
    by_page: defaultdict[int, list[dict[str, str]]] = defaultdict(list)
    blocks = {
        row.get("note_xml_id", ""): row
        for row in read_csv_rows(fresh_dir / "review" / "accepted_footnote_blocks.csv")
    }
    for row in read_csv_rows(fresh_dir / "review" / "accepted_footnote_transcriptions.csv"):
        try:
            page = int(row.get("page") or "0")
        except ValueError:
            continue
        block = blocks.get(row.get("note_xml_id", ""), {})
        bbox = parse_bbox(block.get("note_bbox", ""))
        row = dict(row)
        row["_sort_y"] = str(bbox_top(block.get("note_bbox", "")) if bbox else 0)
        by_page[page].append(row)

    previous: dict[int, dict[str, str]] = {}
    for page, rows in by_page.items():
        rows.sort(key=lambda row: (int(row.get("_sort_y") or "0"), int(row.get("n") or "0")))
        if rows:
            previous[page + 1] = rows[-1]
    return previous


def load_pages(fresh_dir: Path, manifest_path: Path) -> tuple[list[HocrPage], dict[int, tuple[int, int]], dict[int, str]]:
    manifest = load_manifest(manifest_path)
    pages: list[HocrPage] = []
    image_sizes: dict[int, tuple[int, int]] = {}
    image_paths: dict[int, str] = {}
    for page in manifest.get("pages", []):
        pdf_page = int(page.get("pdf_page") or page.get("seq") or 0)
        if not pdf_page:
            continue
        paths = output_paths(fresh_dir, pdf_page)
        hocr_path = Path(paths["hocr"])
        if not hocr_path.exists():
            continue
        hocr_page = parse_hocr(hocr_path, pdf_page)
        if not hocr_page.bbox:
            continue
        pages.append(hocr_page)
        image_sizes[pdf_page] = (hocr_page.bbox[2] - hocr_page.bbox[0], hocr_page.bbox[3] - hocr_page.bbox[1])
        image_paths[pdf_page] = str(paths["image"])
    return pages, image_sizes, image_paths


def audit(
    xml_path: Path,
    manifest_path: Path,
    fresh_dir: Path,
    max_gap: int,
    include_weak: bool = False,
) -> list[dict[str, str]]:
    root = ET.parse(xml_path).getroot()
    by_id = element_by_id(root)
    parents = parent_map(root)
    previous_notes = previous_note_lookup(fresh_dir)
    pages, image_sizes, image_paths = load_pages(fresh_dir, manifest_path)
    rows: list[dict[str, str]] = []

    for page in pages:
        _width, height = image_sizes[page.page]
        separator = footnote_separator(page, height)
        if separator is None:
            continue
        candidates = initial_lines_below_separator(page, height, separator, max_gap=max_gap)
        previous = previous_notes.get(page.page, {})
        strength, reason = continuation_strength(previous.get("transcription", ""), candidates)
        if strength == "weak" and not include_weak:
            continue
        for line in candidates:
            line_id = f"beck-fresh-diplomatic-p{page.page:04d}-l{line.index:03d}"
            body = is_body_line(by_id.get(line_id), parents)
            previous_text = previous.get("transcription", "")
            previous_tail = normalize_ws(previous_text)[-90:]
            rows.append(
                {
                    "page": str(page.page),
                    "image_path": image_paths.get(page.page, ""),
                    "separator_bbox": bbox_str(separator),
                    "line_index": str(line.index),
                    "line_bbox": bbox_str(line.bbox) if line.bbox else "",
                    "line_text": line.text,
                    "emitted_as_body": str(body).lower(),
                    "suggested_previous_page": previous.get("page", ""),
                    "suggested_previous_note_xml_id": previous.get("note_xml_id", ""),
                    "suggested_previous_n": previous.get("n", ""),
                    "previous_note_tail": previous_tail,
                    "candidate_strength": strength,
                    "reason": reason,
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xml", default=DEFAULT_DIPLOMATIC_OUTPUT)
    parser.add_argument("--manifest", default=DEFAULT_DIPLOMATIC_MANIFEST)
    parser.add_argument("--fresh-dir", default=DEFAULT_FRESH_DIR)
    parser.add_argument(
        "--out",
        default="output/beck2020_fresh_diplomatic_audit/footnote_continuation_candidates.csv",
    )
    parser.add_argument("--max-gap", type=int, default=180)
    parser.add_argument("--include-weak", action="store_true")
    parser.add_argument("--fail-on-body", action="store_true")
    args = parser.parse_args()

    rows = audit(Path(args.xml), Path(args.manifest), Path(args.fresh_dir), args.max_gap, args.include_weak)
    write_csv(Path(args.out), rows)
    body_rows = [
        row
        for row in rows
        if row.get("emitted_as_body") == "true" and row.get("candidate_strength") == "strong"
    ]
    print(f"Wrote {len(rows)} continuation candidates to {args.out}")
    print(f"Strong body-line candidates: {len(body_rows)}")
    return 1 if args.fail_on_body and body_rows else 0


if __name__ == "__main__":
    sys.exit(main())
