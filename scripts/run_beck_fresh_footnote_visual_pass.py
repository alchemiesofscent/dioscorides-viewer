#!/usr/bin/env python3
"""Autonomous image-first pass for Beck fresh-OCR footnote ambiguities.

This script follows the Berendes-style pattern from PLAN.md: attach page/crop
images to a model prompt, treat the image as authoritative, and write structured
proposals. It does not patch TEI directly and does not consult older Beck XML.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ocr_beck_fresh_pilot import parse_pages


DEFAULT_QUEUE = "ocr/beck2020_fresh/review/footnote_review_queue.json"
DEFAULT_OCR_DIR = "ocr/beck2020_fresh"
DEFAULT_OUT_DIR = "ocr/beck2020_fresh/review/visual_pass"
DEFAULT_ACCEPTED = "ocr/beck2020_fresh/review/accepted_footnote_links.csv"
DEFAULT_ACCEPTED_BLOCKS = "ocr/beck2020_fresh/review/accepted_footnote_blocks.csv"
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
DEFAULT_PROBLEM_TYPES = (
    "bottom-note-without-marker",
    "ambiguous-marker-count",
    "marker-without-bottom-note",
    "linked-low-confidence-marker",
)


@dataclass(frozen=True)
class Case:
    row: dict
    case_id: str
    page_image: Path
    previous_page_image: Path | None
    panel: Path
    overview: Path
    body_crop: Path
    note_crop: Path
    prompt: Path


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)


def parse_bbox(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(float(part)) for part in str(value).strip().split() if part]
    if len(parts) != 4:
        return None
    left, top, right, bottom = parts
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def bbox_str(bbox: tuple[int, int, int, int] | None) -> str:
    return "" if bbox is None else " ".join(str(part) for part in bbox)


def union_boxes(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def clamp_box(
    bbox: tuple[int, int, int, int] | None,
    width: int,
    height: int,
    pad: int,
    fallback: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    if bbox is None:
        bbox = fallback
    left, top, right, bottom = bbox
    return (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + pad),
        min(height, bottom + pad),
    )


def crop_arg(bbox: tuple[int, int, int, int]) -> str:
    left, top, right, bottom = bbox
    return f"{right - left}x{bottom - top}+{left}+{top}"


def image_size(path: Path) -> tuple[int, int]:
    result = run(["identify", "-format", "%w %h", str(path)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"identify failed for {path}")
    width, height = result.stdout.strip().split()
    return int(width), int(height)


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


def marker_boxes(row: dict) -> list[tuple[int, int, int, int]]:
    boxes = []
    for candidate in row.get("marker_candidates") or []:
        bbox = parse_bbox(candidate.get("bbox"))
        if bbox:
            boxes.append(bbox)
    return boxes


def note_box(row: dict) -> tuple[int, int, int, int] | None:
    return parse_bbox((row.get("note") or {}).get("bbox") or (row.get("qa") or {}).get("note_bbox"))


def separator_boxes(row: dict) -> list[tuple[int, int, int, int]]:
    boxes = []
    for value in (row.get("page_context") or {}).get("separators") or []:
        bbox = parse_bbox(value)
        if bbox:
            boxes.append(bbox)
    return boxes


def row_image(row: dict, ocr_dir: Path) -> Path:
    image = ((row.get("page_context") or {}).get("image") or {}).get("src") or ""
    if image:
        path = (Path("tools/beck-fresh-footnotes") / image).resolve()
        if path.exists():
            return path
    return ocr_dir / "images" / f"beck-{int(row['page']):04d}.png"


def write_visuals(row: dict, ocr_dir: Path, out_dir: Path) -> Case:
    page = int(row["page"])
    case_id = f"{row['id']}-p{page:04d}"
    image = row_image(row, ocr_dir)
    previous_page_image = ocr_dir / "images" / f"beck-{page - 1:04d}.png" if page > 1 else None
    if previous_page_image is not None and not previous_page_image.exists():
        previous_page_image = None
    if not image.exists():
        raise FileNotFoundError(image)
    width, height = image_size(image)

    panel_dir = out_dir / "panels"
    crop_dir = out_dir / "crops"
    prompt_dir = out_dir / "prompts"
    for path in (panel_dir, crop_dir, prompt_dir):
        path.mkdir(parents=True, exist_ok=True)

    markers = marker_boxes(row)
    note = note_box(row)
    separators = separator_boxes(row)
    body_fallback = (0, int(height * 0.08), width, int(height * 0.76))
    note_fallback = (0, int(height * 0.68), width, height)
    body_box = clamp_box(union_boxes(markers), width, height, 150, body_fallback)
    foot_box = clamp_box(note, width, height, 160, note_fallback)

    overview = crop_dir / f"{case_id}-overview.png"
    body_crop = crop_dir / f"{case_id}-markers.png"
    note_crop = crop_dir / f"{case_id}-bottom.png"
    panel = panel_dir / f"{case_id}.png"

    draw_args = (
        draw_box_args("#b13c2f", markers, stroke=7)
        + draw_box_args("#a2761d", [note] if note else [], stroke=8)
        + draw_box_args("#146c5c", separators, stroke=5)
    )
    overview_cmd = ["convert", str(image), *draw_args, "-resize", "38%", str(overview)]
    body_cmd = [
        "convert",
        str(image),
        *draw_args,
        "-crop",
        crop_arg(body_box),
        "+repage",
        "-resize",
        "160%",
        "-normalize",
        str(body_crop),
    ]
    note_cmd = [
        "convert",
        str(image),
        *draw_args,
        "-crop",
        crop_arg(foot_box),
        "+repage",
        "-resize",
        "180%",
        "-normalize",
        str(note_crop),
    ]
    for cmd in (overview_cmd, body_cmd, note_cmd):
        result = run(cmd)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"ImageMagick failed: {' '.join(cmd)}")

    title = f"Beck fresh footnote visual pass | page {page} | {row.get('problem_type', '')}"
    result = run(
        [
            "montage",
            "-title",
            title,
            str(overview),
            str(body_crop),
            str(note_crop),
            "-tile",
            "1x3",
            "-geometry",
            "+14+14",
            "-background",
            "white",
            str(panel),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"montage failed for {panel}")

    prompt = prompt_dir / f"{case_id}.txt"
    prompt.write_text(assemble_prompt(row, panel, image, previous_page_image), encoding="utf-8")
    return Case(
        row=row,
        case_id=case_id,
        page_image=image,
        previous_page_image=previous_page_image,
        panel=panel,
        overview=overview,
        body_crop=body_crop,
        note_crop=note_crop,
        prompt=prompt,
    )


def compact_row(row: dict) -> dict:
    page = int(row.get("page") or 0)
    return {
        "id": row.get("id"),
        "page": page,
        "suggested_ref_xml_id": f"beck-fresh-ref-p{page:04d}-v{row.get('id', '').rsplit('-', 1)[-1]}",
        "suggested_note_xml_id": f"beck-fresh-fn-p{page:04d}-v{row.get('id', '').rsplit('-', 1)[-1]}",
        "problem_type": row.get("problem_type"),
        "status": row.get("status"),
        "raw_n": row.get("raw_n"),
        "qa": row.get("qa"),
        "note": row.get("note"),
        "marker_candidates": row.get("marker_candidates"),
        "current_tei": row.get("current_tei"),
    }


def lines_near_evidence(row: dict) -> list[dict]:
    context = row.get("page_context") or {}
    wanted = set()
    for candidate in row.get("marker_candidates") or []:
        try:
            line = int(candidate.get("line") or 0)
        except ValueError:
            line = 0
        wanted.update(range(max(1, line - 1), line + 2))
    note_line = (row.get("note") or {}).get("first_line") or (row.get("qa") or {}).get("note_first_line")
    try:
        line = int(note_line or 0)
    except ValueError:
        line = 0
    if line:
        wanted.update(range(max(1, line - 1), line + 4))
    return [line for line in context.get("lines") or [] if int(line.get("index") or 0) in wanted]


def bottom_zone_lines(row: dict) -> list[dict]:
    context = row.get("page_context") or {}
    lines = context.get("lines") or []
    bottom_lines = [line for line in lines if line.get("bottom_zone")]
    if bottom_lines:
        return bottom_lines
    return lines[-10:]


def assemble_prompt(row: dict, panel: Path, page_image: Path, previous_page_image: Path | None) -> str:
    payload = compact_row(row)
    payload["hocr_lines_near_candidates_and_note"] = lines_near_evidence(row)
    payload["hocr_bottom_zone_lines"] = bottom_zone_lines(row)
    payload["hocr_separators"] = (row.get("page_context") or {}).get("separators") or []
    return "\n".join(
        [
            "You are resolving one Beck 2020 fresh-OCR footnote ambiguity from page-image evidence.",
            "",
            "Attached images:",
            f"- visual panel: {panel.as_posix()}",
            f"- full 300dpi page image: {page_image.as_posix()}",
            f"- previous page image, if attached: {previous_page_image.as_posix() if previous_page_image else 'none'}",
            "",
            "Use the image as authority. hOCR/OCR are only evidence. Do not use older Beck XML or earlier generated Beck output.",
            "The visual panel marks marker candidates in red, bottom-note boxes in gold, and hOCR separator rules in green.",
            "",
            "Use this page-order method before deciding:",
            "1. First look for a horizontal footnote rule or separator near the lower page.",
            "2. If a rule exists, treat text below it as the candidate footnote zone and read the note label(s) from the image.",
            "3. If no hOCR note block exists but the image clearly has bottom notes, use propose_note_block.",
            "4. For each visible note label n, search upward in the main text on the same page for the corresponding superscript/start marker.",
            "5. If the anchor is not above the note on this page and a previous page image is attached, check the previous page end for a cross-page anchor.",
            "6. Red hOCR boxes are only suggestions. If the true superscript is visible but absent from marker_candidates, use suggested_ref_xml_id and give marker_bbox from the image.",
            "",
            "Return only one JSON object. No markdown fence. Use this schema:",
            "{",
            '  "decision": "accept_link" | "reject_marker" | "propose_note_block" | "unresolved",',
            '  "page": 0,',
            '  "ref_xml_id": "",',
            '  "note_xml_id": "",',
            '  "n": "",',
            '  "marker_bbox": "",',
            '  "note_bbox": "",',
            '  "first_line": "",',
            '  "last_line": "",',
            '  "confidence": 0.0,',
            '  "evidence": ""',
            "}",
            "",
            "Decision rules:",
            "- Use accept_link only if the image clearly shows the inline marker and the bottom note label/body belong together.",
            "- For accept_link, if the marker is not in marker_candidates, use suggested_ref_xml_id and provide marker_bbox.",
            "- Use propose_note_block if the image clearly shows a bottom footnote block that hOCR did not detect as a note block.",
            "- For propose_note_block, use suggested_note_xml_id unless a note_xml_id already exists in the case evidence.",
            "- For propose_note_block, first_line and last_line must be numeric hOCR line indexes, not line text; otherwise leave them blank and include note_bbox.",
            "- If propose_note_block also clearly corresponds to the selected marker, include ref_xml_id, marker_bbox, note_xml_id, and n so the block can be linked after rebuild.",
            "- A Tesseract OCR token like ! or | may be a visual footnote number 1 if the image supports it.",
            "- Use reject_marker for a red candidate that is only punctuation/quotation and has no footnote function.",
            "- Use unresolved if the image does not settle the link.",
            "- Choose ref_xml_id from marker_candidates when possible; otherwise use suggested_ref_xml_id for a visually clear superscript anchor.",
            "- Choose note_xml_id from the note block when present; otherwise use suggested_note_xml_id for a visually clear new note block.",
            "",
            "Case evidence JSON:",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def choose_rows(payload: dict, pages: set[int] | None, problem_types: set[str], limit: int | None) -> list[dict]:
    rows = []
    for row in payload.get("rows") or []:
        try:
            page = int(row.get("page") or 0)
        except ValueError:
            continue
        if pages is not None and page not in pages:
            continue
        if row.get("problem_type") not in problem_types:
            continue
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
    return rows


def strip_json_response(text: str) -> dict:
    text = text.strip()
    if "```" in text:
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def codex_visual_case(case: Case, model: str, timeout: int, response_dir: Path, resume: bool) -> dict:
    response_json_path = response_dir / f"{case.case_id}.json"
    if resume and response_json_path.exists():
        try:
            previous = json.loads(response_json_path.read_text(encoding="utf-8"))
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
        str(case.page_image),
    ]
    if case.previous_page_image is not None:
        cmd.extend(["-i", str(case.previous_page_image)])
    cmd.extend(["--", case.prompt.read_text(encoding="utf-8")])
    started = time.time()
    try:
        result = run(cmd, timeout=timeout)
        elapsed = round(time.time() - started, 1)
        response_text = response_text_path.read_text(encoding="utf-8", errors="replace")
        if result.returncode != 0:
            return {
                "case_id": case.case_id,
                "status": "error",
                "elapsed": elapsed,
                "error": (result.stderr or result.stdout)[-2000:],
                "raw_response": response_text,
            }
        proposal = strip_json_response(response_text or result.stdout)
        return {"case_id": case.case_id, "status": "success", "elapsed": elapsed, "proposal": proposal}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"case_id": case.case_id, "status": "error", "error": str(exc)}
    finally:
        try:
            os.unlink(response_text_path)
        except OSError:
            pass


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def proposal_key(row: dict, fields: list[str]) -> tuple[str, ...]:
    return tuple(str(row.get(field, "")) for field in fields)


def apply_proposals(
    results: list[dict],
    accepted_path: Path,
    accepted_blocks_path: Path,
    rejected_path: Path,
    min_confidence: float,
) -> dict:
    accepted = read_csv(accepted_path)
    accepted_blocks = read_csv(accepted_blocks_path)
    rejected = read_csv(rejected_path)
    accepted_seen = {proposal_key(row, ["page", "ref_xml_id", "note_xml_id"]) for row in accepted}
    accepted_block_seen = {proposal_key(row, ["page", "note_xml_id"]) for row in accepted_blocks}
    rejected_seen = {proposal_key(row, ["page", "ref_xml_id", "reason"]) for row in rejected}
    accepted_added = 0
    accepted_blocks_added = 0
    rejected_added = 0
    for result in results:
        proposal = result.get("proposal") or {}
        try:
            confidence = float(proposal.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0
        decision = proposal.get("decision")
        if decision in {"accept_link", "propose_note_block"} and confidence >= min_confidence:
            if decision == "propose_note_block":
                block_row = {
                    "page": str(proposal.get("page") or ""),
                    "note_xml_id": str(proposal.get("note_xml_id") or ""),
                    "n": str(proposal.get("n") or ""),
                    "note_bbox": str(proposal.get("note_bbox") or ""),
                    "first_line": str(proposal.get("first_line") or ""),
                    "last_line": str(proposal.get("last_line") or ""),
                    "confidence": str(confidence),
                    "method": "model-visual-pass",
                    "reviewer": "codex-visual-footnote-pass",
                }
                key = proposal_key(block_row, ["page", "note_xml_id"])
                has_lines = bool(block_row["first_line"] and block_row["last_line"])
                if (
                    all(block_row[field] for field in ("page", "note_xml_id", "n"))
                    and (has_lines or block_row["note_bbox"])
                    and key not in accepted_block_seen
                ):
                    accepted_blocks.append(block_row)
                    accepted_block_seen.add(key)
                    accepted_blocks_added += 1
            if decision == "propose_note_block" and not proposal.get("ref_xml_id"):
                continue
            row = {
                "page": str(proposal.get("page") or ""),
                "ref_xml_id": str(proposal.get("ref_xml_id") or ""),
                "note_xml_id": str(proposal.get("note_xml_id") or ""),
                "n": str(proposal.get("n") or ""),
                "marker_bbox": str(proposal.get("marker_bbox") or ""),
                "note_bbox": str(proposal.get("note_bbox") or ""),
                "confidence": str(confidence),
                "method": "model-visual-pass",
                "reviewer": "codex-visual-footnote-pass",
            }
            key = proposal_key(row, ["page", "ref_xml_id", "note_xml_id"])
            if all(row[field] for field in ("page", "ref_xml_id", "note_xml_id", "n")) and key not in accepted_seen:
                accepted.append(row)
                accepted_seen.add(key)
                accepted_added += 1
        elif decision == "reject_marker" and confidence >= min_confidence:
            row = {
                "page": str(proposal.get("page") or ""),
                "ref_xml_id": str(proposal.get("ref_xml_id") or ""),
                "note_xml_id": str(proposal.get("note_xml_id") or ""),
                "n": str(proposal.get("n") or ""),
                "marker_bbox": str(proposal.get("marker_bbox") or ""),
                "note_bbox": str(proposal.get("note_bbox") or ""),
                "reason": "model-visual-reject",
                "method": "model-visual-pass",
                "reviewer": "codex-visual-footnote-pass",
            }
            key = proposal_key(row, ["page", "ref_xml_id", "reason"])
            if row["page"] and row["ref_xml_id"] and key not in rejected_seen:
                rejected.append(row)
                rejected_seen.add(key)
                rejected_added += 1
    if accepted_added:
        write_csv(accepted_path, ACCEPTED_FIELDS, accepted)
    if accepted_blocks_added:
        write_csv(accepted_blocks_path, ACCEPTED_BLOCK_FIELDS, accepted_blocks)
    if rejected_added:
        write_csv(rejected_path, REJECTED_FIELDS, rejected)
    return {
        "accepted_added": accepted_added,
        "accepted_blocks_added": accepted_blocks_added,
        "rejected_added": rejected_added,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=DEFAULT_QUEUE)
    parser.add_argument("--ocr-dir", default=DEFAULT_OCR_DIR)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--pages", default="")
    parser.add_argument("--problem-types", default=",".join(DEFAULT_PROBLEM_TYPES))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--run-codex", action="store_true")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--apply-high-confidence", action="store_true")
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--accepted", default=DEFAULT_ACCEPTED)
    parser.add_argument("--accepted-blocks", default=DEFAULT_ACCEPTED_BLOCKS)
    parser.add_argument("--rejected", default=DEFAULT_REJECTED)
    args = parser.parse_args()

    require_command("identify")
    require_command("convert")
    require_command("montage")
    if args.run_codex:
        require_command("codex")

    queue_path = Path(args.queue)
    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    pages = set(parse_pages(args.pages)) if args.pages else None
    problem_types = {part.strip() for part in args.problem_types.split(",") if part.strip()}
    rows = choose_rows(payload, pages, problem_types, args.limit)
    if not rows:
        raise SystemExit("No matching footnote rows")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases: list[Case] = []
    for row in rows:
        case = write_visuals(row, Path(args.ocr_dir), out_dir)
        cases.append(case)
        print(f"panel {case.case_id}: {case.panel}")

    case_manifest = [
        {
            "case_id": case.case_id,
            "page": case.row.get("page"),
            "problem_type": case.row.get("problem_type"),
            "panel": case.panel.as_posix(),
            "prompt": case.prompt.as_posix(),
        }
        for case in cases
    ]
    (out_dir / "cases.json").write_text(json.dumps(case_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    results: list[dict] = []
    if args.run_codex:
        response_dir = out_dir / "responses"
        response_dir.mkdir(parents=True, exist_ok=True)
        max_parallel = max(1, args.max_parallel)
        if max_parallel == 1:
            for case in cases:
                result = codex_visual_case(case, args.model, args.timeout, response_dir, args.resume)
                results.append(result)
                response_path = response_dir / f"{case.case_id}.json"
                response_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                suffix = " resumed" if result.get("resumed") else ""
                print(f"codex {case.case_id}: {result.get('status')}{suffix}", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=max_parallel) as pool:
                futures = {
                    pool.submit(codex_visual_case, case, args.model, args.timeout, response_dir, args.resume): case
                    for case in cases
                }
                for future in as_completed(futures):
                    case = futures[future]
                    result = future.result()
                    results.append(result)
                    response_path = response_dir / f"{case.case_id}.json"
                    response_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    suffix = " resumed" if result.get("resumed") else ""
                    print(f"codex {case.case_id}: {result.get('status')}{suffix}", flush=True)
        with (out_dir / "proposals.jsonl").open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        if args.apply_high_confidence:
            applied = apply_proposals(
                results,
                Path(args.accepted),
                Path(args.accepted_blocks),
                Path(args.rejected),
                args.min_confidence,
            )
            print(
                "applied proposals: "
                f"{applied['accepted_added']} accepted links, "
                f"{applied['accepted_blocks_added']} accepted blocks, "
                f"{applied['rejected_added']} rejected"
            )

    summary = [
        "# Beck Fresh Footnote Visual Pass",
        "",
        f"- Cases: {len(cases)}",
        f"- Model run: {str(args.run_codex).lower()}",
        f"- Resume: {str(args.resume).lower()}",
        f"- Max parallel: {args.max_parallel}",
        f"- Output: `{out_dir.as_posix()}`",
    ]
    if results:
        summary.append(f"- Successful proposals: {sum(1 for result in results if result.get('status') == 'success')}")
    (out_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return 0 if not results or all(result.get("status") == "success" for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
