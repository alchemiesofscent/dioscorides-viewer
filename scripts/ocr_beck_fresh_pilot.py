#!/usr/bin/env python3
"""Run a contained fresh-OCR Beck pilot from the local PDF.

This experiment deliberately treats ``beck.xml`` only as a diagnostic baseline.
It re-renders selected PDF pages, runs Tesseract, writes raw OCR evidence, builds
a page-first TEI draft from hOCR coordinates, and emits QA summaries under an
ignored output directory.
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
DEFAULT_PDF = "Pedanius Dioscorides - 2020 - De materia medica.pdf"
DEFAULT_OUTDIR = "ocr/beck2020_fresh_pilot"
BASELINE_XML = "beck.xml"
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
WORDISH_RE = re.compile(r"\w", re.UNICODE)
SPACE_BEFORE_RE = re.compile(r"^[,.;:!?%)\]\u2019\u201d]$")
NO_SPACE_AFTER_RE = re.compile(r"[(\[\u2018\u201c]$")
FOOTNOTE_LABEL_RE = re.compile(r"^\s*(\d{1,3})\b")
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
    for command in ("pdftoppm", "identify", "tesseract"):
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
    search_root = page_el if page_el is not None else root
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
    return HocrPage(page=page, bbox=page_bbox, lines=lines)


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


def add_text_with_words(parent: ET.Element, words: list[Word]) -> None:
    for index, word in enumerate(words):
        element_name = NS + ("foreign" if GREEK_RE.search(word.text) else "w")
        word_el = ET.SubElement(parent, element_name)
        word_el.set(XML_ID, f"beck-fresh-p{word.page:04d}-l{word.line_index:03d}-w{word.word_index:03d}")
        if word.bbox:
            word_el.set("bbox", bbox_str(word.bbox))
        if word.confidence is not None:
            word_el.set("cert", f"{word.confidence / 100:.3f}")
        if GREEK_RE.search(word.text):
            word_el.set(XML_LANG, "grc")
        word_el.text = word.text
        if index < len(words) - 1:
            word_el.tail = "" if SPACE_BEFORE_RE.match(words[index + 1].text) else " "


def bbox_str(bbox: tuple[int, int, int, int]) -> str:
    return " ".join(str(part) for part in bbox)


def build_tei(
    pages: list[HocrPage],
    image_sizes: dict[int, tuple[int, int]],
    pdf: Path,
    resolution: int,
    langs: str,
    psm: int,
) -> ET.ElementTree:
    root = ET.Element(NS + "TEI")
    root.set(XML_ID, "beck2020-fresh-pilot")
    header = ET.SubElement(root, NS + "teiHeader")
    file_desc = ET.SubElement(header, NS + "fileDesc")
    title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
    ET.SubElement(title_stmt, NS + "title").text = "Beck 2020 fresh OCR pilot"
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
        pb.set("facs", f"images/beck-{hocr_page.page:04d}.png")
        page_div = ET.SubElement(body, NS + "div")
        page_div.set("type", "page")
        page_div.set("n", str(hocr_page.page))
        page_div.set(XML_ID, f"beck-fresh-page-{hocr_page.page:04d}")
        page_div.set("width", str(width))
        page_div.set("height", str(height))
        if hocr_page.bbox:
            page_div.set("bbox", bbox_str(hocr_page.bbox))
        for line in hocr_page.lines:
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
            lb = ET.SubElement(line_el, NS + "lb")
            lb.set("n", str(line.index))
            if line.bbox:
                lb.set("bbox", bbox_str(line.bbox))
            if line.words:
                lb.tail = ""
            add_text_with_words(line_el, line.words)
    return ET.ElementTree(root)


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


def write_report(outdir: Path, qa_rows: list[PageQa], low_rows: list[dict[str, str]]) -> None:
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

    pages_with_similarity = [row for row in qa_rows if row.baseline_similarity is not None]
    avg_conf = sum(row.mean_confidence or 0 for row in qa_rows) / max(1, len([row for row in qa_rows if row.mean_confidence]))
    avg_sim = sum(row.baseline_similarity or 0 for row in pages_with_similarity) / max(1, len(pages_with_similarity))
    low_total = sum(row.low_confidence_words for row in qa_rows)
    greek_total = sum(row.greek_tokens for row in qa_rows)
    page58 = next((row for row in qa_rows if row.page == 58), None)
    strong_pages = [
        row
        for row in qa_rows
        if row.mean_confidence is not None
        and row.mean_confidence >= 88
        and row.baseline_similarity is not None
        and row.baseline_similarity >= 0.80
    ]
    recommendation = (
        "The 300 dpi Tesseract pilot looks strong enough to justify a full 710-page run."
        if len(strong_pages) >= max(1, int(len(qa_rows) * 0.70))
        and (page58 is None or (page58.footnote_47 and page58.footnote_48 and all(page58.page58_expected.values())))
        else "The 300 dpi Tesseract pilot needs review before a full 710-page run."
    )

    lines = [
        "# Beck Fresh Tesseract hOCR Pilot QA",
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
            f"- TEI: `{outdir / 'tei' / 'beck2020_fresh_pilot.xml'}`",
            f"- Page metrics: `{qa_dir / 'page_metrics.csv'}`",
            f"- Low-confidence regions: `{qa_dir / 'low_confidence_regions.csv'}`",
        ]
    )
    (qa_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def format_optional(value: float | None, places: int) -> str:
    return f"{value:.{places}f}" if value is not None else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="Local Beck PDF source")
    parser.add_argument("--pages", default=DEFAULT_PAGES, help="Comma-separated PDF pages or ranges")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help="Ignored experiment output directory")
    parser.add_argument("--resolution", type=int, default=300, help="PDF render resolution in dpi")
    parser.add_argument("--langs", default="eng+lat+grc", help="Tesseract language string")
    parser.add_argument("--psm", type=int, default=4, help="Tesseract page segmentation mode")
    parser.add_argument("--baseline", default=BASELINE_XML, help="Existing Beck XML for diagnostic comparison")
    parser.add_argument("--force", action="store_true", help="Re-render/re-OCR existing page artifacts")
    args = parser.parse_args()

    pdf = Path(args.pdf)
    outdir = Path(args.outdir)
    baseline = Path(args.baseline)
    pages = parse_pages(args.pages)
    if not pages:
        raise SystemExit("No pages selected")
    if not pdf.exists():
        raise SystemExit(f"Missing PDF: {pdf}")

    preflight(args.langs)
    baseline_pages = read_baseline_pages(baseline)
    outdir.mkdir(parents=True, exist_ok=True)

    parsed_pages: list[HocrPage] = []
    image_sizes: dict[int, tuple[int, int]] = {}
    qa_rows: list[PageQa] = []
    low_rows: list[dict[str, str]] = []

    for page in pages:
        paths = output_paths(outdir, page)
        print(f"[beck fresh pilot] page {page}: render", flush=True)
        render_page(pdf, paths["image"], page, args.resolution, args.force)
        print(f"[beck fresh pilot] page {page}: tesseract {args.langs} psm {args.psm}", flush=True)
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
    tei_path = tei_dir / "beck2020_fresh_pilot.xml"
    tree = build_tei(parsed_pages, image_sizes, pdf, args.resolution, args.langs, args.psm)
    ET.indent(tree, space="  ")
    tree.write(tei_path, encoding="utf-8", xml_declaration=True)
    write_report(outdir, qa_rows, low_rows)

    page58 = next((row for row in qa_rows if row.page == 58), None)
    print(f"Wrote {tei_path}")
    print(f"Wrote {outdir / 'qa' / 'report.md'}")
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
