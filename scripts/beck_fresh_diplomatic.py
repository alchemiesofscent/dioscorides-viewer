#!/usr/bin/env python3
"""Shared helpers for the private Beck fresh diplomatic EpiDoc workflow."""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"
XML_SPACE = f"{{{XML}}}space"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

EXPECTED_CHAPTERS = {1: 129, 2: 186, 3: 158, 4: 192, 5: 162}
DEFAULT_SOURCE_XML = Path("beck.xml")
DEFAULT_FRESH_DIR = Path("ocr/beck2020_fresh")
DEFAULT_FRESH_MANIFEST = Path("editions/beck2020_fresh/manifest.json")
DEFAULT_DIPLOMATIC_DIR = Path("ocr/beck2020_fresh/diplomatic")
DEFAULT_STRUCTURE_LEDGER = DEFAULT_DIPLOMATIC_DIR / "structure_ledger.csv"
DEFAULT_TEXT_CORRECTION_LEDGER = DEFAULT_DIPLOMATIC_DIR / "text_correction_ledger.csv"
DEFAULT_BACK_MATTER_TRIAGE_LEDGER = DEFAULT_DIPLOMATIC_DIR / "back_matter_triage_ledger.csv"
DEFAULT_AUDIT_SUMMARY = Path("output/beck2020_fresh_diplomatic_audit/structure_summary.md")
DEFAULT_DIPLOMATIC_OUTPUT = Path("output/beck2020_fresh_diplomatic_epidoc.xml")
DEFAULT_DIPLOMATIC_MANIFEST = Path("editions/beck2020_fresh_diplomatic/manifest.json")
DEFAULT_DIPLOMATIC_REGISTRY = Path("editions/beck2020_fresh_diplomatic/private_registry.json")

DMM_TUID_RE = re.compile(r"^DiosMatMed:(\d+(?:\.\d+)*(?:_\d+)?)$")
BOOK_N_RE = re.compile(r"^\d+$")
CHAPTER_N_RE = re.compile(r"^\d+\.\d+$")
BBOX_RE = re.compile(r"-?\d+")
BAD_XML_ID_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")

STRUCTURE_LEDGER_FIELDS = [
    "row_id",
    "source_xml_id",
    "source_element",
    "source_type",
    "beck_xml_tuid",
    "pdf_page",
    "printed_page",
    "source_bbox",
    "source_heading_text",
    "detected_heading_text",
    "corrected_heading_text",
    "book_id",
    "chapter_id",
    "section_id",
    "hocr_line_index",
    "hocr_bbox",
    "image_path",
    "issue_code",
    "decision",
    "decision_evidence",
]

TEXT_CORRECTION_FIELDS = [
    "correction_id",
    "pdf_page",
    "image_path",
    "line_index",
    "word_ids",
    "bbox",
    "old_ocr",
    "corrected_surface",
    "certainty",
    "reviewer",
    "decision",
    "evidence",
    "applied_at",
]

BACK_MATTER_TRIAGE_FIELDS = [
    "pdf_page",
    "printed_page",
    "image_path",
    "source_section",
    "classification",
    "decision",
    "evidence",
    "reviewer",
    "notes",
]


@dataclass(frozen=True)
class StructureEvent:
    row_id: str
    source_xml_id: str
    source_element: str
    source_type: str
    beck_xml_tuid: str
    n: str
    pdf_page: int
    printed_page: str
    source_bbox: str
    source_heading_text: str
    detected_heading_text: str = ""
    corrected_heading_text: str = ""
    hocr_line_index: str = ""
    hocr_bbox: str = ""
    image_path: str = ""
    issue_code: str = ""
    decision: str = ""
    decision_evidence: str = ""

    @property
    def y(self) -> int:
        bbox = parse_bbox(self.source_bbox)
        return bbox[1] if bbox else 0

    @property
    def book_id(self) -> str:
        return self.n.split(".", 1)[0] if self.n else ""

    @property
    def chapter_id(self) -> str:
        if self.source_type == "chapter":
            return self.n
        if self.source_type == "section" and "." in self.n:
            return ".".join(self.n.split(".")[:2])
        return ""

    @property
    def section_id(self) -> str:
        return self.n if self.source_type == "section" else ""

    def to_row(self) -> dict[str, str]:
        return {
            "row_id": self.row_id,
            "source_xml_id": self.source_xml_id,
            "source_element": self.source_element,
            "source_type": self.source_type,
            "beck_xml_tuid": self.beck_xml_tuid,
            "pdf_page": str(self.pdf_page or ""),
            "printed_page": self.printed_page,
            "source_bbox": self.source_bbox,
            "source_heading_text": self.source_heading_text,
            "detected_heading_text": self.detected_heading_text,
            "corrected_heading_text": self.corrected_heading_text or self.source_heading_text,
            "book_id": self.book_id,
            "chapter_id": self.chapter_id,
            "section_id": self.section_id,
            "hocr_line_index": self.hocr_line_index,
            "hocr_bbox": self.hocr_bbox,
            "image_path": self.image_path,
            "issue_code": self.issue_code,
            "decision": self.decision,
            "decision_evidence": self.decision_evidence,
        }


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_match(text: str) -> str:
    text = normalize_ws(text).casefold()
    text = re.sub(r"[^0-9a-z\u0370-\u03ff\u1f00-\u1fff]+", " ", text)
    return normalize_ws(text)


def parse_bbox(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(part) for part in BBOX_RE.findall(value)]
    if len(parts) < 4:
        return None
    left, top, right, bottom = parts[:4]
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def bbox_top(value: str | None) -> int:
    bbox = parse_bbox(value)
    return bbox[1] if bbox else 0


def bbox_str(bbox: tuple[int, int, int, int] | None) -> str:
    return " ".join(str(part) for part in bbox) if bbox else ""


def slug_xml_id(*parts: str) -> str:
    raw = "-".join(part for part in parts if part)
    base = BAD_XML_ID_CHARS_RE.sub("-", raw.strip())
    base = re.sub(r"-+", "-", base).strip("-")
    if not base:
        base = "item"
    if not re.match(r"^[A-Za-z_]", base):
        base = f"beck-{base}"
    return base


def repo_display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [{key: value for key, value in row.items() if key is not None} for row in csv.DictReader(handle)]


def write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_manifest(path: Path = DEFAULT_FRESH_MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def descendant_text(element: ET.Element) -> str:
    return normalize_ws(" ".join(element.itertext()))


def direct_child(element: ET.Element, tag_name: str) -> ET.Element | None:
    for child in list(element):
        if local_name(child.tag) == tag_name:
            return child
    return None


def first_descendant_bbox(element: ET.Element) -> str:
    own = element.get("bbox")
    if own:
        return own
    for child in element.iter():
        if child is element:
            continue
        bbox = child.get("bbox")
        if bbox:
            return bbox
    return ""


def start_location(element: ET.Element, fallback_page: int, fallback_printed: str) -> tuple[int, str, str]:
    page = fallback_page
    printed = fallback_printed
    for child in element.iter():
        if child is element:
            continue
        tag = local_name(child.tag)
        if tag == "pb":
            try:
                page = int(child.get("seq") or page or 0)
            except ValueError:
                pass
            printed = child.get("n") or printed
            continue
        if tag in {"lb", "tok", "head"}:
            return page, printed, first_descendant_bbox(child)
    return page, printed, ""


def structure_type_from_tuid(tuid: str) -> tuple[str, str]:
    match = DMM_TUID_RE.match(tuid)
    if not match:
        return "", ""
    n = match.group(1)
    if BOOK_N_RE.fullmatch(n):
        return "book", n
    if CHAPTER_N_RE.fullmatch(n):
        return "chapter", n
    return "section", n


def source_heading_for(element: ET.Element, source_type: str, n: str) -> str:
    if source_type == "book":
        return normalize_ws(element.get("n") or f"BOOK {n}")
    if source_type == "chapter":
        head = direct_child(element, "head")
        return descendant_text(head) if head is not None else ""
    if source_type == "back":
        return normalize_ws(element.get("n") or "")
    return ""


def event_sort_key(event: StructureEvent) -> tuple[int, int, int, str]:
    rank = {"front": 0, "book": 1, "back": 1, "chapter": 2, "section": 3}.get(event.source_type, 9)
    return (event.pdf_page or 0, event.y, rank, event.row_id)


def collect_source_structure(source_xml: Path = DEFAULT_SOURCE_XML) -> list[StructureEvent]:
    root = ET.parse(source_xml).getroot()
    text = root.find("text")
    if text is None:
        raise ValueError(f"{source_xml}: expected top-level <text>")

    events: list[StructureEvent] = [
        StructureEvent(
            row_id="front-0001",
            source_xml_id="",
            source_element="synthetic",
            source_type="front",
            beck_xml_tuid="",
            n="front",
            pdf_page=1,
            printed_page="",
            source_bbox="",
            source_heading_text="Front matter",
            corrected_heading_text="Front matter",
            decision="synthetic-front-wrapper",
            decision_evidence="Pages before DiosMatMed:1 are preserved in one front textpart.",
        )
    ]

    state = {"page": 0, "printed": ""}
    row_counter = Counter()
    back_added = False
    seen_book = False
    completed_books = set()

    def make_event(element: ET.Element, source_type: str, n: str, tuid: str = "") -> StructureEvent:
        row_counter[source_type] += 1
        page, printed, bbox = start_location(element, int(state["page"] or 0), str(state["printed"] or ""))
        source_id = element.get("id") or ""
        row_n = n or source_type
        row_id = f"{source_type}-{slug_xml_id(row_n, source_id, str(row_counter[source_type]))}"
        heading = source_heading_for(element, source_type, n)
        return StructureEvent(
            row_id=row_id,
            source_xml_id=source_id,
            source_element=local_name(element.tag),
            source_type=source_type,
            beck_xml_tuid=tuid,
            n=n,
            pdf_page=page,
            printed_page=printed,
            source_bbox=bbox,
            source_heading_text=heading,
            corrected_heading_text=heading,
        )

    def walk(element: ET.Element) -> None:
        nonlocal back_added, seen_book
        tag = local_name(element.tag)

        if tag == "pb":
            try:
                state["page"] = int(element.get("seq") or state["page"] or 0)
            except ValueError:
                pass
            state["printed"] = element.get("n") or state["printed"]

        tuid = element.get("tuid") or ""
        source_type, n = structure_type_from_tuid(tuid)
        if source_type:
            if source_type == "book":
                seen_book = True
                completed_books.add(n)
            events.append(make_event(element, source_type, n, tuid))
        elif tag == "div" and seen_book and len(completed_books) >= 5 and not back_added and element.get("n"):
            events.append(make_event(element, "back", "back", ""))
            back_added = True

        for child in list(element):
            walk(child)

    for child in list(text):
        walk(child)

    return sorted(events, key=event_sort_key)


def hocr_line_candidates(hocr_path: Path) -> list[dict[str, str]]:
    if not hocr_path.exists():
        return []
    try:
        root = ET.parse(hocr_path).getroot()
    except ET.ParseError:
        return []
    rows: list[dict[str, str]] = []
    line_index = 0
    for element in root.iter():
        classes = set((element.get("class") or "").split())
        if not ({"ocr_line", "ocr_textfloat"} & classes):
            continue
        words = []
        for word_el in element.iter():
            if "ocrx_word" in set((word_el.get("class") or "").split()):
                text = normalize_ws("".join(word_el.itertext()))
                if text:
                    words.append(text)
        text = normalize_ws(" ".join(words))
        if not text:
            continue
        line_index += 1
        rows.append(
            {
                "line_index": str(line_index),
                "bbox": title_bbox_str(element.get("title") or ""),
                "text": text,
            }
        )
    return rows


def title_bbox_str(title: str) -> str:
    match = re.search(r"\bbbox\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)", title)
    return " ".join(match.groups()) if match else ""


def best_hocr_match(event: StructureEvent, hocr_dir: Path) -> tuple[str, str, str, str]:
    if event.pdf_page <= 0:
        return "", "", "", "missing-page"
    hocr_path = hocr_dir / f"beck-{event.pdf_page:04d}.hocr"
    candidates = hocr_line_candidates(hocr_path)
    if not candidates:
        return "", "", "", "missing-hocr"

    source_top = event.y
    heading_norm = normalize_for_match(event.source_heading_text)
    scored = []
    for candidate in candidates:
        candidate_top = bbox_top(candidate.get("bbox"))
        y_distance = abs(candidate_top - source_top) if source_top and candidate_top else 0
        if source_top and candidate_top and y_distance > 220:
            continue
        candidate_norm = normalize_for_match(candidate.get("text", ""))
        ratio = SequenceMatcher(None, heading_norm, candidate_norm).ratio() if heading_norm and candidate_norm else 0.0
        score = ratio - (y_distance / 1000.0)
        scored.append((score, ratio, y_distance, candidate))
    if not scored and source_top:
        for candidate in candidates:
            candidate_top = bbox_top(candidate.get("bbox"))
            y_distance = abs(candidate_top - source_top) if candidate_top else 10**9
            scored.append((-y_distance / 1000.0, 0.0, y_distance, candidate))
    if not scored:
        return "", "", "", "missing-hocr-line"
    score, ratio, _distance, best = max(scored, key=lambda item: item[0])
    issue = ""
    if event.source_type in {"book", "chapter", "back"} and heading_norm and ratio < 0.25:
        issue = "hocr-heading-low-similarity"
    return best.get("line_index", ""), best.get("bbox", ""), best.get("text", ""), issue


def ledger_rows_from_events(events: Iterable[StructureEvent], fresh_dir: Path = DEFAULT_FRESH_DIR) -> list[dict[str, str]]:
    hocr_dir = fresh_dir / "hocr"
    image_root = fresh_dir / "images"
    source_counts = Counter(event.n for event in events if event.source_type == "section" and event.n)
    rows: list[dict[str, str]] = []
    for event in events:
        hocr_line, hocr_bbox, hocr_text, issue = best_hocr_match(event, hocr_dir)
        issue_codes = [issue] if issue else []
        if event.source_type == "chapter" and not event.source_heading_text:
            issue_codes.append("missing-source-heading")
        if event.source_type == "section" and source_counts[event.n] > 1:
            issue_codes.append("duplicate-source-section-id")
        if event.source_type in {"front", "section"}:
            decision = event.decision or "structure-marker-from-beck-xml"
        elif issue_codes:
            decision = "needs-review"
        else:
            decision = "use-source-structure-pending-image-review"
        row = StructureEvent(
            **{
                **event.__dict__,
                "detected_heading_text": hocr_text,
                "hocr_line_index": hocr_line,
                "hocr_bbox": hocr_bbox,
                "image_path": repo_display_path(image_root / f"beck-{event.pdf_page:04d}.png")
                if event.pdf_page
                else "",
                "issue_code": ";".join(code for code in issue_codes if code),
                "decision": decision,
                "decision_evidence": event.decision_evidence
                or "beck.xml supplies structure; fresh hOCR supplies page-line evidence; image remains final authority.",
            }
        ).to_row()
        rows.append(row)
    return rows


def write_structure_ledger(
    path: Path = DEFAULT_STRUCTURE_LEDGER,
    source_xml: Path = DEFAULT_SOURCE_XML,
    fresh_dir: Path = DEFAULT_FRESH_DIR,
) -> list[dict[str, str]]:
    rows = ledger_rows_from_events(collect_source_structure(source_xml), fresh_dir)
    write_csv_rows(path, STRUCTURE_LEDGER_FIELDS, rows)
    return rows


def ensure_text_correction_ledger(path: Path = DEFAULT_TEXT_CORRECTION_LEDGER) -> None:
    if path.exists():
        return
    write_csv_rows(path, TEXT_CORRECTION_FIELDS, [])


def back_matter_start_page(structure_rows: list[dict[str, str]]) -> int:
    pages = [
        int(row.get("pdf_page") or "0")
        for row in structure_rows
        if row.get("source_type") == "back" and (row.get("pdf_page") or "").isdigit()
    ]
    return min(pages) if pages else 434


def ensure_back_matter_triage_ledger(
    path: Path = DEFAULT_BACK_MATTER_TRIAGE_LEDGER,
    structure_rows: list[dict[str, str]] | None = None,
    manifest_path: Path = DEFAULT_FRESH_MANIFEST,
) -> list[dict[str, str]]:
    manifest = load_manifest(manifest_path)
    existing = {row.get("pdf_page", ""): row for row in read_csv_rows(path)}
    start_page = back_matter_start_page(structure_rows or [])
    rows: list[dict[str, str]] = []
    for page in manifest.get("pages", []):
        raw_page = str(page.get("pdf_page") or page.get("seq") or "")
        if not raw_page.isdigit() or int(raw_page) < start_page:
            continue
        if raw_page in existing:
            rows.append(existing[raw_page])
            continue
        pdf_page = int(raw_page)
        image_path = page.get("facs") or page.get("tei_facs") or ""
        source_section = "bibliography-or-index"
        classification = "encode-lightly"
        decision = "preserve-page-lines-without-table-modeling"
        notes = "Back matter is preserved diplomatically as page and line text until a table/index pilot justifies fuller modeling."
        if pdf_page == int(manifest.get("pdf_total_pages") or manifest.get("total_pages") or pdf_page):
            source_section = "publisher-production-page"
            classification = "not-worth-full-modeling"
            decision = "preserve-page-break-and-ocr-text-only"
            notes = "Final production/recycling page is not worth detailed table/index modeling."
        rows.append(
            {
                "pdf_page": raw_page,
                "printed_page": str(page.get("book_page") or ""),
                "image_path": image_path,
                "source_section": source_section,
                "classification": classification,
                "decision": decision,
                "evidence": "fresh manifest plus beck.xml back-matter boundary",
                "reviewer": "codex-diplomatic-bootstrap",
                "notes": notes,
            }
        )
    write_csv_rows(path, BACK_MATTER_TRIAGE_FIELDS, rows)
    return rows


def load_structure_ledger(path: Path = DEFAULT_STRUCTURE_LEDGER) -> list[dict[str, str]]:
    rows = read_csv_rows(path)
    if not rows:
        raise FileNotFoundError(f"No structure rows found in {path}")
    return rows


def chapter_counts(rows: list[dict[str, str]]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for row in rows:
        if row.get("source_type") != "chapter":
            continue
        chapter = row.get("chapter_id") or row.get("beck_xml_tuid", "").replace("DiosMatMed:", "")
        if not chapter or "." not in chapter:
            continue
        try:
            counts[int(chapter.split(".", 1)[0])] += 1
        except ValueError:
            continue
    return counts
