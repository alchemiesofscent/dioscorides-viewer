#!/usr/bin/env python3
"""Build the Beck fresh-OCR footnote review sidecars.

This does not rewrite the TEI. It packages page-image, hOCR, note, marker, and
current TEI evidence for the standalone review tool, and initializes the
accepted/rejected decision CSVs consumed by ``ocr_beck_fresh_pilot.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from ocr_beck_fresh_pilot import (
    NS,
    XML_ID,
    FootnoteBlock,
    HocrPage,
    Line,
    MarkerCandidate,
    bbox_str,
    footnote_blocks_for_page,
    is_high_confidence_marker,
    marker_candidates_for_page,
    marker_from_word,
    output_paths,
    parse_hocr,
    word_xml_id,
)


ACCEPTED_FIELDS = [
    "page",
    "ref_xml_id",
    "note_xml_id",
    "n",
    "marker_bbox",
    "note_bbox",
    "confidence",
    "method",
    "reviewer",
]
ACCEPTED_BLOCK_FIELDS = [
    "page",
    "note_xml_id",
    "n",
    "note_bbox",
    "first_line",
    "last_line",
    "confidence",
    "method",
    "reviewer",
]
REJECTED_FIELDS = [
    "page",
    "ref_xml_id",
    "note_xml_id",
    "n",
    "marker_bbox",
    "note_bbox",
    "reason",
    "method",
    "reviewer",
]
FIXTURE_ACCEPTS = {
    (45, "27"),
    (58, "47"),
}
XML = "http://www.w3.org/XML/1998/namespace"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: value for key, value in row.items() if key is not None} for row in csv.DictReader(handle)]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_missing_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]], key_fields: list[str]) -> int:
    existing = read_csv(path) if path.exists() else []
    seen = {tuple(row.get(field, "") for field in key_fields) for row in existing}
    additions = [row for row in rows if tuple(row.get(field, "") for field in key_fields) not in seen]
    if additions:
        write_csv(path, fieldnames, existing + additions)
    elif not path.exists():
        write_csv(path, fieldnames, [])
    return len(additions)


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def page_manifest(manifest: dict) -> dict[int, dict]:
    pages = {}
    for page in manifest.get("pages", []):
        raw = page.get("pdf_page") or page.get("seq") or page.get("book_page")
        try:
            pages[int(raw)] = page
        except (TypeError, ValueError):
            continue
    return pages


def needs_review(row: dict[str, str]) -> bool:
    status = row.get("status", "")
    method = row.get("method", "")
    if status == "linked" and method.startswith("accepted-sidecar"):
        return False
    if status != "linked":
        return True
    marker_text = row.get("marker_text", "")
    high_conf = row.get("high_confidence_marker", "").lower()
    if high_conf:
        return high_conf != "true"
    return not bool(re.search(r"[\^*†‡]|\d", marker_text))


def parse_tei_state(path: Path) -> dict[int, dict[str, list[dict[str, str]]]]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    state: dict[int, dict[str, list[dict[str, str]]]] = {}
    current_page = 0
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            try:
                current_page = int(element.get("n") or "0")
            except ValueError:
                current_page = 0
            continue
        if not current_page:
            continue
        bucket = state.setdefault(current_page, {"refs": [], "notes": []})
        xml_id = element.get(XML_ID) or element.get(f"{{{XML}}}id") or ""
        if tag == "ref" and element.get("type") == "footnote-ref":
            bucket["refs"].append(
                {
                    "xml_id": xml_id,
                    "target": element.get("target", ""),
                    "n": element.get("n", ""),
                    "text": "".join(element.itertext()).strip(),
                }
            )
        elif tag == "note" and element.get("type") == "footnote":
            bucket["notes"].append(
                {
                    "xml_id": xml_id,
                    "corresp": element.get("corresp", ""),
                    "n": element.get("n", ""),
                    "subtype": element.get("subtype", ""),
                    "resp": element.get("resp", ""),
                    "bbox": element.get("bbox", ""),
                    "text": " ".join("".join(element.itertext()).split())[:500],
                }
            )
    return state


def line_payload(line: Line, page_height: int) -> dict:
    bottom_zone = bool(line.bbox and line.bbox[1] >= page_height * 0.72)
    words = []
    for word in line.words:
        marker = marker_from_word(word)
        words.append(
            {
                "id": word_xml_id(word),
                "index": word.word_index,
                "text": word.text,
                "bbox": bbox_str(word.bbox) if word.bbox else "",
                "confidence": word.confidence,
                "low_confidence": bool(word.confidence is not None and word.confidence < 60),
                "marker_base": marker[0] if marker else "",
                "marker_text": marker[1] if marker else "",
            }
        )
    return {
        "index": line.index,
        "text": line.text,
        "bbox": bbox_str(line.bbox) if line.bbox else "",
        "bottom_zone": bottom_zone,
        "words": words,
    }


def block_payload(block: FootnoteBlock) -> dict:
    return {
        "xml_id": block.xml_id,
        "n": block.raw_n,
        "ordinal": block.ordinal,
        "bbox": bbox_str(block.bbox) if block.bbox else "",
        "first_line": block.first_line.index,
        "line_count": len(block.lines),
        "text": block.text,
    }


def marker_payload(marker: MarkerCandidate, words_by_id: dict[str, dict]) -> dict:
    word = words_by_id.get(marker.word_xml_id, {})
    return {
        "ref_xml_id": marker.ref_id,
        "word_xml_id": marker.word_xml_id,
        "line": marker.line_index,
        "word": marker.word_index,
        "base_text": marker.base_text,
        "marker_text": marker.marker_text,
        "line_text": marker.line_text,
        "bbox": bbox_str(marker.bbox) if marker.bbox else "",
        "confidence": word.get("confidence"),
        "high_confidence": is_high_confidence_marker(marker),
    }


def page_context(page: HocrPage, width: int, height: int) -> dict:
    blocks = footnote_blocks_for_page(page, height)
    markers = marker_candidates_for_page(page, blocks)
    lines = [line_payload(line, height) for line in page.lines]
    words_by_id = {word["id"]: word for line in lines for word in line["words"]}
    return {
        "lines": lines,
        "separators": [bbox_str(bbox) for bbox in page.separators],
        "footnote_blocks": [block_payload(block) for block in blocks],
        "marker_candidates": [marker_payload(marker, words_by_id) for marker in markers],
        "image": {
            "width": width,
            "height": height,
            "src": f"../../ocr/beck2020_fresh/images/beck-{page.page:04d}.png",
        },
    }


def seed_accept_rows(
    qa_rows: list[dict[str, str]],
    contexts: dict[int, dict],
) -> list[dict[str, str]]:
    seeds = []
    for row in qa_rows:
        try:
            page = int(row.get("page", "0"))
        except ValueError:
            continue
        n = row.get("raw_n", "")
        if (page, n) not in FIXTURE_ACCEPTS or not row.get("ref_xml_id") or not row.get("note_xml_id"):
            continue
        context = contexts.get(page, {})
        marker = next(
            (
                candidate
                for candidate in context.get("marker_candidates", [])
                if candidate.get("ref_xml_id") == row.get("ref_xml_id")
            ),
            {},
        )
        note = next(
            (
                block
                for block in context.get("footnote_blocks", [])
                if block.get("xml_id") == row.get("note_xml_id")
            ),
            {},
        )
        seeds.append(
            {
                "page": str(page),
                "ref_xml_id": row.get("ref_xml_id", ""),
                "note_xml_id": row.get("note_xml_id", ""),
                "n": n,
                "marker_bbox": marker.get("bbox") or row.get("marker_bbox", ""),
                "note_bbox": note.get("bbox") or row.get("note_bbox", ""),
                "confidence": "1.0",
                "method": "plan-fixture",
                "reviewer": "beck-fresh-footnote-plan",
            }
        )
    return seeds


def build_review_queue(
    qa_path: Path,
    hocr_dir: Path,
    manifest_path: Path,
    tei_path: Path,
    out_path: Path,
    accepted_path: Path,
    accepted_blocks_path: Path,
    rejected_path: Path,
) -> dict:
    qa_rows = read_csv(qa_path)
    manifest = load_manifest(manifest_path)
    manifest_pages = page_manifest(manifest)
    tei_state = parse_tei_state(tei_path)
    review_rows = [row for row in qa_rows if needs_review(row)]
    needed_pages = sorted({int(row["page"]) for row in qa_rows if row.get("page", "").isdigit()})
    contexts: dict[int, dict] = {}

    for page_number in needed_pages:
        hocr_path = output_paths(hocr_dir.parent, page_number)["hocr"]
        page_meta = manifest_pages.get(page_number, {})
        if not hocr_path.exists():
            continue
        hocr_page = parse_hocr(hocr_path, page_number)
        width = int(page_meta.get("width") or (hocr_page.bbox[2] if hocr_page.bbox else 0))
        height = int(page_meta.get("height") or (hocr_page.bbox[3] if hocr_page.bbox else 0))
        contexts[page_number] = page_context(hocr_page, width, height)

    seed_rows = seed_accept_rows(qa_rows, contexts)
    accepted_added = append_missing_csv_rows(
        accepted_path,
        ACCEPTED_FIELDS,
        seed_rows,
        ["page", "ref_xml_id", "note_xml_id"],
    )
    if not rejected_path.exists():
        write_csv(rejected_path, REJECTED_FIELDS, [])
    if not accepted_blocks_path.exists():
        write_csv(accepted_blocks_path, ACCEPTED_BLOCK_FIELDS, [])

    rows = []
    row_index = 0
    for row in review_rows:
        page = int(row["page"])
        context = contexts.get(page, {})
        markers = context.get("marker_candidates", [])
        marker_sets = [markers]
        if row.get("status") == "unresolved-markers-without-notes" and markers:
            marker_sets = [[marker] for marker in markers]
        note_id = row.get("note_xml_id", "")
        note = next((block for block in context.get("footnote_blocks", []) if block.get("xml_id") == note_id), {})
        for row_markers in marker_sets:
            row_index += 1
            rows.append(
                {
                    "id": f"beck-fresh-review-{row_index:04d}",
                    "page": page,
                    "status": row.get("status", ""),
                    "method": row.get("method", ""),
                    "raw_n": row.get("raw_n", ""),
                    "problem_type": problem_type(row),
                    "qa": row,
                    "note": note,
                    "marker_candidates": row_markers,
                    "page_context": context,
                    "current_tei": tei_state.get(page, {"refs": [], "notes": []}),
                }
            )

    payload = {
        "schema": "beck-fresh-footnote-review-v1",
        "source_files": {
            "footnote_links": qa_path.as_posix(),
            "tei": tei_path.as_posix(),
            "manifest": manifest_path.as_posix(),
        },
        "decision_files": {
            "accepted": accepted_path.as_posix(),
            "accepted_blocks": accepted_blocks_path.as_posix(),
            "rejected": rejected_path.as_posix(),
        },
        "summary": {
            "qa_rows": len(qa_rows),
            "review_rows": len(rows),
            "problem_pages": len({row["page"] for row in rows}),
            "accepted_seed_rows_added": accepted_added,
        },
        "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def problem_type(row: dict[str, str]) -> str:
    status = row.get("status", "")
    if status == "linked":
        return "linked-low-confidence-marker"
    if status == "unresolved-markers-without-notes":
        return "marker-without-bottom-note"
    if status == "unresolved-ambiguous":
        return "ambiguous-marker-count"
    if status == "unresolved-no-marker":
        return "bottom-note-without-marker"
    return status or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qa", default="ocr/beck2020_fresh/qa/footnote_links.csv")
    parser.add_argument("--hocr-dir", default="ocr/beck2020_fresh/hocr")
    parser.add_argument("--manifest", default="editions/beck2020_fresh/manifest.json")
    parser.add_argument("--tei", default="output/beck2020_fresh_epidoc.xml")
    parser.add_argument("--out", default="ocr/beck2020_fresh/review/footnote_review_queue.json")
    parser.add_argument("--accepted", default="ocr/beck2020_fresh/review/accepted_footnote_links.csv")
    parser.add_argument("--accepted-blocks", default="ocr/beck2020_fresh/review/accepted_footnote_blocks.csv")
    parser.add_argument("--rejected", default="ocr/beck2020_fresh/review/rejected_footnote_candidates.csv")
    args = parser.parse_args()

    try:
        payload = build_review_queue(
            Path(args.qa),
            Path(args.hocr_dir),
            Path(args.manifest),
            Path(args.tei),
            Path(args.out),
            Path(args.accepted),
            Path(args.accepted_blocks),
            Path(args.rejected),
        )
    except (FileNotFoundError, ET.ParseError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    summary = payload["summary"]
    print(
        "Wrote "
        f"{args.out} with {summary['review_rows']} rows across {summary['problem_pages']} pages"
    )
    print(f"Wrote/updated {args.accepted}")
    print(f"Wrote/updated {args.accepted_blocks}")
    print(f"Wrote/updated {args.rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
