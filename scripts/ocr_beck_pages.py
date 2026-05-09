#!/usr/bin/env python3
"""OCR and audit Beck page images for sidecar text cleanup."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


KNOWN_CORRECTIONS = {
    "opOoKVOia": ("ὀρθόπνοια", "grc", "mixed Latin/Greek OCR confusables; line glosses as orthopnea"),
}
ACCEPTED_STATUSES = {"accepted", "approved", "auto", "auto-accepted"}
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
GREEKISH_LATIN_RE = re.compile(
    r"(?:opOoKVOia|KSpCtTlOV|Oeppog|6\(3oX|8r/23|doOpa|Suojtvoia|pTyv|aurri)"
)


@dataclass
class SourceToken:
    source_id: str
    text: str
    bbox: tuple[int, int, int, int] | None
    line_id: str
    page: int
    index: int


@dataclass
class SourceLine:
    source_id: str
    page: int
    bbox: tuple[int, int, int, int] | None
    tokens: list[SourceToken] = field(default_factory=list)

    @property
    def text(self) -> str:
        return normalize_ws(" ".join(token.text for token in self.tokens))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_token(text: str) -> str:
    return re.sub(r"\W+", "", text.casefold())


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


def bbox_center(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = bbox
    return (left + right) // 2, (top + bottom) // 2


def parse_pages(value: str, available: list[int]) -> list[int]:
    if not value:
        return available
    pages: set[int] = set()
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(chunk))
    available_set = set(available)
    return [page for page in sorted(pages) if page in available_set]


def read_source(source: Path) -> tuple[dict[int, list[SourceLine]], dict[int, list[SourceToken]]]:
    root = ET.parse(source).getroot()
    page = 0
    current_line: SourceLine | None = None
    lines_by_page: defaultdict[int, list[SourceLine]] = defaultdict(list)
    tokens_by_page: defaultdict[int, list[SourceToken]] = defaultdict(list)

    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            page = int(element.get("seq") or page or 0)
            current_line = None
        elif tag == "lb":
            current_line = SourceLine(
                source_id=element.get("id") or "",
                page=page,
                bbox=bbox_parts(element.get("bbox")),
            )
            lines_by_page[page].append(current_line)
        elif tag == "tok" and page:
            text = normalize_ws("".join(element.itertext()))
            if not text:
                continue
            if current_line is None:
                current_line = SourceLine(source_id=f"implicit-{page}-{len(lines_by_page[page]) + 1}", page=page, bbox=None)
                lines_by_page[page].append(current_line)
            token = SourceToken(
                source_id=element.get("id") or "",
                text=text,
                bbox=bbox_parts(element.get("bbox")),
                line_id=current_line.source_id,
                page=page,
                index=len(tokens_by_page[page]),
            )
            current_line.tokens.append(token)
            tokens_by_page[page].append(token)
    return dict(lines_by_page), dict(tokens_by_page)


def run_tesseract(image: Path, ocr_dir: Path, page: int, force: bool) -> dict[str, Path]:
    ocr_dir.mkdir(parents=True, exist_ok=True)
    base = ocr_dir / f"beck-{page:04d}"
    outputs = {
        "hocr": base.with_suffix(".hocr"),
        "tsv": base.with_suffix(".tsv"),
        "txt": base.with_suffix(".txt"),
    }
    if not force and all(path.exists() for path in outputs.values()):
        return outputs
    cmd = ["tesseract", str(image), str(base), "-l", "eng+grc", "--psm", "6", "hocr", "tsv", "txt"]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"tesseract failed for {image}")
    return outputs


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if row.get("text")]


def nearest_ocr_word(token: SourceToken, words: list[dict[str, str]]) -> dict[str, str] | None:
    if token.bbox is None:
        return None
    tx, ty = bbox_center(token.bbox)
    best: tuple[int, dict[str, str]] | None = None
    for word in words:
        try:
            left = int(float(word.get("left") or 0))
            top = int(float(word.get("top") or 0))
            width = int(float(word.get("width") or 0))
            height = int(float(word.get("height") or 0))
        except ValueError:
            continue
        wx = left + width // 2
        wy = top + height // 2
        distance = abs(tx - wx) + abs(ty - wy)
        if best is None or distance < best[0]:
            best = (distance, word)
    if best is None or best[0] > 90:
        return None
    return best[1]


def has_lower_body_text(line: SourceLine, page_lines: list[SourceLine]) -> bool:
    if line.bbox is None:
        return False
    _, _top, _right, bottom = line.bbox
    for other in page_lines:
        if other.bbox is None or other is line:
            continue
        if other.bbox[1] > bottom + 45 and other.text:
            return True
    return False


def classify_line(line: SourceLine, page_lines: list[SourceLine]) -> tuple[str, str, str]:
    if line.bbox is None:
        return "body", "", ""
    left, top, right, _bottom = line.bbox
    text = line.text
    if top > 225 or not has_lower_body_text(line, page_lines):
        return "body", "", ""
    if re.fullmatch(r"(?:[ivxlcdmIVXLCDM]+|\d{1,4})", text):
        place = "top-outer" if left < 300 or right > 1200 else "top"
        return "pageNum", place, "top-band page number"
    if len(text) <= 80 and not re.search(r"[=;:]", text):
        return "header", "top", "top-band running header"
    return "body", "", ""


def token_suspect(token: SourceToken, word: dict[str, str] | None) -> tuple[str, str]:
    if token.text in KNOWN_CORRECTIONS:
        return "mixed-script-confusable", "known high-confidence Greek correction"
    if GREEKISH_LATIN_RE.search(token.text) and not GREEK_RE.search(token.text):
        return "mixed-script-confusable", "Latin glyphs match known Greek OCR-confusable pattern"
    if word:
        ocr_text = word.get("text") or ""
        try:
            conf = float(word.get("conf") or 100)
        except ValueError:
            conf = 100
        if conf < 60 and normalize_token(ocr_text) != normalize_token(token.text):
            return "low-confidence-ocr-disagreement", f"tesseract conf={conf:g} text={ocr_text}"
    return "", ""


def crop_line(image: Path, line: SourceLine, crops_dir: Path) -> str:
    if line.bbox is None:
        return ""
    crops_dir.mkdir(parents=True, exist_ok=True)
    left, top, right, bottom = line.bbox
    margin = 18
    crop_left = max(0, left - margin)
    crop_top = max(0, top - margin)
    width = max(1, right - left + margin * 2)
    height = max(1, bottom - top + margin * 2)
    crop_path = crops_dir / f"page-{line.page:04d}-{line.source_id}.png"
    cmd = ["convert", str(image), "-crop", f"{width}x{height}+{crop_left}+{crop_top}", "+repage", str(crop_path)]
    subprocess.run(cmd, check=False, capture_output=True, text=True)
    return str(crop_path) if crop_path.exists() else ""


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def sidecar_dir_for(outdir: Path) -> Path:
    if outdir.name == "beck_text_cleaning":
        return outdir
    if outdir.parent.name == "beck_text_cleaning":
        return outdir.parent
    return outdir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", default="", help="Comma-separated pages or ranges; default is all pages")
    parser.add_argument("--source", required=True, help="Input Beck OCR/XML source")
    parser.add_argument("--images", required=True, help="Directory containing beck-N.jpg page images")
    parser.add_argument("--outdir", required=True, help="Audit output directory")
    parser.add_argument("--ocrdir", default="ocr/beck2020", help="Ignored directory for hOCR/TSV/text outputs")
    parser.add_argument("--force", action="store_true", help="Re-run OCR even when page outputs already exist")
    args = parser.parse_args()

    source = Path(args.source)
    images = Path(args.images)
    outdir = Path(args.outdir)
    ocr_dir = Path(args.ocrdir)
    outdir.mkdir(parents=True, exist_ok=True)

    lines_by_page, tokens_by_page = read_source(source)
    pages = parse_pages(args.pages, sorted(lines_by_page))
    if not pages:
        raise SystemExit("No source pages selected")

    line_role_rows: list[dict[str, str]] = []
    token_audit_rows: list[dict[str, str]] = []
    correction_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    packet_rows: list[dict[str, object]] = []
    crops_dir = outdir / "review_crops"

    for page in pages:
        image = images / f"beck-{page}.jpg"
        if not image.exists():
            raise SystemExit(f"Missing Beck page image: {image}")
        outputs = run_tesseract(image, ocr_dir, page, args.force)
        words = read_tsv(outputs["tsv"])

        for line in lines_by_page.get(page, []):
            role, place, evidence = classify_line(line, lines_by_page.get(page, []))
            if role != "body":
                line_role_rows.append(
                    {
                        "source_line_id": line.source_id,
                        "page": str(page),
                        "role": role,
                        "place": place,
                        "text": line.text,
                        "status": "auto-accepted",
                        "confidence": "0.99",
                        "evidence": evidence,
                    }
                )

        for token in tokens_by_page.get(page, []):
            word = nearest_ocr_word(token, words)
            category, evidence = token_suspect(token, word)
            correction = KNOWN_CORRECTIONS.get(token.text)
            status = ""
            corrected_text = ""
            xml_lang = ""
            if correction:
                corrected_text, xml_lang, correction_evidence = correction
                status = "auto-accepted"
                evidence = correction_evidence
                correction_rows.append(
                    {
                        "source_token_id": token.source_id,
                        "page": str(page),
                        "original_text": token.text,
                        "corrected_text": corrected_text,
                        "xml_lang": xml_lang,
                        "status": status,
                        "confidence": "0.99",
                        "evidence": evidence,
                    }
                )
            elif category:
                status = "needs-review"

            token_audit_rows.append(
                {
                    "source_token_id": token.source_id,
                    "source_line_id": token.line_id,
                    "page": str(page),
                    "source_text": token.text,
                    "ocr_text": word.get("text", "") if word else "",
                    "ocr_conf": word.get("conf", "") if word else "",
                    "suspect_category": category,
                    "status": status or "clear",
                    "corrected_text": corrected_text,
                    "evidence": evidence,
                }
            )

            if category and status == "needs-review":
                line = next((item for item in lines_by_page.get(page, []) if item.source_id == token.line_id), None)
                crop_path = crop_line(image, line, crops_dir) if line else ""
                row = {
                    "source_token_id": token.source_id,
                    "source_line_id": token.line_id,
                    "page": str(page),
                    "action": "review",
                    "current_xml_text": token.text,
                    "ocr_candidate": word.get("text", "") if word else "",
                    "ocr_conf": word.get("conf", "") if word else "",
                    "suspect_category": category,
                    "evidence_note": evidence,
                    "image_crop": crop_path,
                    "status": "needs-review",
                }
                review_rows.append(row)
                packet_rows.append(
                    {
                        **row,
                        "neighboring_line": line.text if line else "",
                        "schema": {
                            "source_id": token.source_id,
                            "page": page,
                            "action": "accept|correct|omit|needs-manual-review",
                            "corrected_text": "",
                            "confidence": 0.0,
                            "evidence_note": "",
                        },
                    }
                )

    sidecar_dir = sidecar_dir_for(outdir)
    line_fields = ["source_line_id", "page", "role", "place", "text", "status", "confidence", "evidence"]
    correction_fields = [
        "source_token_id",
        "page",
        "original_text",
        "corrected_text",
        "xml_lang",
        "status",
        "confidence",
        "evidence",
    ]
    token_fields = [
        "source_token_id",
        "source_line_id",
        "page",
        "source_text",
        "ocr_text",
        "ocr_conf",
        "suspect_category",
        "status",
        "corrected_text",
        "evidence",
    ]
    review_fields = [
        "source_token_id",
        "source_line_id",
        "page",
        "action",
        "current_xml_text",
        "ocr_candidate",
        "ocr_conf",
        "suspect_category",
        "evidence_note",
        "image_crop",
        "status",
    ]

    write_csv(outdir / "line_roles.csv", line_fields, line_role_rows)
    write_csv(outdir / "token_corrections.csv", correction_fields, correction_rows)
    write_csv(outdir / "token_audit.csv", token_fields, token_audit_rows)
    write_csv(outdir / "review_queue.csv", review_fields, review_rows)
    write_jsonl(outdir / "llm_review_packets.jsonl", packet_rows)
    if sidecar_dir != outdir:
        write_csv(sidecar_dir / "line_roles.csv", line_fields, line_role_rows)
        write_csv(sidecar_dir / "token_corrections.csv", correction_fields, correction_rows)
        write_csv(sidecar_dir / "token_audit.csv", token_fields, token_audit_rows)
        write_csv(sidecar_dir / "review_queue.csv", review_fields, review_rows)
        write_jsonl(sidecar_dir / "llm_review_packets.jsonl", packet_rows)

    summary = [
        "# Beck Text Cleaning OCR Audit",
        "",
        f"- Pages scanned: {len(pages)}",
        f"- Page-furniture lines accepted: {len(line_role_rows)}",
        f"- Token corrections accepted: {len(correction_rows)}",
        f"- Manual review rows: {len(review_rows)}",
        f"- hOCR/TSV/text directory: `{ocr_dir}`",
    ]
    (outdir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(f"OCR-scanned pages: {len(pages)}")
    print(f"Wrote {outdir / 'token_audit.csv'}")
    print(f"Wrote {sidecar_dir / 'line_roles.csv'}")
    print(f"Wrote {sidecar_dir / 'token_corrections.csv'}")
    print(f"Review queue rows: {len(review_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
