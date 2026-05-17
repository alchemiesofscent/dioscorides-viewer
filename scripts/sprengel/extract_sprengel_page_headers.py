#!/usr/bin/env python3
"""Extract Sprengel running headers from page-image top bands."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


ARCHIVE_ID = "b23982500_0001"
FIELDS = [
    "tei_facs",
    "book_page",
    "header_text",
    "page_num_text",
    "source",
    "confidence",
    "needs_review",
    "notes",
]
AUDIT_FIELDS = FIELDS + ["pdf_page", "remote_image", "raw_ocr"]
GREEK_BOOK_NUMERALS = {"1": "Α", "2": "Β", "3": "Γ", "4": "Δ", "5": "Ε"}
ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
TOKEN_RE = re.compile(r"[0-9A-Za-zIVXLCDM]+|[Α-Ωα-ωϐ-ϿΆ-ώ]+", re.IGNORECASE)


@dataclass
class OcrResult:
    text: str = ""
    confidence: float = 0.0


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=True)


def scan_number(page: dict, fallback: int) -> int:
    value = page.get("pdf_page")
    if isinstance(value, int):
        return value
    match = re.search(r"page-(\d{4})\.", page.get("tei_facs") or "")
    return int(match.group(1)) if match else fallback


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def clean_ocr_line(text: str) -> str:
    text = text.replace("|", " ")
    text = re.sub(r"[©@_=~]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .·,:;")


def text_quality(text: str) -> bool:
    letters = re.findall(r"[A-Za-zΑ-Ωα-ωϐ-ϿΆ-ώ]", text)
    return len(letters) >= 8


def matching_zip_entry(zip_path: Path, archive_id: str, number: int) -> str | None:
    wanted = f"{archive_id}_{number:04d}.jp2"
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith(wanted):
                return name
    return None


def extract_from_zip(zip_path: Path, entry: str, output_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        output_path.write_bytes(zf.read(entry))


def fetch_image(url: str, output_path: Path) -> None:
    with urllib.request.urlopen(url, timeout=45) as response:
        output_path.write_bytes(response.read())


def identify_size(path: Path) -> tuple[int, int]:
    result = run(["identify", "-format", "%w %h", str(path)])
    width, height = result.stdout.strip().split()
    return int(width), int(height)


def crop_top_band(image_path: Path, output_path: Path, crop_percent: float) -> None:
    width, height = identify_size(image_path)
    crop_height = max(140, min(300, int(height * crop_percent)))
    run(
        [
            "convert",
            str(image_path),
            "-crop",
            f"{width}x{crop_height}+0+0",
            "-colorspace",
            "Gray",
            "-resize",
            f"{width * 2}x{crop_height * 2}",
            str(output_path),
        ]
    )


def ocr_image(image_path: Path, languages: str) -> OcrResult:
    try:
        result = run(["tesseract", str(image_path), "stdout", "-l", languages, "--psm", "6", "tsv"])
    except subprocess.CalledProcessError:
        return OcrResult()

    rows = list(csv.DictReader(result.stdout.splitlines(), delimiter="\t"))
    line_words: dict[tuple[str, str, str], list[str]] = {}
    confidences: list[float] = []
    for row in rows:
        word = (row.get("text") or "").strip()
        if not word:
            continue
        key = (row.get("block_num") or "", row.get("par_num") or "", row.get("line_num") or "")
        line_words.setdefault(key, []).append(word)
        try:
            confidence = float(row.get("conf") or "-1")
        except ValueError:
            confidence = -1
        if confidence >= 0:
            confidences.append(confidence)
    lines = [clean_ocr_line(" ".join(words)) for _key, words in sorted(line_words.items())]
    lines = [line for line in lines if line]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrResult(text="\n".join(lines), confidence=confidence)


def likely_page_num(token: str, book_page: str) -> bool:
    normalized = token.strip(" .,:;[]()")
    if not normalized or not book_page:
        return False
    if book_page.isdigit():
        normalized = re.sub(r"^[OoQq](?=\d)", "9", normalized)
    if normalized == book_page:
        return True
    if book_page.isdigit() and normalized.isdigit():
        return normalized[-1:] == book_page[-1:] and len(normalized) == len(book_page)
    return normalized.upper() == book_page.upper()


def split_header(ocr: OcrResult, book_page: str, threshold: float) -> tuple[str, str, str, bool, str]:
    lines = [clean_ocr_line(line) for line in ocr.text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return "", "", "ocr_blank", True, "OCR returned no text"

    line = lines[0]
    tokens = TOKEN_RE.findall(line)
    page_num = ""
    if tokens and likely_page_num(tokens[0], book_page):
        page_num = book_page or tokens[0]
        line = line.replace(tokens[0], "", 1).strip()
    tokens = TOKEN_RE.findall(line)
    if tokens and likely_page_num(tokens[-1], book_page):
        page_num = book_page or tokens[-1]
        line = re.sub(re.escape(tokens[-1]) + r"\W*$", "", line).strip()
    header = clean_ocr_line(line)
    usable = ocr.confidence >= threshold and text_quality(header)
    if usable:
        return header, page_num or book_page, "ocr", False, ""
    note = f"OCR below threshold or implausible: conf={ocr.confidence:.1f}; raw={lines[0]}"
    return "", "", "ocr_low_confidence", True, note


def metadata_header(page: dict) -> str:
    book = str(page.get("book") or "")
    book_page = str(page.get("book_page") or "")
    if not book_page or not book:
        return ""
    if book and book_page.isdigit():
        if int(book_page) % 2 == 0:
            return "ΠΕΔΑΝΙΟΥ ΔΙΟΣΚΟΡΙΔΟΥ ΑΝΑΖΑΡΒΕΩΣ"
        numeral = GREEK_BOOK_NUMERALS.get(book, book)
        return f"ΠΕΡΙ ΥΛΗΣ ΙΑΤΡΙΚΗΣ ΒΙΒΛΙΟΝ {numeral}."
    return (
        page.get("front_subsection_title")
        or page.get("front_section_title")
        or page.get("section")
        or ""
    )


def fallback_row(page: dict, source: str, note: str) -> dict[str, str]:
    return {
        "tei_facs": page.get("tei_facs") or "",
        "book_page": str(page.get("book_page") or ""),
        "header_text": metadata_header(page),
        "page_num_text": str(page.get("book_page") or ""),
        "source": "metadata_fallback",
        "confidence": "0.00",
        "needs_review": "true",
        "notes": note or source,
    }


def select_pages(pages: list[dict], selector: str) -> set[int] | None:
    if not selector:
        return None
    selected: set[int] = set()
    wanted = {item.strip() for item in selector.split(",") if item.strip()}
    for index, page in enumerate(pages, start=1):
        candidates = {
            str(index),
            str(page.get("pdf_page") or ""),
            str(page.get("book_page") or ""),
            page.get("tei_facs") or "",
            Path(page.get("tei_facs") or "").name,
        }
        if wanted & candidates:
            selected.add(index)
    return selected


def process_page(
    page: dict,
    index: int,
    args: argparse.Namespace,
    zip_entry_cache: dict[int, str | None],
    tempdir: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    number = scan_number(page, index)
    image_path = tempdir / f"sprengel-{number:04d}.img"
    image_source_note = ""

    if args.zip:
        entry = zip_entry_cache.setdefault(number, matching_zip_entry(args.zip, args.archive_id, number))
        if entry:
            extract_from_zip(args.zip, entry, image_path)
            image_source_note = f"zip:{entry}"
        elif args.fetch:
            fetch_image(page["remoteImage"], image_path)
            image_source_note = "iiif"
    elif args.fetch:
        fetch_image(page["remoteImage"], image_path)
        image_source_note = "iiif"

    if not image_path.exists():
        row = fallback_row(page, "image_missing", "No matching local image; metadata fallback")
        audit = dict(row)
        audit.update({"pdf_page": str(number), "remote_image": page.get("remoteImage") or "", "raw_ocr": ""})
        return row, audit

    crop_path = tempdir / f"sprengel-{number:04d}-top.png"
    try:
        crop_top_band(image_path, crop_path, args.crop_percent)
        ocr = ocr_image(crop_path, args.languages)
    except (subprocess.CalledProcessError, ValueError) as exc:
        row = fallback_row(page, "ocr_error", f"{type(exc).__name__}: {exc}")
        audit = dict(row)
        audit.update({"pdf_page": str(number), "remote_image": page.get("remoteImage") or "", "raw_ocr": ""})
        return row, audit

    header, page_num, source, needs_review, note = split_header(
        ocr,
        str(page.get("book_page") or ""),
        args.confidence_threshold,
    )
    if not header and needs_review:
        row = fallback_row(page, source, note)
    else:
        expected_header = metadata_header(page)
        if source == "ocr" and expected_header:
            header = expected_header
            source = "ocr_normalized"
        row = {
            "tei_facs": page.get("tei_facs") or "",
            "book_page": str(page.get("book_page") or ""),
            "header_text": header,
            "page_num_text": page_num,
            "source": source,
            "confidence": f"{ocr.confidence:.2f}",
            "needs_review": bool_text(needs_review),
            "notes": image_source_note,
        }
    audit = dict(row)
    audit.update({"pdf_page": str(number), "remote_image": page.get("remoteImage") or "", "raw_ocr": ocr.text})
    return row, audit


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_summary(path: Path, rows: list[dict[str, str]]) -> None:
    counts: dict[str, int] = {}
    review = 0
    for row in rows:
        counts[row["source"]] = counts.get(row["source"], 0) + 1
        if row["needs_review"] == "true":
            review += 1
    lines = [
        "# Sprengel Page Header Audit",
        "",
        f"Rows: {len(rows)}",
        f"Needs review: {review}",
        "",
        "## Sources",
        "",
    ]
    for source, count in sorted(counts.items()):
        lines.append(f"- {source}: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("editions/sprengel1829/manifest.json"))
    parser.add_argument("--sidecar", type=Path, default=Path("editions/sprengel1829/page_headers.csv"))
    parser.add_argument("--audit-dir", type=Path, default=Path("output/sprengel_page_header_audit"))
    parser.add_argument("--archive-id", default=ARCHIVE_ID)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--fetch", action="store_true", help="Download missing page images from manifest IIIF URLs.")
    parser.add_argument("--pages", default="", help="Comma-separated selectors: row index, pdf_page, book_page, facs.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--languages", default="grc+eng")
    parser.add_argument("--crop-percent", type=float, default=0.085)
    parser.add_argument("--confidence-threshold", type=float, default=35.0)
    args = parser.parse_args()

    if args.zip and not args.zip.exists():
        raise SystemExit(f"Zip not found: {args.zip}")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    pages = list(manifest.get("pages", []))
    selected = select_pages(pages, args.pages)
    rows: list[dict[str, str]] = []
    audit_rows: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="sprengel-headers-") as tmp:
        tempdir = Path(tmp)
        zip_entry_cache: dict[int, str | None] = {}
        for index, page in enumerate(pages, start=1):
            if selected is not None and index not in selected:
                continue
            if args.limit and len(rows) >= args.limit:
                break
            row, audit = process_page(page, index, args, zip_entry_cache, tempdir)
            rows.append(row)
            audit_rows.append(audit)

    if selected is None and not args.limit:
        write_csv(args.sidecar, FIELDS, rows)
    write_csv(args.audit_dir / "header_ledger.csv", AUDIT_FIELDS, audit_rows)
    write_summary(args.audit_dir / "header_summary.md", rows)


if __name__ == "__main__":
    main()
