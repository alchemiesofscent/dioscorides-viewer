#!/usr/bin/env python3
"""Run a page-image-first Beck fresh footnote pass.

This runner deliberately does not read ``footnote_review_queue.json``. It
creates one model case per selected PDF page from the fresh manifest, attaches
the rendered page image, and includes hOCR only as helper evidence. Accepted
high-confidence results are written to the existing fresh-footnote sidecars so
``ocr_beck_fresh_pilot.py`` can consume them on rebuild.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_beck_fresh_pilot import (  # noqa: E402
    bbox_str,
    footnote_blocks_for_page,
    is_high_confidence_marker,
    marker_candidates_for_page,
    output_paths,
    parse_hocr,
    parse_pages,
)


DEFAULT_MANIFEST = "editions/beck2020_fresh/manifest.json"
DEFAULT_OCR_DIR = "ocr/beck2020_fresh"
DEFAULT_OUT_DIR = "ocr/beck2020_fresh/review/image_scratch_pass"
DEFAULT_ACCEPTED = "ocr/beck2020_fresh/review/accepted_footnote_links.csv"
DEFAULT_ACCEPTED_BLOCKS = "ocr/beck2020_fresh/review/accepted_footnote_blocks.csv"
DEFAULT_ACCEPTED_TRANSCRIPTIONS = "ocr/beck2020_fresh/review/accepted_footnote_transcriptions.csv"
DEFAULT_REJECTED = "ocr/beck2020_fresh/review/rejected_footnote_candidates.csv"
DEFAULT_MODEL = "gpt-5.5"
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
ACCEPTED_TRANSCRIPTION_FIELDS = [
    "page",
    "note_xml_id",
    "n",
    "transcription",
    "confidence",
    "method",
    "reviewer",
    "evidence",
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


@dataclass(frozen=True)
class PageEvidence:
    page: int
    manifest: dict[str, Any]
    image: Path
    previous_image: Path | None
    hocr: Path
    width: int
    height: int
    lines: list[dict[str, Any]]
    bottom_lines: list[dict[str, Any]]
    footnote_blocks: list[dict[str, Any]]
    marker_candidates: list[dict[str, Any]]
    separators: list[str]
    suggested_note_xml_ids: list[str]
    suggested_ref_xml_ids: list[str]


@dataclass(frozen=True)
class Case:
    case_id: str
    evidence: PageEvidence
    panel: Path
    overview: Path
    bottom_crop: Path
    prompt: Path


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("MAGICK_TIME_LIMIT", "1800")
    return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout, env=env)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_pages(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    pages: dict[int, dict[str, Any]] = {}
    for page in manifest.get("pages", []):
        raw = page.get("pdf_page") or page.get("seq") or page.get("page")
        try:
            page_number = int(raw)
        except (TypeError, ValueError):
            continue
        pages[page_number] = page
    return pages


def image_size(path: Path) -> tuple[int, int]:
    result = run(["identify", "-format", "%w %h", str(path)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"identify failed for {path}")
    width, height = result.stdout.strip().split()
    return int(width), int(height)


def parse_bbox(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(float(part)) for part in str(value).split() if part]
    if len(parts) != 4:
        return None
    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def crop_arg(bbox: tuple[int, int, int, int]) -> str:
    left, top, right, bottom = bbox
    return f"{right - left}x{bottom - top}+{left}+{top}"


def draw_box_args(color: str, boxes: list[tuple[int, int, int, int]], stroke: int = 6) -> list[str]:
    args: list[str] = []
    for left, top, right, bottom in boxes:
        args.extend(
            [
                "-stroke",
                color,
                "-strokewidth",
                str(stroke),
                "-fill",
                "none",
                "-draw",
                f"rectangle {left},{top} {right},{bottom}",
            ]
        )
    return args


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_line_number(value: Any) -> str:
    text = normalize_text(value)
    return text if text.isdigit() else ""


def line_payload(line: Any, page_height: int) -> dict[str, Any]:
    return {
        "index": line.index,
        "text": line.text,
        "bbox": bbox_str(line.bbox) if line.bbox else "",
        "bottom_zone": bool(line.bbox and line.bbox[1] >= page_height * 0.68),
        "words": [
            {
                "index": word.word_index,
                "text": word.text,
                "bbox": bbox_str(word.bbox) if word.bbox else "",
                "confidence": word.confidence,
            }
            for word in line.words
        ],
    }


def block_payload(block: Any) -> dict[str, Any]:
    return {
        "note_xml_id": block.xml_id,
        "n": block.raw_n,
        "ordinal": block.ordinal,
        "bbox": bbox_str(block.bbox) if block.bbox else "",
        "first_line": block.first_line.index,
        "last_line": block.lines[-1].index if block.lines else "",
        "text": block.text,
    }


def marker_payload(marker: Any) -> dict[str, Any]:
    return {
        "ref_xml_id": marker.ref_id,
        "line": marker.line_index,
        "word": marker.word_index,
        "base_text": marker.base_text,
        "marker_text": marker.marker_text,
        "line_text": marker.line_text,
        "bbox": bbox_str(marker.bbox) if marker.bbox else "",
        "high_confidence_hocr_marker": is_high_confidence_marker(marker),
    }


def page_image_path(ocr_dir: Path, page: int, page_meta: dict[str, Any]) -> Path:
    facs = str(page_meta.get("facs") or page_meta.get("tei_facs") or "").strip()
    if facs:
        path = Path(facs)
        if path.exists():
            return path
        candidate = ocr_dir / "images" / path.name
        if candidate.exists():
            return candidate
    return output_paths(ocr_dir, page)["image"]


def build_page_evidence(page: int, page_meta: dict[str, Any], ocr_dir: Path) -> PageEvidence:
    image = page_image_path(ocr_dir, page, page_meta)
    hocr = output_paths(ocr_dir, page)["hocr"]
    if not image.exists():
        raise FileNotFoundError(image)
    if not hocr.exists():
        raise FileNotFoundError(hocr)
    width = int(page_meta.get("width") or 0)
    height = int(page_meta.get("height") or 0)
    if width <= 0 or height <= 0:
        width, height = image_size(image)
    hocr_page = parse_hocr(hocr, page)
    lines = [line_payload(line, height) for line in hocr_page.lines]
    bottom_lines = [line for line in lines if line["bottom_zone"]]
    if not bottom_lines:
        bottom_lines = lines[-12:]
    blocks = footnote_blocks_for_page(hocr_page, height)
    markers = marker_candidates_for_page(hocr_page, blocks)
    previous_image = output_paths(ocr_dir, page - 1)["image"] if page > 1 else None
    if previous_image is not None and not previous_image.exists():
        previous_image = None
    return PageEvidence(
        page=page,
        manifest=page_meta,
        image=image,
        previous_image=previous_image,
        hocr=hocr,
        width=width,
        height=height,
        lines=lines,
        bottom_lines=bottom_lines,
        footnote_blocks=[block_payload(block) for block in blocks],
        marker_candidates=[marker_payload(marker) for marker in markers],
        separators=[bbox_str(bbox) for bbox in hocr_page.separators],
        suggested_note_xml_ids=[f"beck-fresh-fn-p{page:04d}-scratch-{index:03d}" for index in range(1, 7)],
        suggested_ref_xml_ids=[f"beck-fresh-ref-p{page:04d}-scratch-{index:03d}" for index in range(1, 7)],
    )


def evidence_payload(evidence: PageEvidence) -> dict[str, Any]:
    return {
        "page": evidence.page,
        "image": evidence.image.as_posix(),
        "previous_page_image": evidence.previous_image.as_posix() if evidence.previous_image else "",
        "hocr": evidence.hocr.as_posix(),
        "width": evidence.width,
        "height": evidence.height,
        "section": evidence.manifest.get("section", ""),
        "detected_bottom_notes": evidence.footnote_blocks,
        "marker_candidates": evidence.marker_candidates,
        "hocr_separators": evidence.separators,
        "hocr_bottom_zone_lines": evidence.bottom_lines,
        "suggested_note_xml_ids": evidence.suggested_note_xml_ids,
        "suggested_ref_xml_ids": evidence.suggested_ref_xml_ids,
    }


def write_case(evidence: PageEvidence, out_dir: Path, force: bool = False) -> Case:
    case_id = f"beck-fresh-image-scratch-p{evidence.page:04d}"
    panel_dir = out_dir / "panels"
    crop_dir = out_dir / "crops"
    prompt_dir = out_dir / "prompts"
    for path in (panel_dir, crop_dir, prompt_dir):
        path.mkdir(parents=True, exist_ok=True)
    overview = crop_dir / f"{case_id}-overview.png"
    bottom_crop = crop_dir / f"{case_id}-bottom.png"
    panel = panel_dir / f"{case_id}.png"
    prompt = prompt_dir / f"{case_id}.txt"
    if not force and panel.exists() and overview.exists() and bottom_crop.exists() and prompt.exists():
        return Case(case_id=case_id, evidence=evidence, panel=panel, overview=overview, bottom_crop=bottom_crop, prompt=prompt)

    marker_boxes = [box for box in (parse_bbox(row.get("bbox")) for row in evidence.marker_candidates) if box]
    note_boxes = [box for box in (parse_bbox(row.get("bbox")) for row in evidence.footnote_blocks) if box]
    separator_boxes = [box for box in (parse_bbox(row) for row in evidence.separators) if box]
    draw_args = (
        draw_box_args("#b13c2f", marker_boxes, stroke=7)
        + draw_box_args("#a2761d", note_boxes, stroke=8)
        + draw_box_args("#146c5c", separator_boxes, stroke=5)
    )
    bottom_top = max(0, int(evidence.height * 0.60))
    bottom_box = (0, bottom_top, evidence.width, evidence.height)
    commands = [
        ["convert", str(evidence.image), *draw_args, "-resize", "38%", str(overview)],
        [
            "convert",
            str(evidence.image),
            *draw_args,
            "-crop",
            crop_arg(bottom_box),
            "+repage",
            "-resize",
            "170%",
            "-normalize",
            str(bottom_crop),
        ],
    ]
    for cmd in commands:
        result = run(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"ImageMagick failed: {' '.join(cmd)}")
    title = f"Beck fresh image-scratch footnote pass | page {evidence.page}"
    result = run(
        [
            "montage",
            "-title",
            title,
            str(overview),
            str(bottom_crop),
            "-tile",
            "1x2",
            "-geometry",
            "+14+14",
            "-background",
            "white",
            str(panel),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"montage failed for {panel}")
    prompt.write_text(assemble_prompt(evidence, panel), encoding="utf-8")
    return Case(case_id=case_id, evidence=evidence, panel=panel, overview=overview, bottom_crop=bottom_crop, prompt=prompt)


def assemble_prompt(evidence: PageEvidence, panel: Path) -> str:
    return "\n".join(
        [
            "You are doing a fresh page-image scratch pass for Beck 2020 footnotes.",
            "",
            "Attached images:",
            f"- visual panel with hOCR helper boxes: {panel.as_posix()}",
            f"- full 300dpi page image: {evidence.image.as_posix()}",
            f"- previous page image, if attached: {evidence.previous_image.as_posix() if evidence.previous_image else 'none'}",
            "",
            "Use the page image as authority. hOCR is helper evidence only. Do not rely on a previous review queue or older Beck XML.",
            "In the panel, red boxes are hOCR marker candidates, gold boxes are detected hOCR bottom-note blocks, and green boxes are separator rules.",
            "",
            "Task:",
            "1. Inspect the printed page for visible bottom notes below a footnote rule or in the lower note zone.",
            "2. For every visible bottom note, read its printed label and transcribe the note body exactly enough for TEI use, omitting the printed label because n carries it.",
            "3. Find the matching inline anchor evidence in the main text on this page. If the anchor is at the end of the previous page, use the previous page image evidence.",
            "4. Report unresolved or rejected evidence instead of guessing. Precision is more important than coverage.",
            "",
            "Return only one JSON object. No markdown fence. Use this schema:",
            "{",
            '  "page": 0,',
            '  "visible_bottom_notes": [',
            "    {",
            '      "n": "",',
            '      "note_xml_id": "",',
            '      "note_bbox": "",',
            '      "first_line": "",',
            '      "last_line": "",',
            '      "transcription": "",',
            '      "confidence": 0.0,',
            '      "evidence": ""',
            "    }",
            "  ],",
            '  "links": [',
            "    {",
            '      "n": "",',
            '      "ref_xml_id": "",',
            '      "note_xml_id": "",',
            '      "marker_bbox": "",',
            '      "note_bbox": "",',
            '      "confidence": 0.0,',
            '      "anchor_evidence": ""',
            "    }",
            "  ],",
            '  "rejected_candidates": [',
            "    {",
            '      "ref_xml_id": "",',
            '      "note_xml_id": "",',
            '      "n": "",',
            '      "marker_bbox": "",',
            '      "note_bbox": "",',
            '      "reason": "",',
            '      "confidence": 0.0',
            "    }",
            "  ],",
            '  "unresolved": [',
            "    {",
            '      "type": "",',
            '      "n": "",',
            '      "evidence": "",',
            '      "confidence": 0.0',
            "    }",
            "  ]",
            "}",
            "",
            "ID rules:",
            "- If a note matches detected_bottom_notes, use that note_xml_id.",
            "- If a note is visible in the image but missing from detected_bottom_notes, use the first unused suggested_note_xml_id.",
            "- If an anchor matches marker_candidates, use that ref_xml_id.",
            "- If the anchor is visible in the image but absent from marker_candidates, use the first unused suggested_ref_xml_id and provide marker_bbox.",
            "- For boxes, use image coordinates as 'left top right bottom' when you can identify them.",
            "- Set confidence >= 0.95 only when the image clearly supports the note label, transcription, anchor, and boxes.",
            "",
            "Page hOCR helper evidence JSON:",
            json.dumps(evidence_payload(evidence), ensure_ascii=False, indent=2),
        ]
    )


def strip_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def codex_case(case: Case, model: str, timeout: int, out_dir: Path, resume: bool) -> dict[str, Any]:
    response_json = out_dir / "responses" / f"{case.case_id}.json"
    raw_response = out_dir / "raw_responses" / f"{case.case_id}.txt"
    if resume and response_json.exists():
        try:
            previous = json.loads(response_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        if previous.get("status") == "success":
            previous["resumed"] = True
            return previous
    response_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", prefix=f"{case.case_id}_", delete=False)
    response_text_path = Path(response_file.name)
    response_file.close()
    cmd = [
        "codex",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--output-last-message",
        str(response_text_path),
        "--model",
        model,
        "-i",
        str(case.panel),
        "-i",
        str(case.evidence.image),
    ]
    if case.evidence.previous_image is not None:
        cmd.extend(["-i", str(case.evidence.previous_image)])
    cmd.extend(["--", case.prompt.read_text(encoding="utf-8")])
    started = time.time()
    try:
        result = run(cmd, timeout=timeout)
        elapsed = round(time.time() - started, 1)
        response_text = response_text_path.read_text(encoding="utf-8", errors="replace")
        raw_response.write_text(response_text, encoding="utf-8")
        if result.returncode != 0:
            return {
                "case_id": case.case_id,
                "page": case.evidence.page,
                "status": "error",
                "elapsed": elapsed,
                "error": (result.stderr or result.stdout)[-3000:],
                "raw_response": raw_response.as_posix(),
            }
        proposal = strip_json_response(response_text or result.stdout)
        return {
            "case_id": case.case_id,
            "page": case.evidence.page,
            "status": "success",
            "elapsed": elapsed,
            "proposal": proposal,
            "raw_response": raw_response.as_posix(),
        }
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"case_id": case.case_id, "page": case.evidence.page, "status": "error", "error": str(exc)}
    finally:
        try:
            os.unlink(response_text_path)
        except OSError:
            pass


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: value for key, value in row.items() if key is not None} for row in csv.DictReader(handle)]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, str], fields: list[str]) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in fields)


def confidence(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def proposal_notes(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    notes = proposal.get("visible_bottom_notes")
    if isinstance(notes, list):
        return [note for note in notes if isinstance(note, dict)]
    if proposal.get("decision") in {"accept_link", "propose_note_block"}:
        return [proposal]
    return []


def proposal_links(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    links = proposal.get("links")
    if isinstance(links, list):
        return [link for link in links if isinstance(link, dict)]
    if proposal.get("decision") == "accept_link":
        return [proposal]
    if proposal.get("decision") == "propose_note_block" and proposal.get("ref_xml_id"):
        return [proposal]
    return []


def proposal_rejections(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    rejected = proposal.get("rejected_candidates")
    if isinstance(rejected, list):
        return [row for row in rejected if isinstance(row, dict)]
    if proposal.get("decision") == "reject_marker":
        return [proposal]
    return []


def note_index(notes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed = {}
    for note in notes:
        note_xml_id = normalize_text(note.get("note_xml_id"))
        if note_xml_id:
            indexed[note_xml_id] = note
    return indexed


def apply_results(
    results: list[dict[str, Any]],
    accepted_path: Path,
    accepted_blocks_path: Path,
    accepted_transcriptions_path: Path,
    rejected_path: Path,
    min_confidence: float,
) -> dict[str, int]:
    accepted = read_csv(accepted_path)
    accepted_blocks = read_csv(accepted_blocks_path)
    accepted_transcriptions = read_csv(accepted_transcriptions_path)
    rejected = read_csv(rejected_path)
    accepted_seen = {row_key(row, ["page", "ref_xml_id", "note_xml_id"]) for row in accepted}
    block_seen = {row_key(row, ["page", "note_xml_id"]) for row in accepted_blocks}
    transcription_seen = {row_key(row, ["page", "note_xml_id"]) for row in accepted_transcriptions}
    rejected_seen = {row_key(row, ["page", "ref_xml_id", "reason"]) for row in rejected}
    counts = {
        "accepted_added": 0,
        "accepted_blocks_added": 0,
        "accepted_transcriptions_added": 0,
        "rejected_added": 0,
        "below_confidence": 0,
        "links_without_transcription": 0,
    }
    for result in results:
        if result.get("status") != "success":
            continue
        proposal = result.get("proposal") or {}
        notes = proposal_notes(proposal)
        notes_by_id = note_index(notes)
        for note in notes:
            conf = confidence(note.get("confidence"))
            if conf < min_confidence:
                counts["below_confidence"] += 1
                continue
            page = normalize_text(note.get("page") or proposal.get("page") or result.get("page"))
            note_xml_id = normalize_text(note.get("note_xml_id"))
            n = normalize_text(note.get("n"))
            transcription = normalize_text(note.get("transcription"))
            if not (page and note_xml_id and n and transcription):
                continue
            note_bbox = normalize_text(note.get("note_bbox"))
            first_line = normalize_line_number(note.get("first_line"))
            last_line = normalize_line_number(note.get("last_line"))
            if note_bbox or (first_line and last_line):
                block_row = {
                    "page": page,
                    "note_xml_id": note_xml_id,
                    "n": n,
                    "note_bbox": note_bbox,
                    "first_line": first_line,
                    "last_line": last_line,
                    "confidence": str(conf),
                    "method": "model-image-scratch-pass",
                    "reviewer": "codex-image-scratch-footnote-pass",
                }
                key = row_key(block_row, ["page", "note_xml_id"])
                if key not in block_seen:
                    accepted_blocks.append(block_row)
                    block_seen.add(key)
                    counts["accepted_blocks_added"] += 1
            transcription_row = {
                "page": page,
                "note_xml_id": note_xml_id,
                "n": n,
                "transcription": transcription,
                "confidence": str(conf),
                "method": "model-image-scratch-pass",
                "reviewer": "codex-image-scratch-footnote-pass",
                "evidence": normalize_text(note.get("evidence")),
            }
            key = row_key(transcription_row, ["page", "note_xml_id"])
            if key not in transcription_seen:
                accepted_transcriptions.append(transcription_row)
                transcription_seen.add(key)
                counts["accepted_transcriptions_added"] += 1
        for link in proposal_links(proposal):
            conf = confidence(link.get("confidence"))
            if conf < min_confidence:
                counts["below_confidence"] += 1
                continue
            page = normalize_text(link.get("page") or proposal.get("page") or result.get("page"))
            ref_xml_id = normalize_text(link.get("ref_xml_id"))
            note_xml_id = normalize_text(link.get("note_xml_id"))
            n = normalize_text(link.get("n"))
            if not (page and ref_xml_id and note_xml_id and n):
                continue
            transcription_key = (page, note_xml_id)
            if transcription_key not in transcription_seen:
                counts["links_without_transcription"] += 1
                continue
            row = {
                "page": page,
                "ref_xml_id": ref_xml_id,
                "note_xml_id": note_xml_id,
                "n": n,
                "marker_bbox": normalize_text(link.get("marker_bbox")),
                "note_bbox": normalize_text(link.get("note_bbox") or notes_by_id.get(note_xml_id, {}).get("note_bbox")),
                "confidence": str(conf),
                "method": "model-image-scratch-pass",
                "reviewer": "codex-image-scratch-footnote-pass",
            }
            key = row_key(row, ["page", "ref_xml_id", "note_xml_id"])
            if key not in accepted_seen:
                accepted.append(row)
                accepted_seen.add(key)
                counts["accepted_added"] += 1
        for candidate in proposal_rejections(proposal):
            conf = confidence(candidate.get("confidence"))
            if conf < min_confidence:
                counts["below_confidence"] += 1
                continue
            page = normalize_text(candidate.get("page") or proposal.get("page") or result.get("page"))
            ref_xml_id = normalize_text(candidate.get("ref_xml_id"))
            reason = normalize_text(candidate.get("reason")) or "model-image-scratch-reject"
            if not (page and ref_xml_id):
                continue
            row = {
                "page": page,
                "ref_xml_id": ref_xml_id,
                "note_xml_id": normalize_text(candidate.get("note_xml_id")),
                "n": normalize_text(candidate.get("n")),
                "marker_bbox": normalize_text(candidate.get("marker_bbox")),
                "note_bbox": normalize_text(candidate.get("note_bbox")),
                "reason": reason,
                "method": "model-image-scratch-pass",
                "reviewer": "codex-image-scratch-footnote-pass",
            }
            key = row_key(row, ["page", "ref_xml_id", "reason"])
            if key not in rejected_seen:
                rejected.append(row)
                rejected_seen.add(key)
                counts["rejected_added"] += 1
    if counts["accepted_added"]:
        write_csv(accepted_path, ACCEPTED_FIELDS, accepted)
    elif not accepted_path.exists():
        write_csv(accepted_path, ACCEPTED_FIELDS, [])
    if counts["accepted_blocks_added"]:
        write_csv(accepted_blocks_path, ACCEPTED_BLOCK_FIELDS, accepted_blocks)
    elif not accepted_blocks_path.exists():
        write_csv(accepted_blocks_path, ACCEPTED_BLOCK_FIELDS, [])
    if counts["accepted_transcriptions_added"]:
        write_csv(accepted_transcriptions_path, ACCEPTED_TRANSCRIPTION_FIELDS, accepted_transcriptions)
    elif not accepted_transcriptions_path.exists():
        write_csv(accepted_transcriptions_path, ACCEPTED_TRANSCRIPTION_FIELDS, [])
    if counts["rejected_added"]:
        write_csv(rejected_path, REJECTED_FIELDS, rejected)
    elif not rejected_path.exists():
        write_csv(rejected_path, REJECTED_FIELDS, [])
    return counts


def choose_pages(args: argparse.Namespace, manifest: dict[str, Any]) -> list[int]:
    pages = manifest_pages(manifest)
    if args.all_pages:
        selected = sorted(pages)
    else:
        selected = parse_pages(args.pages)
    if not selected:
        raise SystemExit("No pages selected")
    missing = [page for page in selected if page not in pages]
    if missing:
        raise SystemExit(f"Pages missing from manifest: {missing[:10]}")
    return selected


def successful_response_exists(out_dir: Path, page: int) -> bool:
    response = out_dir / "responses" / f"beck-fresh-image-scratch-p{page:04d}.json"
    if not response.exists():
        return False
    try:
        data = json.loads(response.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return data.get("status") == "success"


def write_summary(out_dir: Path, args: argparse.Namespace, cases: list[Case], results: list[dict[str, Any]], applied: dict[str, int] | None) -> None:
    successful = sum(1 for result in results if result.get("status") == "success")
    errored = sum(1 for result in results if result.get("status") == "error")
    page_notes = 0
    page_links = 0
    unresolved = 0
    rejected = 0
    for result in results:
        proposal = result.get("proposal") or {}
        page_notes += len(proposal_notes(proposal))
        page_links += len(proposal_links(proposal))
        rejected += len(proposal_rejections(proposal))
        unresolved_rows = proposal.get("unresolved")
        if isinstance(unresolved_rows, list):
            unresolved += len(unresolved_rows)
    lines = [
        "# Beck Fresh Image-Scratch Footnote Pass",
        "",
        f"- Cases: {len(cases)}",
        f"- Model run: {str(args.run_codex).lower()}",
        f"- Model: `{args.model}`",
        f"- Min confidence: {args.min_confidence}",
        f"- Resume: {str(args.resume).lower()}",
        f"- Pending only: {str(args.pending_only).lower()}",
        f"- Force prep: {str(args.force_prep).lower()}",
        f"- Prep parallel: {args.prep_parallel}",
        f"- Model parallel: {args.max_parallel}",
        f"- Successful responses: {successful}",
        f"- Error responses: {errored}",
        f"- Proposed visible bottom notes: {page_notes}",
        f"- Proposed links: {page_links}",
        f"- Proposed rejected candidates: {rejected}",
        f"- Unresolved evidence rows: {unresolved}",
    ]
    if applied is not None:
        lines.extend(
            [
                f"- Accepted links added: {applied['accepted_added']}",
                f"- Accepted blocks added: {applied['accepted_blocks_added']}",
                f"- Accepted transcriptions added: {applied['accepted_transcriptions_added']}",
                f"- Rejected candidates added: {applied['rejected_added']}",
                f"- Below-confidence proposal rows kept as evidence only: {applied['below_confidence']}",
                f"- Links kept as evidence only because transcription was missing: {applied['links_without_transcription']}",
            ]
        )
    out_dir.joinpath("summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--ocr-dir", default=DEFAULT_OCR_DIR)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--pages", default="")
    parser.add_argument("--all-pages", action="store_true")
    parser.add_argument("--run-codex", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--prep-parallel", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--pending-only", action="store_true", help="Run only selected pages without a successful response JSON.")
    parser.add_argument("--force-prep", action="store_true", help="Regenerate panels, crops, and prompts even when they already exist.")
    parser.add_argument("--apply-high-confidence", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.95)
    parser.add_argument("--accepted", default=DEFAULT_ACCEPTED)
    parser.add_argument("--accepted-blocks", default=DEFAULT_ACCEPTED_BLOCKS)
    parser.add_argument("--accepted-transcriptions", default=DEFAULT_ACCEPTED_TRANSCRIPTIONS)
    parser.add_argument("--rejected", default=DEFAULT_REJECTED)
    args = parser.parse_args()

    require_command("identify")
    require_command("convert")
    require_command("montage")
    if args.run_codex:
        require_command("codex")
    if not args.all_pages and not args.pages:
        raise SystemExit("Use --pages or --all-pages")

    manifest = load_manifest(Path(args.manifest))
    pages = choose_pages(args, manifest)
    out_dir = Path(args.out_dir)
    for child in ("responses", "raw_responses"):
        (out_dir / child).mkdir(parents=True, exist_ok=True)
    if args.pending_only:
        original_count = len(pages)
        pages = [page for page in pages if not successful_response_exists(out_dir, page)]
        print(f"pending-only selected {len(pages)} of {original_count} pages", flush=True)
        if not pages:
            write_summary(out_dir, args, [], [], None)
            return 0
    page_map = manifest_pages(manifest)
    ocr_dir = Path(args.ocr_dir)
    cases: list[Case] = []

    def prepare_case(page: int) -> Case:
        evidence = build_page_evidence(page, page_map[page], ocr_dir)
        return write_case(evidence, out_dir, force=args.force_prep)

    prep_parallel = max(1, args.prep_parallel)
    if prep_parallel == 1:
        for page in pages:
            case = prepare_case(page)
            cases.append(case)
            print(f"case {case.case_id}: {case.panel}", flush=True)
    else:
        with ThreadPoolExecutor(max_workers=prep_parallel) as pool:
            futures = {pool.submit(prepare_case, page): page for page in pages}
            for future in as_completed(futures):
                case = future.result()
                cases.append(case)
                print(f"case {case.case_id}: {case.panel}", flush=True)
        cases.sort(key=lambda case: case.evidence.page)
    case_manifest = [
        {
            "case_id": case.case_id,
            "page": case.evidence.page,
            "image": case.evidence.image.as_posix(),
            "hocr": case.evidence.hocr.as_posix(),
            "panel": case.panel.as_posix(),
            "prompt": case.prompt.as_posix(),
        }
        for case in cases
    ]
    out_dir.joinpath("cases.json").write_text(json.dumps(case_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    results: list[dict[str, Any]] = []
    if args.run_codex:
        max_parallel = max(1, args.max_parallel)
        if max_parallel == 1:
            for case in cases:
                result = codex_case(case, args.model, args.timeout, out_dir, args.resume)
                results.append(result)
                out_dir.joinpath("responses", f"{case.case_id}.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                suffix = " resumed" if result.get("resumed") else ""
                print(f"codex {case.case_id}: {result.get('status')}{suffix}", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {pool.submit(codex_case, case, args.model, args.timeout, out_dir, args.resume): case for case in cases}
                for future in as_completed(futures):
                    case = futures[future]
                    result = future.result()
                    results.append(result)
                    out_dir.joinpath("responses", f"{case.case_id}.json").write_text(
                        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    suffix = " resumed" if result.get("resumed") else ""
                    print(f"codex {case.case_id}: {result.get('status')}{suffix}", flush=True)
        with out_dir.joinpath("proposals.jsonl").open("w", encoding="utf-8") as handle:
            for result in sorted(results, key=lambda row: int(row.get("page") or 0)):
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    applied = None
    if args.run_codex and args.apply_high_confidence:
        applied = apply_results(
            results,
            Path(args.accepted),
            Path(args.accepted_blocks),
            Path(args.accepted_transcriptions),
            Path(args.rejected),
            args.min_confidence,
        )
        print(
            "applied proposals: "
            f"{applied['accepted_added']} accepted links, "
            f"{applied['accepted_blocks_added']} accepted blocks, "
            f"{applied['accepted_transcriptions_added']} accepted transcriptions, "
            f"{applied['rejected_added']} rejected, "
            f"{applied['below_confidence']} below confidence, "
            f"{applied['links_without_transcription']} missing transcription",
            flush=True,
        )
    write_summary(out_dir, args, cases, results, applied)
    return 0 if not results or all(result.get("status") == "success" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
