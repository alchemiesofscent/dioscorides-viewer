#!/usr/bin/env python3
"""Run the fresh-OCR Beck stream from the local PDF.

This experiment deliberately treats ``beck.xml`` only as a diagnostic baseline.
It re-renders selected PDF pages, runs Tesseract, writes raw OCR evidence, builds
a page-first TEI draft from hOCR coordinates, and emits QA summaries under an
ignored output directory. By default it runs the representative pilot page set;
use ``--all-pages`` to process the full local PDF.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

DEFAULT_PAGES = (
    "14,15,16,30,33,37,40,45,58,59,80,126,133,162,184,207,223,285,293,300,"
    "318,325,386,405,419,427,432"
)
DEFAULT_PDF = "beck.pdf"
DEFAULT_OUTDIR = "ocr/beck2020_fresh"
DEFAULT_OUTPUT_XML = "output/beck2020_fresh_epidoc.xml"
DEFAULT_MANIFEST = "editions/beck2020_fresh/manifest.json"
DEFAULT_PRIVATE_REGISTRY = "editions/beck2020_fresh/private_registry.json"
DEFAULT_REVIEW_DIR = "ocr/beck2020_fresh/review"
DEFAULT_ACCEPTED_FOOTNOTES = f"{DEFAULT_REVIEW_DIR}/accepted_footnote_links.csv"
DEFAULT_ACCEPTED_FOOTNOTE_BLOCKS = f"{DEFAULT_REVIEW_DIR}/accepted_footnote_blocks.csv"
DEFAULT_ACCEPTED_FOOTNOTE_TRANSCRIPTIONS = f"{DEFAULT_REVIEW_DIR}/accepted_footnote_transcriptions.csv"
DEFAULT_REJECTED_FOOTNOTES = f"{DEFAULT_REVIEW_DIR}/rejected_footnote_candidates.csv"
DEFAULT_EDITION_ID = "beck2020_fresh"
DEFAULT_EDITION_LABEL = "Beck 2020 fresh OCR (private local review)"
BASELINE_XML = "beck.xml"
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
WORDISH_RE = re.compile(r"\w", re.UNICODE)
SPACE_BEFORE_RE = re.compile(r"^[,.;:!?%)\]\u2019\u201d]$")
NO_SPACE_AFTER_RE = re.compile(r"[(\[\u2018\u201c]$")
FOOTNOTE_LABEL_RE = re.compile(r"^\s*(\d{1,3})\b")
FOOTNOTE_LABEL_TOKEN_RE = re.compile(r"^(\d{1,3})\b")
FOOTNOTE_OCR_ONE_TOKEN_RE = re.compile(r"^[!|]\.?,?$")
FOOTNOTE_MARKER_RE = re.compile(r"^(.+?)([\^*†‡'’\"”]+(?:\d{1,3})?|\d{1,3}[\^*†‡'’\"”]+)$")
FOOTNOTE_SIGNAL_RE = re.compile(r"[\^*†‡]|\d")
QUOTE_ONLY_MARKER_RE = re.compile(r"^[\"'‘’“”«»„‚]+$")
PAGE_NUMBER_TOKEN_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdmIVXLCDM]+|\[[ivxlcdmIVXLCDM\d-]+\])$")
PHRASE_CHECK_TRANSLATION = str.maketrans({"Α": "A"})
PAGE_58_EXPECTED = (
    "This dirt is a mixture",
    "A compound word from ἔλαιον",
)


@dataclass
class Word:
    text: str
    bbox: tuple[int, int, int, int] | None
    confidence: float | None
    page: int
    line_index: int
    word_index: int


@dataclass
class Line:
    bbox: tuple[int, int, int, int] | None
    page: int
    index: int
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return join_tokens([word.text for word in self.words])


@dataclass
class HocrPage:
    page: int
    bbox: tuple[int, int, int, int] | None
    lines: list[Line]
    separators: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class PageQa:
    page: int
    image: str
    hocr: str
    tsv: str
    txt: str
    width: int
    height: int
    word_count: int
    mean_confidence: float | None
    low_confidence_words: int
    greek_tokens: int
    baseline_similarity: float | None
    footnote_47: bool = False
    footnote_48: bool = False
    page58_expected: dict[str, bool] = field(default_factory=dict)


@dataclass
class FootnoteBlock:
    page: int
    ordinal: int
    raw_n: str
    lines: list[Line]
    xml_id: str = ""
    ref_id: str = ""
    marker: "MarkerCandidate | None" = None
    status: str = "unlinked"
    method: str = "none"
    evidence: str = ""
    accepted_transcription: str = ""

    @property
    def first_line(self) -> Line:
        return self.lines[0]

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        boxes = [line.bbox for line in self.lines if line.bbox is not None]
        if not boxes:
            return None
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    @property
    def text(self) -> str:
        if self.accepted_transcription:
            return self.accepted_transcription
        return normalize_ws(" ".join(line.text for line in self.lines))


@dataclass(frozen=True)
class MarkerCandidate:
    page: int
    line_index: int
    word_index: int
    word_xml_id: str
    ref_id: str
    base_text: str
    marker_text: str
    line_text: str
    bbox: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class AcceptedFootnoteLink:
    page: int
    ref_xml_id: str
    note_xml_id: str
    n: str
    marker_bbox: str = ""
    note_bbox: str = ""
    confidence: str = ""
    method: str = ""
    reviewer: str = ""


@dataclass(frozen=True)
class AcceptedFootnoteBlock:
    page: int
    note_xml_id: str
    n: str
    note_bbox: str = ""
    first_line: str = ""
    last_line: str = ""
    confidence: str = ""
    method: str = ""
    reviewer: str = ""


@dataclass(frozen=True)
class AcceptedFootnoteTranscription:
    page: int
    note_xml_id: str
    n: str
    transcription: str
    confidence: str = ""
    method: str = ""
    reviewer: str = ""
    evidence: str = ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_compare(text: str) -> str:
    text = text.casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_for_phrase_check(text: str) -> str:
    return normalize_ws(text.translate(PHRASE_CHECK_TRANSLATION))


def join_tokens(tokens: list[str]) -> str:
    text = ""
    for token in tokens:
        if not token:
            continue
        if not text:
            text = token
        elif SPACE_BEFORE_RE.match(token) or NO_SPACE_AFTER_RE.search(text[-1]):
            text += token
        else:
            text += " " + token
    return text


def parse_pages(value: str) -> list[int]:
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
    return sorted(pages)


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"Missing required command: {name}")


def preflight(langs: str) -> None:
    for command in ("pdfinfo", "pdftoppm", "identify", "tesseract"):
        require_command(command)
    result = run(["tesseract", "--list-langs"])
    if result.returncode != 0:
        raise SystemExit(result.stderr.strip() or "Could not list Tesseract languages")
    installed = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of available")
    }
    requested = {part for part in re.split(r"[+,\s]+", langs) if part}
    missing = sorted(requested - installed)
    if missing:
        raise SystemExit(
            f"Missing Tesseract language packs: {', '.join(missing)}. "
            f"Installed: {', '.join(sorted(installed))}"
        )


def pdf_page_count(pdf: Path) -> int:
    result = run(["pdfinfo", str(pdf)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"pdfinfo failed for {pdf}")
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"Could not determine page count for {pdf}")


def output_paths(outdir: Path, page: int) -> dict[str, Path]:
    stem = f"beck-{page:04d}"
    return {
        "image": outdir / "images" / f"{stem}.png",
        "hocr": outdir / "hocr" / f"{stem}.hocr",
        "tsv": outdir / "tsv" / f"{stem}.tsv",
        "txt": outdir / "txt" / f"{stem}.txt",
    }


def render_page(pdf: Path, image: Path, page: int, resolution: int, force: bool) -> None:
    if image.exists() and not force:
        return
    image.parent.mkdir(parents=True, exist_ok=True)
    prefix = image.with_suffix("")
    tmp_output = prefix.with_suffix(".png")
    if tmp_output.exists() and force:
        tmp_output.unlink()
    result = run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(resolution),
            "-png",
            "-singlefile",
            str(pdf),
            str(prefix),
        ]
    )
    if result.returncode != 0 or not image.exists():
        raise RuntimeError(result.stderr.strip() or f"pdftoppm failed for PDF page {page}")


def run_tesseract(image: Path, paths: dict[str, Path], langs: str, psm: int, force: bool) -> None:
    if not force and paths["hocr"].exists() and paths["tsv"].exists() and paths["txt"].exists():
        return
    for key in ("hocr", "tsv", "txt"):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = paths["hocr"].parents[1] / ".tmp_tesseract"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    base = tmp_dir / paths["hocr"].with_suffix("").name
    for suffix in (".hocr", ".tsv", ".txt"):
        candidate = base.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()
    result = run(
        [
            "tesseract",
            str(image),
            str(base),
            "-l",
            langs,
            "--psm",
            str(psm),
            "hocr",
            "tsv",
            "txt",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"tesseract failed for {image}")
    for key, suffix in (("hocr", ".hocr"), ("tsv", ".tsv"), ("txt", ".txt")):
        generated = base.with_suffix(suffix)
        if not generated.exists():
            raise RuntimeError(f"Tesseract did not write {generated}")
        shutil.move(str(generated), paths[key])


def image_size(image: Path) -> tuple[int, int]:
    result = run(["identify", "-format", "%w %h", str(image)])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"identify failed for {image}")
    width, height = result.stdout.strip().split()
    return int(width), int(height)


def class_tokens(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def title_bbox(title: str | None) -> tuple[int, int, int, int] | None:
    if not title:
        return None
    match = re.search(r"\bbbox\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)", title)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def title_confidence(title: str | None) -> float | None:
    if not title:
        return None
    match = re.search(r"\bx_wconf\s+(-?\d+(?:\.\d+)?)", title)
    if not match:
        return None
    value = float(match.group(1))
    return value if value >= 0 else None


def parse_hocr(path: Path, page: int) -> HocrPage:
    root = ET.parse(path).getroot()
    page_el: ET.Element | None = None
    for element in root.iter():
        if "ocr_page" in class_tokens(element):
            page_el = element
            break
    page_bbox = title_bbox(page_el.get("title") if page_el is not None else None)
    lines: list[Line] = []
    separators: list[tuple[int, int, int, int]] = []
    search_root = page_el if page_el is not None else root
    for element in search_root.iter():
        if "ocr_separator" in class_tokens(element):
            bbox = title_bbox(element.get("title"))
            if bbox:
                separators.append(bbox)
    for element in search_root.iter():
        if not ({"ocr_line", "ocr_textfloat"} & class_tokens(element)):
            continue
        line = Line(bbox=title_bbox(element.get("title")), page=page, index=len(lines) + 1)
        for word_el in element.iter():
            if "ocrx_word" not in class_tokens(word_el):
                continue
            text = normalize_ws("".join(word_el.itertext()))
            if not text:
                continue
            line.words.append(
                Word(
                    text=text,
                    bbox=title_bbox(word_el.get("title")),
                    confidence=title_confidence(word_el.get("title")),
                    page=page,
                    line_index=line.index,
                    word_index=len(line.words) + 1,
                )
            )
        if line.words:
            lines.append(line)
    return HocrPage(page=page, bbox=page_bbox, lines=lines, separators=separators)


def float_or_none(value: str | None) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except ValueError:
        return None
    return number if number >= 0 else None


def line_type(line: Line, page_height: int) -> tuple[str, str]:
    text = line.text
    bbox = line.bbox
    if bbox is None:
        return "body", ""
    left, top, right, bottom = bbox
    if top < page_height * 0.10 and len(text) <= 90:
        if re.fullmatch(r"[\divxlcdmIVXLCDM\[\]-]+", text):
            return "pageNum", "top"
        return "header", "top"
    if bottom > page_height * 0.82:
        match = FOOTNOTE_LABEL_RE.match(text)
        if match:
            return "note", "bottom"
        if len(text) <= 30 and (left < 350 or right > 1200):
            return "pageNum", "bottom"
    return "body", ""


def word_xml_id(word: Word) -> str:
    return f"beck-fresh-p{word.page:04d}-l{word.line_index:03d}-w{word.word_index:03d}"


def raw_note_label(line: Line, allow_ocr_one: bool = False) -> str:
    if not line.words:
        return ""
    first = line.words[0].text.strip()
    match = FOOTNOTE_LABEL_TOKEN_RE.match(first)
    if match:
        return match.group(1)
    if allow_ocr_one and FOOTNOTE_OCR_ONE_TOKEN_RE.fullmatch(first):
        return "1"
    return ""


def is_note_start_line(line: Line, page_height: int, allow_ocr_one: bool = False) -> bool:
    if line.bbox is None or line.bbox[1] < page_height * 0.72:
        return False
    return bool(raw_note_label(line, allow_ocr_one))


def page_width(page: HocrPage) -> int:
    if page.bbox:
        return max(0, page.bbox[2] - page.bbox[0])
    boxes = [line.bbox for line in page.lines if line.bbox is not None]
    if not boxes:
        return 0
    return max(box[2] for box in boxes) - min(box[0] for box in boxes)


def footnote_separator_start_index(page: HocrPage, page_height: int) -> int | None:
    width = page_width(page)
    min_rule_width = max(300, int(width * 0.25)) if width else 300
    for separator in sorted(page.separators, key=lambda bbox: bbox[1]):
        left, top, right, bottom = separator
        rule_width = right - left
        rule_height = bottom - top
        if top < page_height * 0.55 or bottom > page_height * 0.95:
            continue
        if rule_width < min_rule_width or rule_height > 20:
            continue
        for index, line in enumerate(page.lines):
            if line.bbox is None or line.bbox[1] <= bottom:
                continue
            if line.bbox[1] - bottom > page_height * 0.08:
                break
            if raw_note_label(line, allow_ocr_one=True):
                return index
            break
    return None


def footnote_blocks_for_page(page: HocrPage, page_height: int) -> list[FootnoteBlock]:
    start_index: int | None = None
    allow_ocr_one = False
    for index, line in enumerate(page.lines):
        if is_note_start_line(line, page_height):
            start_index = index
            break
    if start_index is None:
        start_index = footnote_separator_start_index(page, page_height)
        allow_ocr_one = start_index is not None
    if start_index is None:
        return []

    blocks: list[FootnoteBlock] = []
    current: FootnoteBlock | None = None
    for line in page.lines[start_index:]:
        if line.bbox is None:
            continue
        label = raw_note_label(line, allow_ocr_one)
        if label:
            current = FootnoteBlock(page=page.page, ordinal=len(blocks) + 1, raw_n=label, lines=[line])
            current.xml_id = f"beck-fresh-fn-p{page.page:04d}-{current.ordinal:03d}"
            blocks.append(current)
            continue
        if current is not None:
            current.lines.append(line)
    return blocks


def marker_from_word(word: Word) -> tuple[str, str] | None:
    text = word.text.strip()
    match = FOOTNOTE_MARKER_RE.match(text)
    if not match:
        return None
    base = match.group(1).strip()
    marker = match.group(2).strip()
    if not base or not marker:
        return None
    if base in {"I", "V", "X"} and marker.isdigit():
        return None
    return base, marker


def marker_candidates_for_page(page: HocrPage, footnote_blocks: list[FootnoteBlock]) -> list[MarkerCandidate]:
    first_note_line = min((block.first_line.index for block in footnote_blocks), default=10**9)
    candidates: list[MarkerCandidate] = []
    for line in page.lines:
        if line.index >= first_note_line:
            continue
        if line.bbox is None:
            continue
        for word in line.words:
            marker = marker_from_word(word)
            if marker is None:
                continue
            base, marker_text = marker
            ref_id = f"beck-fresh-ref-p{page.page:04d}-{len(candidates) + 1:03d}"
            candidates.append(
                MarkerCandidate(
                    page=page.page,
                    line_index=line.index,
                    word_index=word.word_index,
                    word_xml_id=word_xml_id(word),
                    ref_id=ref_id,
                    base_text=base,
                    marker_text=marker_text,
                    line_text=line.text,
                    bbox=word.bbox,
                )
            )
    return candidates


def is_high_confidence_marker(marker: MarkerCandidate) -> bool:
    marker_text = marker.marker_text.strip()
    if not marker_text or QUOTE_ONLY_MARKER_RE.fullmatch(marker_text):
        return False
    return bool(FOOTNOTE_SIGNAL_RE.search(marker_text))


def read_dict_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: value for key, value in row.items() if key is not None} for row in csv.DictReader(handle)]


def load_accepted_footnote_links(path: Path) -> list[AcceptedFootnoteLink]:
    links: list[AcceptedFootnoteLink] = []
    for row in read_dict_rows(path):
        page = row.get("page", "").strip()
        ref_xml_id = row.get("ref_xml_id", "").strip()
        note_xml_id = row.get("note_xml_id", "").strip()
        if not (page and ref_xml_id and note_xml_id):
            continue
        try:
            page_number = int(page)
        except ValueError:
            continue
        links.append(
            AcceptedFootnoteLink(
                page=page_number,
                ref_xml_id=ref_xml_id,
                note_xml_id=note_xml_id,
                n=row.get("n", "").strip(),
                marker_bbox=row.get("marker_bbox", "").strip(),
                note_bbox=row.get("note_bbox", "").strip(),
                confidence=row.get("confidence", "").strip(),
                method=row.get("method", "").strip(),
                reviewer=row.get("reviewer", "").strip(),
            )
        )
    return links


def load_accepted_footnote_blocks(path: Path) -> list[AcceptedFootnoteBlock]:
    blocks: list[AcceptedFootnoteBlock] = []
    for row in read_dict_rows(path):
        page = row.get("page", "").strip()
        note_xml_id = row.get("note_xml_id", "").strip()
        n = row.get("n", "").strip()
        if not (page and note_xml_id and n):
            continue
        try:
            page_number = int(page)
        except ValueError:
            continue
        blocks.append(
            AcceptedFootnoteBlock(
                page=page_number,
                note_xml_id=note_xml_id,
                n=n,
                note_bbox=row.get("note_bbox", "").strip(),
                first_line=row.get("first_line", "").strip(),
                last_line=row.get("last_line", "").strip(),
                confidence=row.get("confidence", "").strip(),
                method=row.get("method", "").strip(),
                reviewer=row.get("reviewer", "").strip(),
            )
        )
    return blocks


def load_accepted_footnote_transcriptions(path: Path) -> dict[str, AcceptedFootnoteTranscription]:
    transcriptions: dict[str, AcceptedFootnoteTranscription] = {}
    for row in read_dict_rows(path):
        page = row.get("page", "").strip()
        note_xml_id = row.get("note_xml_id", "").strip()
        transcription = row.get("transcription", "").strip()
        if not (page and note_xml_id and transcription):
            continue
        try:
            page_number = int(page)
        except ValueError:
            continue
        transcriptions[note_xml_id] = AcceptedFootnoteTranscription(
            page=page_number,
            note_xml_id=note_xml_id,
            n=row.get("n", "").strip(),
            transcription=transcription,
            confidence=row.get("confidence", "").strip(),
            method=row.get("method", "").strip(),
            reviewer=row.get("reviewer", "").strip(),
            evidence=row.get("evidence", "").strip(),
        )
    return transcriptions


def load_rejected_footnote_refs(path: Path) -> set[str]:
    rejected: set[str] = set()
    for row in read_dict_rows(path):
        ref_xml_id = row.get("ref_xml_id", "").strip()
        if ref_xml_id:
            rejected.add(ref_xml_id)
    return rejected


def parse_bbox_str(value: str) -> tuple[int, int, int, int] | None:
    parts = [part for part in value.strip().split() if part]
    if len(parts) != 4:
        return None
    try:
        left, top, right, bottom = (int(float(part)) for part in parts)
    except ValueError:
        return None
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def line_overlaps_bbox(line: Line, bbox: tuple[int, int, int, int]) -> bool:
    if line.bbox is None:
        return False
    left, top, right, bottom = line.bbox
    box_left, box_top, box_right, box_bottom = bbox
    horizontal_overlap = min(right, box_right) - max(left, box_left)
    vertical_overlap = min(bottom, box_bottom) - max(top, box_top)
    if horizontal_overlap <= 0 or vertical_overlap <= 0:
        return False
    line_height = bottom - top
    box_height = box_bottom - box_top
    required_vertical = max(4, min(line_height, box_height) * 0.5)
    return vertical_overlap >= required_vertical


def find_anchor_word_for_bbox(page: HocrPage, bbox: tuple[int, int, int, int]) -> Word | None:
    box_left, box_top, box_right, box_bottom = bbox
    box_center_y = (box_top + box_bottom) / 2
    overlapping_words: list[tuple[int, float, Word]] = []
    box_center_x = (box_left + box_right) / 2
    for line in page.lines:
        if line.bbox is None or not line.words:
            continue
        for word in line.words:
            if word.bbox is None:
                continue
            left, top, right, bottom = word.bbox
            horizontal_overlap = min(right, box_right) - max(left, box_left)
            vertical_overlap = min(bottom, box_bottom) - max(top, box_top)
            if horizontal_overlap <= 0 or vertical_overlap <= 0:
                continue
            area = horizontal_overlap * vertical_overlap
            word_center_x = (left + right) / 2
            word_center_y = (top + bottom) / 2
            distance = abs(word_center_x - box_center_x) + abs(word_center_y - box_center_y)
            overlapping_words.append((-area, distance, word))
    if overlapping_words:
        _area, _distance, word = min(overlapping_words, key=lambda item: (item[0], item[1]))
        return word

    line_scores: list[tuple[float, Line]] = []
    for line in page.lines:
        if line.bbox is None or not line.words:
            continue
        left, top, right, bottom = line.bbox
        overlap = min(bottom, box_bottom) - max(top, box_top)
        center_y = (top + bottom) / 2
        if overlap > 0:
            score = -overlap
        else:
            score = abs(center_y - box_center_y)
        line_scores.append((score, line))
    if not line_scores:
        return None
    _score, line = min(line_scores, key=lambda item: item[0])
    preceding = [word for word in line.words if word.bbox and word.bbox[2] <= box_right]
    if preceding:
        return max(preceding, key=lambda word: word.bbox[2] if word.bbox else -1)
    return min(
        line.words,
        key=lambda word: abs((((word.bbox[0] + word.bbox[2]) / 2) if word.bbox else 0) - box_left),
    )


def virtual_marker_from_accepted_link(page: HocrPage, accepted: AcceptedFootnoteLink) -> MarkerCandidate | None:
    bbox = parse_bbox_str(accepted.marker_bbox)
    if bbox is None:
        return None
    anchor_word = find_anchor_word_for_bbox(page, bbox)
    if anchor_word is None:
        return None
    marker_text = accepted.n or "?"
    return MarkerCandidate(
        page=page.page,
        line_index=anchor_word.line_index,
        word_index=anchor_word.word_index,
        word_xml_id=word_xml_id(anchor_word),
        ref_id=accepted.ref_xml_id,
        base_text=anchor_word.text,
        marker_text=marker_text,
        line_text=page.lines[anchor_word.line_index - 1].text if anchor_word.line_index - 1 < len(page.lines) else anchor_word.text,
        bbox=bbox,
    )


def accepted_blocks_for_page(page: HocrPage, accepted_blocks: list[AcceptedFootnoteBlock]) -> list[FootnoteBlock]:
    blocks: list[FootnoteBlock] = []
    for accepted in accepted_blocks:
        if accepted.page != page.page:
            continue
        selected_lines: list[Line] = []
        if accepted.note_bbox:
            bbox = parse_bbox_str(accepted.note_bbox)
            if bbox:
                selected_lines = [line for line in page.lines if line_overlaps_bbox(line, bbox)]
        try:
            first_line = int(accepted.first_line) if accepted.first_line else 0
            last_line = int(accepted.last_line) if accepted.last_line else first_line
        except ValueError:
            first_line = 0
            last_line = 0
        if not selected_lines and first_line and last_line:
            low, high = sorted((first_line, last_line))
            selected_lines = [line for line in page.lines if low <= line.index <= high]
        if not selected_lines:
            continue
        block = FootnoteBlock(
            page=page.page,
            ordinal=len(blocks) + 1,
            raw_n=accepted.n,
            lines=selected_lines,
            xml_id=accepted.note_xml_id,
            status="unlinked",
            method=f"accepted-block-sidecar:{accepted.method or 'model-visual-pass'}",
        )
        reviewer = f" reviewer={accepted.reviewer}" if accepted.reviewer else ""
        block.evidence = f"accepted sidecar note block {accepted.note_xml_id}{reviewer}"
        blocks.append(block)
    return blocks


def merge_accepted_and_detected_blocks(
    accepted_blocks: list[FootnoteBlock],
    detected_blocks: list[FootnoteBlock],
) -> list[FootnoteBlock]:
    merged = list(accepted_blocks)
    used_line_ids = {id(line) for block in merged for line in block.lines}
    used_xml_ids = {block.xml_id for block in merged if block.xml_id}
    for block in detected_blocks:
        if any(id(line) in used_line_ids for line in block.lines):
            continue
        if block.xml_id in used_xml_ids:
            block.ordinal = len(merged) + 1
            block.xml_id = f"beck-fresh-fn-p{block.page:04d}-{block.ordinal:03d}"
        merged.append(block)
        used_xml_ids.add(block.xml_id)
    merged.sort(key=lambda block: block.first_line.index)
    return merged


def link_footnotes(
    pages: list[HocrPage],
    image_sizes: dict[int, tuple[int, int]],
    accepted_links: list[AcceptedFootnoteLink] | None = None,
    accepted_blocks: list[AcceptedFootnoteBlock] | None = None,
    accepted_transcriptions: dict[str, AcceptedFootnoteTranscription] | None = None,
    rejected_ref_ids: set[str] | None = None,
) -> tuple[dict[int, list[FootnoteBlock]], dict[str, FootnoteBlock], list[dict[str, str]]]:
    blocks_by_page: dict[int, list[FootnoteBlock]] = {}
    note_by_line: dict[int, FootnoteBlock] = {}
    note_by_marker_word: dict[str, FootnoteBlock] = {}
    qa_rows: list[dict[str, str]] = []
    accepted_by_page: defaultdict[int, list[AcceptedFootnoteLink]] = defaultdict(list)
    for link in accepted_links or []:
        accepted_by_page[link.page].append(link)
    accepted_blocks_by_page: defaultdict[int, list[AcceptedFootnoteBlock]] = defaultdict(list)
    for block in accepted_blocks or []:
        accepted_blocks_by_page[block.page].append(block)
    accepted_transcriptions = accepted_transcriptions or {}
    rejected_ref_ids = rejected_ref_ids or set()

    for page in pages:
        _width, height = image_sizes[page.page]
        blocks = merge_accepted_and_detected_blocks(
            accepted_blocks_for_page(page, accepted_blocks_by_page.get(page.page, [])),
            footnote_blocks_for_page(page, height),
        )
        blocks_by_page[page.page] = blocks
        for block in blocks:
            transcription = accepted_transcriptions.get(block.xml_id)
            if transcription and transcription.page == page.page:
                if transcription.n:
                    block.raw_n = transcription.n
                block.accepted_transcription = transcription.transcription
                reviewer = f" reviewer={transcription.reviewer}" if transcription.reviewer else ""
                block.evidence = (
                    f"{block.evidence}; " if block.evidence else ""
                ) + f"accepted sidecar transcription {block.xml_id}{reviewer}"
            for line in block.lines:
                note_by_line[id(line)] = block

        markers = marker_candidates_for_page(page, blocks)
        auto_markers = [
            marker
            for marker in markers
            if marker.ref_id not in rejected_ref_ids and is_high_confidence_marker(marker)
        ]
        block_by_id = {block.xml_id: block for block in blocks}
        marker_by_ref_id = {marker.ref_id: marker for marker in markers}
        linked_block_ids: set[str] = set()
        linked_marker_ids: set[str] = set()

        for accepted in accepted_by_page.get(page.page, []):
            marker = marker_by_ref_id.get(accepted.ref_xml_id)
            block = block_by_id.get(accepted.note_xml_id)
            if block is None and accepted.n:
                block = next((candidate for candidate in blocks if candidate.raw_n == accepted.n), None)
            if marker is None and accepted.marker_bbox:
                marker = virtual_marker_from_accepted_link(page, accepted)
            if marker is None or block is None or marker.ref_id in rejected_ref_ids:
                continue
            marker_line = next((line for line in page.lines if line.index == marker.line_index), None)
            if marker_line is None:
                continue
            marker_role, _marker_place = line_type(marker_line, height)
            if id(marker_line) in note_by_line or marker_role in {"header", "pageNum", "note"}:
                continue
            if marker.word_xml_id in note_by_marker_word:
                continue
            if accepted.n:
                block.raw_n = accepted.n
            block.marker = marker
            block.ref_id = accepted.ref_xml_id
            block.status = "linked"
            block.method = f"accepted-sidecar:{accepted.method or 'manual-review'}"
            reviewer = f" reviewer={accepted.reviewer}" if accepted.reviewer else ""
            block.evidence = f"accepted sidecar link {accepted.ref_xml_id}->{accepted.note_xml_id}{reviewer}"
            note_by_marker_word[marker.word_xml_id] = block
            linked_block_ids.add(block.xml_id)
            linked_marker_ids.add(marker.ref_id)

        remaining_blocks = [block for block in blocks if block.xml_id not in linked_block_ids]
        remaining_auto_markers = [
            marker
            for marker in auto_markers
            if marker.ref_id not in linked_marker_ids and marker.word_xml_id not in note_by_marker_word
        ]
        linked = 0
        method = "no-markers-or-notes"
        if remaining_auto_markers and remaining_blocks and len(remaining_auto_markers) == len(remaining_blocks):
            method = "page-ordinal-layout"
            for marker, block in zip(remaining_auto_markers, remaining_blocks):
                block.marker = marker
                block.ref_id = marker.ref_id
                block.status = "linked"
                block.method = method
                block.evidence = marker.line_text
                note_by_marker_word[marker.word_xml_id] = block
                linked += 1
        elif remaining_auto_markers and remaining_blocks and len(remaining_auto_markers) < len(remaining_blocks):
            method = "partial-page-ordinal-layout"
            for marker, block in zip(remaining_auto_markers, remaining_blocks):
                block.marker = marker
                block.ref_id = marker.ref_id
                block.status = "linked"
                block.method = method
                block.evidence = marker.line_text
                note_by_marker_word[marker.word_xml_id] = block
                linked += 1
            for block in remaining_blocks[linked:]:
                block.status = "unresolved-no-marker"
                block.method = method
                block.evidence = "fewer high-confidence marker candidates than note blocks"
        elif remaining_auto_markers and remaining_blocks and len(remaining_auto_markers) > len(remaining_blocks):
            method = "unresolved-ambiguous-marker-count"
            for block in remaining_blocks:
                block.status = "unresolved-ambiguous"
                block.method = method
                block.evidence = "more high-confidence marker candidates than note blocks"
        elif remaining_blocks:
            method = "unresolved-no-marker"
            for block in remaining_blocks:
                block.status = "unresolved-no-marker"
                block.method = method
                block.evidence = "no high-confidence marker candidates before footnote zone"

        marker_summary = " | ".join(
            f"l{marker.line_index}w{marker.word_index}:{marker.base_text}[{marker.marker_text}]"
            for marker in markers[:12]
        )
        auto_marker_summary = " | ".join(
            f"l{marker.line_index}w{marker.word_index}:{marker.base_text}[{marker.marker_text}]"
            for marker in auto_markers[:12]
        )
        for block in blocks:
            qa_rows.append(
                {
                    "page": str(page.page),
                    "note_xml_id": block.xml_id,
                    "raw_n": block.raw_n,
                    "ordinal": str(block.ordinal),
                    "status": block.status,
                    "method": block.method,
                    "ref_xml_id": block.ref_id,
                    "marker_word_id": block.marker.word_xml_id if block.marker else "",
                    "marker_text": block.marker.marker_text if block.marker else "",
                    "marker_line": str(block.marker.line_index) if block.marker else "",
                    "note_first_line": str(block.first_line.index),
                    "note_line_count": str(len(block.lines)),
                    "marker_count": str(len(markers)),
                    "auto_marker_count": str(len(auto_markers)),
                    "note_count": str(len(blocks)),
                    "high_confidence_marker": str(bool(block.marker and is_high_confidence_marker(block.marker))).lower(),
                    "marker_bbox": bbox_str(block.marker.bbox) if block.marker and block.marker.bbox else "",
                    "note_bbox": bbox_str(block.bbox) if block.bbox else "",
                    "evidence": block.evidence,
                    "marker_candidates": marker_summary,
                    "auto_marker_candidates": auto_marker_summary,
                    "note_excerpt": block.text[:220],
                    "accepted_transcription": block.accepted_transcription,
                }
            )
        if not blocks and markers:
            qa_rows.append(
                {
                    "page": str(page.page),
                    "note_xml_id": "",
                    "raw_n": "",
                    "ordinal": "",
                    "status": "unresolved-markers-without-notes",
                    "method": method,
                    "ref_xml_id": "",
                    "marker_word_id": "",
                    "marker_text": "",
                    "marker_line": "",
                    "note_first_line": "",
                    "note_line_count": "",
                    "marker_count": str(len(markers)),
                    "auto_marker_count": str(len(auto_markers)),
                    "note_count": "0",
                    "high_confidence_marker": "false",
                    "marker_bbox": "",
                    "note_bbox": "",
                    "evidence": "marker candidates found but no note zone detected",
                    "marker_candidates": marker_summary,
                    "auto_marker_candidates": auto_marker_summary,
                    "note_excerpt": "",
                    "accepted_transcription": "",
                }
            )

    return blocks_by_page, note_by_marker_word, qa_rows


def top_furniture_parts(
    line: Line,
    page_width: int,
    page_height: int,
) -> list[tuple[str, str, list[Word], tuple[int, int, int, int] | None]]:
    if line.bbox is None or line.bbox[1] >= page_height * 0.10 or len(line.text) > 90:
        return []
    if not line.words:
        return []
    first_word = line.words[0]
    last_word = line.words[-1]
    first_place = top_place(first_word.bbox, page_width)
    last_place = top_place(last_word.bbox, page_width)
    if PAGE_NUMBER_TOKEN_RE.fullmatch(first_word.text) and (len(line.words) == 1 or first_place == "top-left"):
        parts: list[tuple[str, str, list[Word], tuple[int, int, int, int] | None]] = [
            ("pageNum", first_place, [first_word], first_word.bbox),
        ]
        if len(line.words) > 1:
            rest_words = line.words[1:]
            parts.append(("header", "top", rest_words, words_bbox(rest_words) or line.bbox))
        return parts
    if len(line.words) > 1 and PAGE_NUMBER_TOKEN_RE.fullmatch(last_word.text) and last_place == "top-right":
        rest_words = line.words[:-1]
        return [
            ("header", "top", rest_words, words_bbox(rest_words) or line.bbox),
            ("pageNum", last_place, [last_word], last_word.bbox),
        ]
    return [("header", "top", line.words, line.bbox)]


def top_place(bbox: tuple[int, int, int, int] | None, page_width: int) -> str:
    if bbox is None or page_width <= 0:
        return "top"
    left, _top, right, _bottom = bbox
    center = (left + right) / 2
    if center < page_width * 0.40:
        return "top-left"
    if center > page_width * 0.60:
        return "top-right"
    return "top"


def words_bbox(words: list[Word]) -> tuple[int, int, int, int] | None:
    boxes = [word.bbox for word in words if word.bbox is not None]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def add_line_content(
    parent: ET.Element,
    line: Line,
    linked_notes_by_word: dict[str, FootnoteBlock] | None = None,
) -> None:
    lb = ET.SubElement(parent, NS + "lb")
    lb.set("n", str(line.index))
    if line.bbox:
        lb.set("bbox", bbox_str(line.bbox))
    if line.words:
        lb.tail = ""
    add_text_with_words(parent, line.words, linked_notes_by_word or {})


def add_transcription_content(
    parent: ET.Element,
    block: FootnoteBlock,
) -> None:
    lb = ET.SubElement(parent, NS + "lb")
    lb.set("n", str(block.first_line.index))
    if block.first_line.bbox:
        lb.set("bbox", bbox_str(block.first_line.bbox))
    lb.tail = block.accepted_transcription


def add_text_with_words(
    parent: ET.Element,
    words: list[Word],
    linked_notes_by_word: dict[str, FootnoteBlock] | None = None,
) -> None:
    linked_notes_by_word = linked_notes_by_word or {}
    for index, word in enumerate(words):
        element_name = NS + ("foreign" if GREEK_RE.search(word.text) else "w")
        word_id = word_xml_id(word)
        linked_note = linked_notes_by_word.get(word_id)
        marker = marker_from_word(word) if linked_note is not None else None
        virtual_marker = (
            linked_note.marker
            if linked_note is not None and linked_note.marker is not None and linked_note.marker.word_xml_id == word_id
            else None
        )
        word_text = marker[0] if marker else word.text
        marker_text = marker[1] if marker else (virtual_marker.marker_text if virtual_marker else "")
        word_el = ET.SubElement(parent, element_name)
        word_el.set(XML_ID, word_id)
        if word.bbox:
            word_el.set("bbox", bbox_str(word.bbox))
        if word.confidence is not None:
            word_el.set("cert", f"{word.confidence / 100:.3f}")
        if GREEK_RE.search(word_text):
            word_el.set(XML_LANG, "grc")
        word_el.text = word_text
        if linked_note is not None and marker_text:
            ref = ET.SubElement(parent, NS + "ref")
            ref.set("type", "footnote-ref")
            ref.set(XML_ID, linked_note.ref_id)
            ref.set("target", f"#{linked_note.xml_id}")
            if linked_note.raw_n:
                ref.set("n", linked_note.raw_n)
            ref.text = marker_text
        if index < len(words) - 1:
            tail_target = word_el
            if linked_note is not None and marker_text:
                tail_target = list(parent)[-1]
            tail_target.tail = "" if SPACE_BEFORE_RE.match(words[index + 1].text) else " "


def bbox_str(bbox: tuple[int, int, int, int]) -> str:
    return " ".join(str(part) for part in bbox)


def build_tei(
    pages: list[HocrPage],
    image_sizes: dict[int, tuple[int, int]],
    pdf: Path,
    resolution: int,
    langs: str,
    psm: int,
    edition_id: str,
    edition_label: str,
    facs_prefix: str,
    accepted_links: list[AcceptedFootnoteLink] | None = None,
    accepted_blocks: list[AcceptedFootnoteBlock] | None = None,
    accepted_transcriptions: dict[str, AcceptedFootnoteTranscription] | None = None,
    rejected_ref_ids: set[str] | None = None,
) -> tuple[ET.ElementTree, list[dict[str, str]]]:
    footnotes_by_page, linked_notes_by_word, footnote_qa_rows = link_footnotes(
        pages,
        image_sizes,
        accepted_links,
        accepted_blocks,
        accepted_transcriptions,
        rejected_ref_ids,
    )
    note_line_ids = {
        id(line)
        for blocks in footnotes_by_page.values()
        for block in blocks
        for line in block.lines
    }
    note_by_first_line = {
        id(block.first_line): block
        for blocks in footnotes_by_page.values()
        for block in blocks
    }

    root = ET.Element(NS + "TEI")
    root.set(XML_ID, edition_id)
    header = ET.SubElement(root, NS + "teiHeader")
    file_desc = ET.SubElement(header, NS + "fileDesc")
    title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
    ET.SubElement(title_stmt, NS + "title").text = edition_label
    pub_stmt = ET.SubElement(file_desc, NS + "publicationStmt")
    ET.SubElement(pub_stmt, NS + "p").text = "Private local OCR experiment; not a canonical edition."
    source_desc = ET.SubElement(file_desc, NS + "sourceDesc")
    ET.SubElement(source_desc, NS + "p").text = f"Generated from local PDF: {pdf.name}"
    encoding_desc = ET.SubElement(header, NS + "encodingDesc")
    ET.SubElement(encoding_desc, NS + "p").text = (
        f"Pages rendered at {resolution} dpi and OCRed with Tesseract languages {langs}, PSM {psm}. "
        "hOCR line and word bounding boxes are preserved as bbox attributes."
    )
    text = ET.SubElement(root, NS + "text")
    body = ET.SubElement(text, NS + "body")

    for hocr_page in pages:
        width, height = image_sizes[hocr_page.page]
        pb = ET.SubElement(body, NS + "pb")
        pb.set(XML_ID, f"beck-fresh-p{hocr_page.page:04d}")
        pb.set("n", str(hocr_page.page))
        pb.set("seq", str(hocr_page.page))
        pb.set("facs", f"{facs_prefix}beck-{hocr_page.page:04d}.png")
        page_div = ET.SubElement(body, NS + "div")
        page_div.set("type", "page")
        page_div.set("n", str(hocr_page.page))
        page_div.set(XML_ID, f"beck-fresh-page-{hocr_page.page:04d}")
        page_div.set("width", str(width))
        page_div.set("height", str(height))
        if hocr_page.bbox:
            page_div.set("bbox", bbox_str(hocr_page.bbox))
        for line in hocr_page.lines:
            if id(line) in note_line_ids:
                block = note_by_first_line.get(id(line))
                if block is None:
                    continue
                line_el = ET.SubElement(page_div, NS + "note")
                line_el.set("type", "footnote")
                line_el.set("place", "bottom")
                line_el.set(XML_ID, block.xml_id)
                if block.raw_n:
                    line_el.set("n", block.raw_n)
                    line_el.set("raw_n", block.raw_n)
                line_el.set("subtype", block.status)
                line_el.set("resp", block.method)
                if block.ref_id:
                    line_el.set("corresp", f"#{block.ref_id}")
                if block.bbox:
                    line_el.set("bbox", bbox_str(block.bbox))
                if block.accepted_transcription:
                    line_el.set("source", DEFAULT_ACCEPTED_FOOTNOTE_TRANSCRIPTIONS)
                    add_transcription_content(line_el, block)
                else:
                    for note_line in block.lines:
                        add_line_content(line_el, note_line)
                continue

            top_parts = top_furniture_parts(line, width, height)
            if top_parts:
                for part_index, (part_role, part_place, part_words, part_bbox) in enumerate(top_parts, start=1):
                    line_el = ET.SubElement(page_div, NS + "fw")
                    line_el.set("type", part_role)
                    line_el.set("place", part_place)
                    line_el.set(XML_ID, f"beck-fresh-p{hocr_page.page:04d}-l{line.index:03d}-fw{part_index}")
                    if part_bbox:
                        line_el.set("bbox", bbox_str(part_bbox))
                    lb = ET.SubElement(line_el, NS + "lb")
                    lb.set("n", str(line.index))
                    if part_bbox:
                        lb.set("bbox", bbox_str(part_bbox))
                    if part_words:
                        lb.tail = ""
                    add_text_with_words(line_el, part_words)
                continue
            role, place = line_type(line, height)
            if role in {"header", "pageNum"}:
                line_el = ET.SubElement(page_div, NS + "fw")
                line_el.set("type", role)
                if place:
                    line_el.set("place", place)
            elif role == "note":
                line_el = ET.SubElement(page_div, NS + "note")
                line_el.set("place", place or "bottom")
                match = FOOTNOTE_LABEL_RE.match(line.text)
                if match:
                    line_el.set("n", match.group(1))
            else:
                line_el = ET.SubElement(page_div, NS + "ab")
                line_el.set("type", "line")
            line_el.set(XML_ID, f"beck-fresh-p{hocr_page.page:04d}-l{line.index:03d}")
            if role not in {"header", "pageNum"}:
                line_el.set("subtype", role)
            if line.bbox:
                line_el.set("bbox", bbox_str(line.bbox))
            add_line_content(line_el, line, linked_notes_by_word)
    return ET.ElementTree(root), footnote_qa_rows


def read_baseline_pages(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    pages: defaultdict[int, list[str]] = defaultdict(list)
    current_page = 0
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            current_page = int(element.get("seq") or "0")
            continue
        if current_page and tag not in {"teiHeader"}:
            text = element.text or ""
            if text.strip():
                pages[current_page].append(text)
            tail = element.tail or ""
            if tail.strip():
                pages[current_page].append(tail)
    return {page: normalize_ws(" ".join(parts)) for page, parts in pages.items()}


def page_similarity(fresh: str, baseline: str) -> float | None:
    fresh_norm = normalize_for_compare(fresh)
    baseline_norm = normalize_for_compare(baseline)
    if not fresh_norm or not baseline_norm:
        return None
    return SequenceMatcher(None, fresh_norm, baseline_norm).quick_ratio()


def summarize_page(
    page: int,
    paths: dict[str, Path],
    hocr_page: HocrPage,
    size: tuple[int, int],
    baseline_pages: dict[int, str],
) -> tuple[PageQa, list[dict[str, str]]]:
    width, height = size
    words = [word for line in hocr_page.lines for word in line.words]
    confidences = [word.confidence for word in words if word.confidence is not None]
    low_words = [word for word in words if word.confidence is not None and word.confidence < 60]
    text = normalize_ws(Path(paths["txt"]).read_text(encoding="utf-8", errors="replace"))
    bottom_lines = [line for line in hocr_page.lines if line.bbox and line.bbox[3] > height * 0.78]
    bottom_text = "\n".join(line.text for line in bottom_lines)
    qa = PageQa(
        page=page,
        image=str(paths["image"]),
        hocr=str(paths["hocr"]),
        tsv=str(paths["tsv"]),
        txt=str(paths["txt"]),
        width=width,
        height=height,
        word_count=len([word for word in words if WORDISH_RE.search(word.text)]),
        mean_confidence=sum(confidences) / len(confidences) if confidences else None,
        low_confidence_words=len(low_words),
        greek_tokens=sum(1 for word in words if GREEK_RE.search(word.text)),
        baseline_similarity=page_similarity(text, baseline_pages.get(page, "")),
    )
    if page == 58:
        phrase_text = normalize_for_phrase_check(text)
        qa.footnote_47 = bool(re.search(r"(^|\n)\s*47\b", bottom_text))
        qa.footnote_48 = bool(re.search(r"(^|\n)\s*48\b", bottom_text))
        qa.page58_expected = {
            expected: normalize_for_phrase_check(expected) in phrase_text
            for expected in PAGE_58_EXPECTED
        }
    low_rows = []
    for word in sorted(low_words, key=lambda item: item.confidence if item.confidence is not None else 999)[:25]:
        low_rows.append(
            {
                "page": str(page),
                "line": str(word.line_index),
                "word": str(word.word_index),
                "text": word.text,
                "confidence": f"{word.confidence:.2f}" if word.confidence is not None else "",
                "bbox": bbox_str(word.bbox) if word.bbox else "",
                "line_text": hocr_page.lines[word.line_index - 1].text if word.line_index - 1 < len(hocr_page.lines) else "",
            }
        )
    return qa, low_rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_footnote_report(outdir: Path, footnote_rows: list[dict[str, str]]) -> None:
    qa_dir = outdir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "page",
        "note_xml_id",
        "raw_n",
        "ordinal",
        "status",
        "method",
        "ref_xml_id",
        "marker_word_id",
        "marker_text",
        "marker_line",
        "note_first_line",
        "note_line_count",
        "marker_count",
        "auto_marker_count",
        "note_count",
        "high_confidence_marker",
        "marker_bbox",
        "note_bbox",
        "evidence",
        "marker_candidates",
        "auto_marker_candidates",
        "note_excerpt",
        "accepted_transcription",
    ]
    write_csv(qa_dir / "footnote_links.csv", fields, footnote_rows)

    status_counts: defaultdict[str, int] = defaultdict(int)
    method_counts: defaultdict[str, int] = defaultdict(int)
    linked = 0
    unresolved = 0
    pages = sorted({row.get("page", "") for row in footnote_rows if row.get("page")}, key=lambda item: int(item))
    for row in footnote_rows:
        status = row.get("status") or "none"
        method = row.get("method") or "none"
        status_counts[status] += 1
        method_counts[method] += 1
        if status == "linked":
            linked += 1
        elif status.startswith("unresolved"):
            unresolved += 1

    lines = [
        "# Beck Fresh OCR Footnote Report",
        "",
        f"- Pages with footnote evidence: {len(pages)}",
        f"- Footnote blocks: {sum(1 for row in footnote_rows if row.get('note_xml_id'))}",
        f"- Linked refs: {linked}",
        f"- Unresolved/ambiguous rows: {unresolved}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Method Counts", ""])
    for method, count in sorted(method_counts.items()):
        lines.append(f"- `{method}`: {count}")
    lines.extend(["", "## Page Details", ""])
    for row in footnote_rows:
        page = row.get("page", "")
        note = row.get("note_xml_id") or "(no note)"
        lines.extend(
            [
                f"### Page {page} {note}",
                "",
                f"- Status: `{row.get('status')}` via `{row.get('method')}`",
                f"- Raw label: `{row.get('raw_n')}`",
                f"- Ref: `{row.get('ref_xml_id')}` marker `{row.get('marker_text')}` at `{row.get('marker_word_id')}`",
                f"- Counts: markers `{row.get('marker_count')}`, notes `{row.get('note_count')}`",
                f"- Auto markers: `{row.get('auto_marker_count')}`",
                f"- Evidence: {row.get('evidence') or row.get('marker_candidates') or 'none'}",
                f"- Note: {row.get('note_excerpt')}",
                "",
            ]
        )
    (qa_dir / "footnote_report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_report(
    outdir: Path,
    qa_rows: list[PageQa],
    low_rows: list[dict[str, str]],
    footnote_rows: list[dict[str, str]],
    tei_path: Path,
    manifest_path: Path,
    pdf_total_pages: int,
) -> None:
    qa_dir = outdir / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    json_rows = [
        {
            **row.__dict__,
            "mean_confidence": round(row.mean_confidence, 2) if row.mean_confidence is not None else None,
            "baseline_similarity": round(row.baseline_similarity, 4) if row.baseline_similarity is not None else None,
        }
        for row in qa_rows
    ]
    (qa_dir / "page_metrics.json").write_text(json.dumps(json_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(
        qa_dir / "page_metrics.csv",
        [
            "page",
            "word_count",
            "mean_confidence",
            "low_confidence_words",
            "greek_tokens",
            "baseline_similarity",
            "footnote_47",
            "footnote_48",
        ],
        [
            {
                "page": str(row.page),
                "word_count": str(row.word_count),
                "mean_confidence": f"{row.mean_confidence:.2f}" if row.mean_confidence is not None else "",
                "low_confidence_words": str(row.low_confidence_words),
                "greek_tokens": str(row.greek_tokens),
                "baseline_similarity": f"{row.baseline_similarity:.4f}" if row.baseline_similarity is not None else "",
                "footnote_47": str(row.footnote_47).lower(),
                "footnote_48": str(row.footnote_48).lower(),
            }
            for row in qa_rows
        ],
    )
    write_csv(
        qa_dir / "low_confidence_regions.csv",
        ["page", "line", "word", "text", "confidence", "bbox", "line_text"],
        low_rows,
    )
    write_footnote_report(outdir, footnote_rows)

    pages_with_similarity = [row for row in qa_rows if row.baseline_similarity is not None]
    avg_conf = sum(row.mean_confidence or 0 for row in qa_rows) / max(1, len([row for row in qa_rows if row.mean_confidence]))
    avg_sim = sum(row.baseline_similarity or 0 for row in pages_with_similarity) / max(1, len(pages_with_similarity))
    low_total = sum(row.low_confidence_words for row in qa_rows)
    greek_total = sum(row.greek_tokens for row in qa_rows)
    page58 = next((row for row in qa_rows if row.page == 58), None)
    is_full_run = len(qa_rows) == pdf_total_pages
    strong_pages = [
        row
        for row in qa_rows
        if row.mean_confidence is not None
        and row.mean_confidence >= 88
        and row.baseline_similarity is not None
        and row.baseline_similarity >= 0.80
    ]
    if is_full_run:
        recommendation = (
            f"The 300 dpi Tesseract full run completed for all {pdf_total_pages} PDF pages. "
            "Use the footnote report and model-correction pass for unresolved or ambiguous note links."
        )
    else:
        recommendation = (
            f"The 300 dpi Tesseract pilot looks strong enough to justify a full {pdf_total_pages}-page run."
            if len(strong_pages) >= max(1, int(len(qa_rows) * 0.70))
            and (page58 is None or (page58.footnote_47 and page58.footnote_48 and all(page58.page58_expected.values())))
            else f"The 300 dpi Tesseract pilot needs review before a full {pdf_total_pages}-page run."
        )

    lines = [
        f"# Beck Fresh Tesseract hOCR {'Full Run' if is_full_run else 'Pilot'} QA",
        "",
        f"- Pages processed: {len(qa_rows)}",
        f"- Average word confidence: {avg_conf:.2f}",
        f"- Average similarity against current `beck.xml`: {avg_sim:.4f}",
        f"- Low-confidence words (<60): {low_total}",
        f"- Greek-script tokens recognized: {greek_total}",
        f"- Recommendation: {recommendation}",
        "",
        "## Page Metrics",
        "",
        "| Page | Words | Mean conf | Low conf | Greek tokens | Beck XML similarity |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in qa_rows:
        lines.append(
            "| "
            f"{row.page} | {row.word_count} | "
            f"{format_optional(row.mean_confidence, 2)} | "
            f"{row.low_confidence_words} | {row.greek_tokens} | "
            f"{format_optional(row.baseline_similarity, 4)} |"
        )
    if page58:
        lines.extend(
            [
                "",
                "## Page 58 Footnote Check",
                "",
                "Phrase checks normalize Greek capital alpha to Latin A for diagnostics; raw OCR files are unchanged.",
                "",
                f"- Bottom note 47 detected: {str(page58.footnote_47).lower()}",
                f"- Bottom note 48 detected: {str(page58.footnote_48).lower()}",
            ]
        )
        for expected, present in page58.page58_expected.items():
            lines.append(f"- Contains `{expected}`: {str(present).lower()}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- TEI: `{tei_path}`",
            f"- Viewer manifest: `{manifest_path}`",
            f"- Page metrics: `{qa_dir / 'page_metrics.csv'}`",
            f"- Low-confidence regions: `{qa_dir / 'low_confidence_regions.csv'}`",
            f"- Footnote links: `{qa_dir / 'footnote_links.csv'}`",
            f"- Footnote report: `{qa_dir / 'footnote_report.md'}`",
        ]
    )
    (qa_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_optional(value: float | None, places: int) -> str:
    return f"{value:.{places}f}" if value is not None else ""


def repo_display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def fresh_section_for_page(page: int) -> str:
    if page <= 4:
        return "cover-and-front"
    if page <= 29:
        return "front"
    if page <= 681:
        return "body"
    return "back"


def write_manifest(
    manifest_path: Path,
    pages: list[int],
    image_sizes: dict[int, tuple[int, int]],
    qa_rows: list[PageQa],
    pdf: Path,
    outdir: Path,
    output_xml: Path,
    pdf_total_pages: int,
    resolution: int,
    langs: str,
    psm: int,
) -> None:
    qa_by_page = {row.page: row for row in qa_rows}
    local_image_root = f"{repo_display_path(outdir / 'images').rstrip('/')}/"
    manifest_pages = []
    for index, page in enumerate(pages):
        width, height = image_sizes[page]
        image_name = f"beck-{page:04d}.png"
        image_path = f"{local_image_root}{image_name}"
        qa = qa_by_page.get(page)
        manifest_pages.append(
            {
                "page_index": index,
                "pdf_page": page,
                "seq": page,
                "book_page": str(page),
                "section": fresh_section_for_page(page),
                "book": "",
                "chapter": "",
                "tei_facs": image_path,
                "facs": image_path,
                "image": image_name,
                "xml_id": f"beck-fresh-p{page:04d}",
                "width": width,
                "height": height,
                "word_count": qa.word_count if qa else None,
                "mean_confidence": round(qa.mean_confidence, 2) if qa and qa.mean_confidence is not None else None,
                "greek_tokens": qa.greek_tokens if qa else None,
            }
        )

    payload = {
        "total_pages": len(manifest_pages),
        "pdf_total_pages": pdf_total_pages,
        "source": "Beck 2020 fresh OCR from local PDF",
        "private": True,
        "image_mode": "local",
        "local_image_root": local_image_root,
        "tei": repo_display_path(output_xml),
        "pdf": pdf.name,
        "resolution": resolution,
        "tesseract_langs": langs,
        "tesseract_psm": psm,
        "pages": manifest_pages,
        "sections": [
            {"id": "cover-and-front", "label": "Cover/front matter"},
            {"id": "front", "label": "Front matter"},
            {"id": "body", "label": "Body"},
            {"id": "back", "label": "Back matter"},
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_private_registry(
    registry_path: Path,
    edition_id: str,
    edition_label: str,
    output_xml: Path,
    manifest_path: Path,
    outdir: Path,
) -> None:
    local_image_root = f"{repo_display_path(outdir / 'images').rstrip('/')}/"
    payload = {
        "defaultEdition": edition_id,
        "private": True,
        "editions": [
            {
                "id": edition_id,
                "label": edition_label,
                "tei": repo_display_path(output_xml),
                "manifest": repo_display_path(manifest_path),
                "imageMode": "local",
                "localImageRoot": local_image_root,
                "imageLabelRoot": local_image_root,
                "sourceLabel": "Local private Beck PDF fresh OCR",
                "licenseNote": "Private local review only. Generated from a local Beck PDF and not suitable for public registry promotion without a publication-safe policy.",
            }
        ],
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="Local Beck PDF source")
    parser.add_argument("--pages", default=DEFAULT_PAGES, help="Comma-separated PDF pages or ranges")
    parser.add_argument("--all-pages", action="store_true", help="Process every page reported by pdfinfo")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help="Ignored experiment output directory")
    parser.add_argument("--output-xml", default=DEFAULT_OUTPUT_XML, help="Fresh stream TEI output path")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="Fresh stream viewer manifest path")
    parser.add_argument("--private-registry", default=DEFAULT_PRIVATE_REGISTRY, help="Fresh stream private viewer registry path")
    parser.add_argument("--accepted-footnotes", default=DEFAULT_ACCEPTED_FOOTNOTES, help="Approved fresh footnote link sidecar CSV")
    parser.add_argument("--accepted-footnote-blocks", default=DEFAULT_ACCEPTED_FOOTNOTE_BLOCKS, help="Approved fresh footnote note-block sidecar CSV")
    parser.add_argument(
        "--accepted-footnote-transcriptions",
        default=DEFAULT_ACCEPTED_FOOTNOTE_TRANSCRIPTIONS,
        help="Approved fresh footnote transcription sidecar CSV",
    )
    parser.add_argument("--rejected-footnotes", default=DEFAULT_REJECTED_FOOTNOTES, help="Rejected fresh footnote candidate sidecar CSV")
    parser.add_argument("--edition-id", default=DEFAULT_EDITION_ID, help="Viewer edition id for the fresh stream")
    parser.add_argument("--edition-label", default=DEFAULT_EDITION_LABEL, help="Viewer edition label for the fresh stream")
    parser.add_argument("--resolution", type=int, default=300, help="PDF render resolution in dpi")
    parser.add_argument("--langs", default="eng+lat+grc", help="Tesseract language string")
    parser.add_argument("--psm", type=int, default=4, help="Tesseract page segmentation mode")
    parser.add_argument("--baseline", default=BASELINE_XML, help="Existing Beck XML for diagnostic comparison")
    parser.add_argument("--force", action="store_true", help="Re-render/re-OCR existing page artifacts")
    args = parser.parse_args()

    pdf = Path(args.pdf)
    outdir = Path(args.outdir)
    output_xml = Path(args.output_xml)
    manifest_path = Path(args.manifest)
    private_registry_path = Path(args.private_registry)
    accepted_footnotes_path = Path(args.accepted_footnotes)
    accepted_footnote_blocks_path = Path(args.accepted_footnote_blocks)
    accepted_footnote_transcriptions_path = Path(args.accepted_footnote_transcriptions)
    rejected_footnotes_path = Path(args.rejected_footnotes)
    baseline = Path(args.baseline)
    if not pdf.exists():
        raise SystemExit(f"Missing PDF: {pdf}")

    preflight(args.langs)
    total_pdf_pages = pdf_page_count(pdf)
    pages = list(range(1, total_pdf_pages + 1)) if args.all_pages else parse_pages(args.pages)
    if not pages:
        raise SystemExit("No pages selected")
    out_of_range = [page for page in pages if page < 1 or page > total_pdf_pages]
    if out_of_range:
        raise SystemExit(f"Selected pages outside PDF range 1-{total_pdf_pages}: {out_of_range[:10]}")
    baseline_pages = read_baseline_pages(baseline)
    accepted_links = load_accepted_footnote_links(accepted_footnotes_path)
    accepted_blocks = load_accepted_footnote_blocks(accepted_footnote_blocks_path)
    accepted_transcriptions = load_accepted_footnote_transcriptions(accepted_footnote_transcriptions_path)
    rejected_ref_ids = load_rejected_footnote_refs(rejected_footnotes_path)
    outdir.mkdir(parents=True, exist_ok=True)

    parsed_pages: list[HocrPage] = []
    image_sizes: dict[int, tuple[int, int]] = {}
    qa_rows: list[PageQa] = []
    low_rows: list[dict[str, str]] = []

    for page in pages:
        paths = output_paths(outdir, page)
        print(f"[beck fresh] page {page}: render", flush=True)
        render_page(pdf, paths["image"], page, args.resolution, args.force)
        print(f"[beck fresh] page {page}: tesseract {args.langs} psm {args.psm}", flush=True)
        run_tesseract(paths["image"], paths, args.langs, args.psm, args.force)
        hocr_page = parse_hocr(paths["hocr"], page)
        size = image_size(paths["image"])
        parsed_pages.append(hocr_page)
        image_sizes[page] = size
        page_qa, page_low_rows = summarize_page(page, paths, hocr_page, size, baseline_pages)
        qa_rows.append(page_qa)
        low_rows.extend(page_low_rows)

    tei_dir = outdir / "tei"
    tei_dir.mkdir(parents=True, exist_ok=True)
    tei_path = tei_dir / output_xml.name
    facs_prefix = f"{repo_display_path(outdir / 'images').rstrip('/')}/"
    tree, footnote_rows = build_tei(
        parsed_pages,
        image_sizes,
        pdf,
        args.resolution,
        args.langs,
        args.psm,
        args.edition_id,
        args.edition_label,
        facs_prefix,
        accepted_links,
        accepted_blocks,
        accepted_transcriptions,
        rejected_ref_ids,
    )
    ET.indent(tree, space="  ")
    tree.write(tei_path, encoding="utf-8", xml_declaration=True)
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_xml, encoding="utf-8", xml_declaration=True)
    write_manifest(
        manifest_path,
        pages,
        image_sizes,
        qa_rows,
        pdf,
        outdir,
        output_xml,
        total_pdf_pages,
        args.resolution,
        args.langs,
        args.psm,
    )
    write_private_registry(private_registry_path, args.edition_id, args.edition_label, output_xml, manifest_path, outdir)
    write_report(outdir, qa_rows, low_rows, footnote_rows, output_xml, manifest_path, total_pdf_pages)

    page58 = next((row for row in qa_rows if row.page == 58), None)
    print(f"Wrote {tei_path}")
    print(f"Wrote {output_xml}")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {private_registry_path}")
    print(f"Wrote {outdir / 'qa' / 'report.md'}")
    print(f"Wrote {outdir / 'qa' / 'footnote_report.md'}")
    if page58:
        expected_ok = all(page58.page58_expected.values())
        print(
            "Page 58: "
            f"note47={page58.footnote_47} note48={page58.footnote_48} "
            f"expected_phrases={expected_ok}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
