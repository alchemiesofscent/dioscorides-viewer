#!/usr/bin/env python3
"""Build the private diplomatic Beck fresh EpiDoc from hOCR and ledgers."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from beck_fresh_diplomatic import (
    DEFAULT_BACK_MATTER_TRIAGE_LEDGER,
    DEFAULT_DIPLOMATIC_MANIFEST,
    DEFAULT_DIPLOMATIC_OUTPUT,
    DEFAULT_DIPLOMATIC_REGISTRY,
    DEFAULT_FRESH_DIR,
    DEFAULT_FRESH_MANIFEST,
    DEFAULT_STRUCTURE_LEDGER,
    DEFAULT_TEXT_CORRECTION_LEDGER,
    NS,
    TEI,
    XML,
    XML_ID,
    XML_SPACE,
    bbox_top,
    chapter_counts,
    load_manifest,
    load_structure_ledger,
    parse_bbox,
    read_csv_rows,
    repo_display_path,
    slug_xml_id,
)
from ocr_beck_fresh_pilot import (
    GREEK_RE,
    PAGE_NUMBER_TOKEN_RE,
    SPACE_BEFORE_RE,
    WORDISH_RE,
    add_transcription_content,
    bbox_str,
    clean_latin_token,
    line_type,
    link_footnotes,
    load_accepted_footnote_blocks,
    load_accepted_footnote_links,
    load_accepted_footnote_transcriptions,
    load_rejected_footnote_refs,
    marker_from_word,
    output_paths,
    parse_hocr,
    is_marker_only_word,
    is_latin_abbreviated_genus,
    is_latin_authority,
    is_latin_genus,
    latin_name_word_ids,
    top_furniture_parts,
    word_xml_id,
    write_footnote_report,
)


ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

DEFAULT_LINE_ROLE_OVERRIDES = DEFAULT_FRESH_DIR / "diplomatic" / "line_role_overrides.csv"


@dataclass(frozen=True)
class WordCorrection:
    correction_id: str
    corrected_surface: str
    certainty: str
    decision: str
    evidence: str


def event_y(row: dict[str, str]) -> int:
    deferred_y = row.get("_deferred_event_y")
    if deferred_y and str(deferred_y).isdigit():
        return int(deferred_y)
    return bbox_top(row.get("source_bbox")) or bbox_top(row.get("hocr_bbox"))


def event_sort_key(row: dict[str, str]) -> tuple[int, int, int, str]:
    rank = {"front": 0, "book": 1, "back": 1, "chapter": 2, "section": 3}.get(row.get("source_type", ""), 9)
    page = int(row.get("pdf_page") or "0")
    return (page, event_y(row), rank, row.get("row_id", ""))


def line_top(line) -> int:
    return line.bbox[1] if line.bbox else 0


def line_is_page_furniture(line, width: int, height: int) -> bool:
    if top_furniture_parts(line, width, height):
        return True
    role, _place = line_type(line, height)
    return role in {"header", "pageNum"}


def open_before_page_break(row: dict[str, str], page_lines: list, width: int, height: int) -> bool:
    source_type = row.get("source_type", "")
    if source_type == "front":
        return True
    y = event_y(row)
    if not y:
        return True
    heading_line_index = int(row.get("hocr_line_index") or "0") if (row.get("hocr_line_index") or "").isdigit() else 0
    for line in page_lines:
        if heading_line_index and line.index == heading_line_index:
            continue
        top = line_top(line)
        if not top or top >= y - 4:
            continue
        if line_is_page_furniture(line, width, height):
            continue
        return False
    return True


def row_heading(row: dict[str, str]) -> str:
    return (row.get("corrected_heading_text") or row.get("source_heading_text") or row.get("detected_heading_text") or "").strip()


def should_skip_heading_line(row: dict[str, str]) -> bool:
    return bool(row_heading(row)) and row.get("source_type") in {"book", "chapter", "back"}


def use_source_head_only(row: dict[str, str]) -> bool:
    return row.get("_source_head_only") == "1"


def structure_xml_id(row: dict[str, str]) -> str:
    return slug_xml_id(
        "beck-fresh-diplomatic",
        row.get("source_type", "textpart"),
        row.get("book_id") or row.get("chapter_id") or row.get("section_id") or row.get("row_id", ""),
        row.get("source_xml_id", ""),
        row.get("row_id", ""),
    )


def load_word_corrections(path: Path) -> dict[str, WordCorrection]:
    corrections: dict[str, WordCorrection] = {}
    accepted = {"apply", "accepted", "unclear", "delete", "omit", "not-latin", "no-latin", "plain", "latin", "force-latin"}
    for row in read_csv_rows(path):
        decision = (row.get("decision") or "").strip().casefold()
        if decision not in accepted:
            continue
        word_ids = [part for part in re.split(r"[\s,;]+", row.get("word_ids", "")) if part]
        if len(word_ids) != 1:
            continue
        surface = (row.get("corrected_surface") or "").strip()
        if not surface and decision not in {"unclear", "delete", "omit", "latin", "force-latin"}:
            continue
        corrections[word_ids[0]] = WordCorrection(
            correction_id=row.get("correction_id", ""),
            corrected_surface=surface,
            certainty=row.get("certainty", ""),
            decision=decision,
            evidence=row.get("evidence", ""),
        )
    return corrections


def merge_correction_layers(*layers: dict[str, WordCorrection]) -> dict[str, WordCorrection]:
    merged: dict[str, WordCorrection] = {}
    for layer in layers:
        merged.update(layer)
    return merged


def load_line_role_overrides(path: Path) -> dict[tuple[int, int], str]:
    overrides: dict[tuple[int, int], str] = {}
    if not path.exists():
        return overrides
    for row in read_csv_rows(path):
        try:
            page = int(row.get("page") or "0")
            line = int(row.get("line") or "0")
        except ValueError:
            continue
        role = (row.get("role") or "").strip()
        if page and line and role:
            overrides[(page, line)] = role
    return overrides


def heading_tokens(value: str) -> list[str]:
    value = re.sub(r"^([IVX]+),(\d+)\b", r"\1, \2", value.strip())
    return [part for part in value.split() if part]


def token_has_greek(value: str) -> bool:
    return bool(GREEK_RE.search(value))


def is_source_latin_genus(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Za-z-]+[.,;:]?", clean_latin_token(value))) or is_latin_abbreviated_genus(value)


def is_source_latin_species(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z-]+[.,;:]?", clean_latin_token(value)))


def source_latin_authority_indices(tokens: list[str], start: int) -> list[int]:
    if start >= len(tokens):
        return []
    if is_latin_authority(tokens[start]):
        return [start]
    if start + 1 < len(tokens) and clean_latin_token(tokens[start]) == "L" and clean_latin_token(tokens[start + 1]) == ".":
        return [start, start + 1]
    return []


def source_latin_name_token_indices(tokens: list[str]) -> set[int]:
    indices: set[int] = set()
    for index, token in enumerate(tokens):
        if token_has_greek(token):
            continue
        genus_indices = [index]
        species_index = index + 1
        if is_latin_abbreviated_genus(token) and species_index < len(tokens) and clean_latin_token(tokens[species_index]) == ".":
            genus_indices.append(species_index)
            species_index += 1
        if species_index >= len(tokens):
            continue
        species_token = tokens[species_index]
        if token_has_greek(species_token):
            continue
        if not (is_source_latin_genus(token) and is_source_latin_species(species_token)):
            continue
        authority_indices = source_latin_authority_indices(tokens, species_index + 1)
        if not authority_indices:
            continue
        indices.update(genus_indices)
        indices.add(species_index)
        indices.update(authority_indices)
    return indices


def leading_greek_heading_tokens(value: str) -> list[str]:
    tokens = heading_tokens(value)
    if len(tokens) >= 2 and re.fullmatch(r"[IVXIl1LTΠῚH]+,?", tokens[0]) and re.fullmatch(r"\d+", tokens[1]):
        tokens = tokens[2:]
    elif tokens and re.fullmatch(r"[IVXIl1LTΠῚH]+,?\d+", tokens[0]):
        tokens = tokens[1:]

    greek_tokens = []
    for token in tokens:
        if not token_has_greek(token):
            break
        greek_tokens.append(token)
    return greek_tokens


def heading_word_start_index(words: list) -> int:
    if len(words) >= 2 and re.fullmatch(r"[IVXIl1LTΠῚH]+,?", words[0].text) and re.fullmatch(r"\d+", words[1].text):
        return 2
    if words and re.fullmatch(r"[IVXIl1LTΠῚH]+,?\d+", words[0].text):
        return 1
    return 0


def build_heading_corrections(
    pages: list,
    heading_line_for: dict[tuple[int, int], dict[str, str]],
    existing_corrections: dict[str, WordCorrection],
) -> dict[str, WordCorrection]:
    first_heading_line_by_row = {
        row.get("row_id", ""): min(
            line_index
            for (page_number, line_index), mapped_row in heading_line_for.items()
            if mapped_row.get("row_id", "") == row.get("row_id", "")
        )
        for row in heading_line_for.values()
        if row.get("row_id", "")
    }
    corrections: dict[str, WordCorrection] = {}
    for page in pages:
        for line in page.lines:
            row = heading_line_for.get((page.page, line.index))
            if not row or row.get("source_type") != "chapter":
                continue
            if first_heading_line_by_row.get(row.get("row_id", "")) != line.index:
                continue
            source_tokens = leading_greek_heading_tokens(row_heading(row))
            if not source_tokens:
                continue
            start = heading_word_start_index(line.words)
            available = len(line.words) - start
            if available <= 0:
                continue
            for source_token, word in zip(source_tokens[:available], line.words[start:]):
                word_id = word_xml_id(word)
                if word_id in existing_corrections:
                    continue
                if word.text == source_token:
                    continue
                if token_has_greek(word.text):
                    continue
                corrections[word_id] = WordCorrection(
                    correction_id=f"structure-heading:{row.get('row_id', '')}:{word_id}",
                    corrected_surface=source_token,
                    certainty="0.97",
                    decision="accepted",
                    evidence="Corrected chapter heading token supplied by structure_ledger.csv from beck.xml alignment.",
                )
    return corrections


def build_heading_latin_corrections(
    pages: list,
    heading_line_for: dict[tuple[int, int], dict[str, str]],
    existing_corrections: dict[str, WordCorrection],
) -> dict[str, WordCorrection]:
    lines_by_row: dict[str, list] = defaultdict(list)
    row_by_id: dict[str, dict[str, str]] = {}
    for page in pages:
        for line in page.lines:
            row = heading_line_for.get((page.page, line.index))
            if not row or row.get("source_type") != "chapter":
                continue
            row_id = row.get("row_id", "")
            if not row_id:
                continue
            lines_by_row[row_id].append(line)
            row_by_id[row_id] = row

    corrections: dict[str, WordCorrection] = {}
    for row_id, lines in lines_by_row.items():
        words = [word for line in sorted(lines, key=lambda item: item.index) for word in line.words]
        for word in words:
            word_id = word_xml_id(word)
            if word_id not in latin_name_word_ids(words) or word_id in existing_corrections:
                continue
            if token_has_greek(word.text):
                continue
            corrections[word_id] = WordCorrection(
                correction_id=f"structure-heading-latin:{row_id}:{word_id}",
                corrected_surface="",
                certainty="0.97",
                decision="latin",
                evidence="Latin scientific-name token detected across full chapter heading from structure_ledger.csv and hOCR.",
            )
    return corrections


def build_source_heading_token_corrections(
    pages: list,
    heading_line_for: dict[tuple[int, int], dict[str, str]],
    existing_corrections: dict[str, WordCorrection],
) -> dict[str, WordCorrection]:
    lines_by_row: dict[str, list] = defaultdict(list)
    row_by_id: dict[str, dict[str, str]] = {}
    for page in pages:
        for line in page.lines:
            row = heading_line_for.get((page.page, line.index))
            if not row or row.get("source_type") != "chapter":
                continue
            row_id = row.get("row_id", "")
            if not row_id:
                continue
            lines_by_row[row_id].append(line)
            row_by_id[row_id] = row

    corrections: dict[str, WordCorrection] = {}
    for row_id, lines in lines_by_row.items():
        row = row_by_id[row_id]
        source_tokens = heading_tokens(row_heading(row))
        words = [word for line in sorted(lines, key=lambda item: item.index) for word in line.words]
        if not source_tokens or len(source_tokens) != len(words):
            continue
        source_latin_indices = source_latin_name_token_indices(source_tokens)
        for index, (source_token, word) in enumerate(zip(source_tokens, words)):
            word_id = word_xml_id(word)
            if word_id in existing_corrections:
                continue
            source_is_latin = index in source_latin_indices and not token_has_greek(source_token)
            if word.text == source_token and not source_is_latin:
                continue
            decision = "force-latin" if source_is_latin else "accepted"
            corrections[word_id] = WordCorrection(
                correction_id=f"structure-heading-token:{row_id}:{word_id}",
                corrected_surface=source_token,
                certainty="0.97",
                decision=decision,
                evidence="Token-aligned chapter heading correction supplied by structure_ledger.csv from beck.xml alignment.",
            )
    return corrections


def add_words(parent: ET.Element, words: list, linked_notes_by_word: dict, corrections: dict[str, WordCorrection]) -> None:
    latin_word_ids = latin_name_word_ids(words)
    for index, word in enumerate(words):
        original_word_id = word_xml_id(word)
        correction = corrections.get(original_word_id)
        if correction and correction.decision in {"delete", "omit"}:
            continue
        linked_note = linked_notes_by_word.get(original_word_id)
        marker = marker_from_word(word) if linked_note is not None else None
        virtual_marker = (
            linked_note.marker
            if linked_note is not None and linked_note.marker is not None and linked_note.marker.word_xml_id == original_word_id
            else None
        )
        base_text = marker[0] if marker else word.text
        word_text = correction.corrected_surface if correction and correction.corrected_surface else base_text
        marker_text = virtual_marker.marker_text if virtual_marker else (marker[1] if marker else "")
        marker_only_virtual = bool(virtual_marker and marker is None and is_marker_only_word(word.text))

        if marker_only_virtual and list(parent):
            list(parent)[-1].tail = ""

        if marker_only_virtual:
            pass
        elif correction and correction.decision == "unclear":
            word_el = ET.SubElement(parent, NS + "unclear")
            word_el.set(XML_ID, original_word_id)
            if correction.certainty:
                word_el.set("cert", correction.certainty)
            word_el.set("resp", f"text-correction-ledger:{correction.correction_id or 'unidentified'}")
            word_el.text = word_text or base_text
        else:
            is_greek = bool(GREEK_RE.search(word_text))
            suppress_latin = bool(correction and correction.decision in {"not-latin", "no-latin", "plain"})
            force_latin = bool(correction and correction.decision in {"latin", "force-latin"})
            is_latin_name = (original_word_id in latin_word_ids or force_latin) and not suppress_latin
            element_name = NS + ("foreign" if is_greek or is_latin_name else "w")
            word_el = ET.SubElement(parent, element_name)
            word_el.set(XML_ID, original_word_id)
            if word.bbox:
                word_el.set("bbox", bbox_str(word.bbox))
            if word.confidence is not None:
                word_el.set("cert", f"{word.confidence / 100:.3f}")
            if correction:
                word_el.set("resp", f"text-correction-ledger:{correction.correction_id or 'unidentified'}")
            if is_greek:
                word_el.set(f"{{{XML}}}lang", "grc")
            elif is_latin_name:
                word_el.set(f"{{{XML}}}lang", "lat")
                word_el.set("rend", "italic")
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
            tail_target = list(parent)[-1]
            tail_target.tail = "" if SPACE_BEFORE_RE.match(words[index + 1].text) else " "


def add_line_content(parent: ET.Element, line, linked_notes_by_word: dict | None, corrections: dict[str, WordCorrection]) -> None:
    lb = ET.SubElement(parent, NS + "lb")
    lb.set("n", str(line.index))
    if line.bbox:
        lb.set("bbox", bbox_str(line.bbox))
    if line.words:
        lb.tail = ""
    add_words(parent, line.words, linked_notes_by_word or {}, corrections)


def line_has_visible_words(line, corrections: dict[str, WordCorrection]) -> bool:
    for word in line.words:
        correction = corrections.get(word_xml_id(word))
        if correction and correction.decision in {"delete", "omit"}:
            continue
        return True
    return False


class DiplomaticBuilder:
    def __init__(
        self,
        structure_rows: list[dict[str, str]],
        corrections: dict[str, WordCorrection],
        facs_prefix: str,
    ) -> None:
        self.structure_rows = sorted(
            [row for row in structure_rows if row.get("decision") != "waived"],
            key=event_sort_key,
        )
        self.corrections = corrections
        self.facs_prefix = facs_prefix.rstrip("/") + "/"
        self.root = ET.Element(NS + "TEI")
        self.root.set(XML_ID, "beck2020_fresh_diplomatic")
        self.edition: ET.Element | None = None
        self.front: ET.Element | None = None
        self.book: ET.Element | None = None
        self.chapter: ET.Element | None = None
        self.section: ET.Element | None = None
        self.back: ET.Element | None = None
        self.head_by_row_id: dict[str, ET.Element] = {}
        self.opened_rows: set[str] = set()

    def make_header(self) -> ET.Element:
        header = ET.Element(NS + "teiHeader")
        file_desc = ET.SubElement(header, NS + "fileDesc")
        title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
        ET.SubElement(title_stmt, NS + "title").text = "Beck 2020 fresh diplomatic OCR EpiDoc"
        pub_stmt = ET.SubElement(file_desc, NS + "publicationStmt")
        ET.SubElement(pub_stmt, NS + "p").text = "Private local corrected diplomatic review artifact; not a public edition."
        source_desc = ET.SubElement(file_desc, NS + "sourceDesc")
        ET.SubElement(source_desc, NS + "p").text = (
            "Generated from local Beck PDF page images and fresh hOCR. beck.xml is used only as structural alignment evidence."
        )
        encoding_desc = ET.SubElement(header, NS + "encodingDesc")
        ET.SubElement(encoding_desc, NS + "p").text = (
            "The body contains one edition div with nested textpart divisions. "
            "Physical pages and lines are represented by pb/lb milestones; page wrapper divs are intentionally not emitted."
        )
        return header

    def initialize(self) -> None:
        self.root.append(self.make_header())
        text = ET.SubElement(self.root, NS + "text")
        body = ET.SubElement(text, NS + "body")
        self.edition = ET.SubElement(body, NS + "div")
        self.edition.set("type", "edition")
        self.edition.set(XML_ID, "beck-fresh-diplomatic-edition")
        self.edition.set(XML_SPACE, "preserve")

    def current_parent(self) -> ET.Element:
        for candidate in (self.section, self.chapter, self.book, self.back, self.front, self.edition):
            if candidate is not None:
                return candidate
        raise RuntimeError("No active diplomatic parent")

    def open_event(self, row: dict[str, str]) -> None:
        row_id = row.get("row_id", "")
        if row_id in self.opened_rows:
            return
        if self.edition is None:
            raise RuntimeError("Builder is not initialized")
        source_type = row.get("source_type", "")
        if source_type == "front":
            if self.front is None:
                self.front = self.make_textpart(row, "front")
                self.edition.append(self.front)
            self.book = self.chapter = self.section = self.back = None
        elif source_type == "book":
            self.front = self.chapter = self.section = self.back = None
            self.book = self.make_textpart(row, "book")
            self.edition.append(self.book)
        elif source_type == "chapter":
            self.section = None
            parent = self.book if self.book is not None else self.edition
            self.chapter = self.make_textpart(row, "chapter")
            parent.append(self.chapter)
        elif source_type == "section":
            parent = self.chapter if self.chapter is not None else self.book if self.book is not None else self.edition
            self.section = self.make_textpart(row, "section")
            parent.append(self.section)
        elif source_type == "back":
            self.front = self.book = self.chapter = self.section = None
            self.back = self.make_textpart(row, "back")
            self.edition.append(self.back)
        self.opened_rows.add(row_id)

    def make_textpart(self, row: dict[str, str], subtype: str) -> ET.Element:
        div = ET.Element(NS + "div")
        div.set("type", "textpart")
        div.set("subtype", subtype)
        div.set(XML_ID, structure_xml_id(row))
        if subtype == "book":
            n = row.get("book_id", "")
        elif subtype == "chapter":
            n = row.get("chapter_id", "")
        elif subtype == "section":
            n = row.get("section_id", "")
        elif subtype == "back":
            n = "back"
        else:
            n = ""
        if n:
            div.set("n", n)
        tuid = row.get("beck_xml_tuid")
        if tuid:
            div.set("source", tuid)
        heading = row_heading(row)
        if heading and subtype in {"book", "chapter", "back"}:
            head = ET.SubElement(div, NS + "head")
            if row.get("hocr_line_index") and not use_source_head_only(row):
                self.head_by_row_id[row.get("row_id", "")] = head
            else:
                head.text = heading
        return div

    def emit_page_break(self, page: int) -> None:
        parent = self.current_parent()
        pb = ET.SubElement(parent, NS + "pb")
        pb.set(XML_ID, f"beck-fresh-diplomatic-p{page:04d}")
        pb.set("n", str(page))
        pb.set("seq", str(page))
        pb.set("facs", f"{self.facs_prefix}beck-{page:04d}.png")

    def emit_line(self, line, width: int, height: int, linked_notes_by_word: dict, force_body: bool = False) -> None:
        parent = self.current_parent()
        if not line_has_visible_words(line, self.corrections):
            return
        top_parts = [] if force_body else top_furniture_parts(line, width, height)
        if top_parts:
            for part_index, (part_role, part_place, part_words, part_bbox) in enumerate(top_parts, start=1):
                fw = ET.SubElement(parent, NS + "fw")
                fw.set("type", part_role)
                fw.set("place", part_place)
                fw.set(XML_ID, f"beck-fresh-diplomatic-p{line.page:04d}-l{line.index:03d}-fw{part_index}")
                if part_bbox:
                    fw.set("bbox", bbox_str(part_bbox))
                lb = ET.SubElement(fw, NS + "lb")
                lb.set("n", str(line.index))
                if part_bbox:
                    lb.set("bbox", bbox_str(part_bbox))
                if part_words:
                    lb.tail = ""
                add_words(fw, part_words, {}, self.corrections)
            return

        role, place = ("body", "") if force_body else line_type(line, height)
        if role in {"header", "pageNum"}:
            line_el = ET.SubElement(parent, NS + "fw")
            line_el.set("type", role)
            if place:
                line_el.set("place", place)
        elif role == "note":
            line_el = ET.SubElement(parent, NS + "note")
            line_el.set("place", place or "bottom")
            match = re.match(r"^\s*(\d{1,3})\b", line.text)
            if match:
                line_el.set("n", match.group(1))
        else:
            line_el = ET.SubElement(parent, NS + "ab")
            line_el.set("type", "line")
            line_el.set("subtype", role)
        line_el.set(XML_ID, f"beck-fresh-diplomatic-p{line.page:04d}-l{line.index:03d}")
        if line.bbox:
            line_el.set("bbox", bbox_str(line.bbox))
        add_line_content(line_el, line, linked_notes_by_word, self.corrections)

    def emit_heading_line(self, row: dict[str, str], line, linked_notes_by_word: dict) -> None:
        head = self.head_by_row_id.get(row.get("row_id", ""))
        if head is None:
            return
        add_line_content(head, line, linked_notes_by_word, self.corrections)

    def emit_footnote(self, block) -> None:
        parent = self.current_parent()
        note = ET.SubElement(parent, NS + "note")
        note.set("type", "footnote")
        note.set("place", "bottom")
        note.set(XML_ID, block.xml_id)
        if block.raw_n:
            note.set("n", block.raw_n)
            note.set("raw_n", block.raw_n)
        note.set("subtype", block.status)
        note.set("resp", block.method)
        if block.ref_id:
            note.set("corresp", f"#{block.ref_id}")
        if block.bbox:
            note.set("bbox", bbox_str(block.bbox))
        if block.accepted_transcription:
            note.set("source", repo_display_path(DEFAULT_FRESH_DIR / "review" / "accepted_footnote_transcriptions.csv"))
            add_transcription_content(note, block)
        else:
            for note_line in block.lines:
                add_line_content(note, note_line, None, self.corrections)


def load_hocr_pages(fresh_dir: Path, manifest_path: Path) -> tuple[list, dict[int, tuple[int, int]], dict]:
    manifest = load_manifest(manifest_path)
    pages = []
    image_sizes: dict[int, tuple[int, int]] = {}
    for page in manifest.get("pages", []):
        pdf_page = int(page.get("pdf_page") or page.get("seq") or 0)
        if not pdf_page:
            continue
        paths = output_paths(fresh_dir, pdf_page)
        if not paths["hocr"].exists():
            raise FileNotFoundError(paths["hocr"])
        pages.append(parse_hocr(paths["hocr"], pdf_page))
        image_sizes[pdf_page] = (int(page.get("width") or 0), int(page.get("height") or 0))
    return pages, image_sizes, manifest


def normalize_heading_text(value: str) -> str:
    value = re.sub(r"[\W_]+", " ", value.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def line_overlaps_vertical_bbox(line, bbox: tuple[int, int, int, int]) -> bool:
    if not line.bbox:
        return False
    _left, top, _right, bottom = line.bbox
    _box_left, box_top, _box_right, box_bottom = bbox
    vertical_overlap = min(bottom, box_bottom) - max(top, box_top)
    if vertical_overlap <= 0:
        return False
    return vertical_overlap >= max(4, (bottom - top) * 0.45)


def heading_line_indices(row: dict[str, str], lines: list) -> set[int]:
    if not should_skip_heading_line(row) or not (row.get("hocr_line_index") or "").isdigit():
        return set()
    start = int(row["hocr_line_index"])
    by_index = {line.index: line for line in lines}
    source_bbox = parse_bbox(row.get("source_bbox"))
    hocr_bbox = parse_bbox(row.get("hocr_bbox"))
    bboxes = [bbox for bbox in (source_bbox, hocr_bbox) if bbox]

    def source_is_covered(acc: str, expected_source: str) -> bool:
        if not expected_source:
            return True
        ratio = SequenceMatcher(None, expected_source, acc).ratio()
        return expected_source in acc or (len(acc) >= len(expected_source) and ratio >= 0.90) or (
            len(acc) >= len(expected_source) * 1.25 and ratio >= 0.82
        )

    def extend_to_source(selected: set[int]) -> set[int]:
        if not selected or not source:
            return selected
        ordered = sorted(selected)
        acc = normalize_heading_text(" ".join(by_index[line_index].text for line_index in ordered if line_index in by_index))
        if source_is_covered(acc, source):
            return extend_before_body_opener(selected, acc)
        previous_bottom = by_index[ordered[-1]].bbox[3] if by_index.get(ordered[-1]) and by_index[ordered[-1]].bbox else 0
        for line_index in range(ordered[-1] + 1, min(start + 4, max(by_index) + 1)):
            line = by_index.get(line_index)
            if line is None:
                break
            if re.match(r"^\s*\d+\.\s", line.text):
                break
            if line.bbox and previous_bottom and line.bbox[1] - previous_bottom > 90:
                break
            selected.add(line_index)
            previous_bottom = line.bbox[3] if line.bbox else previous_bottom
            acc = normalize_heading_text(f"{acc} {line.text}")
            if source_is_covered(acc, source):
                break
        return extend_before_body_opener(selected, acc)

    def extend_before_body_opener(selected: set[int], acc: str) -> set[int]:
        if not selected or not corrected_source or source_is_covered(acc, corrected_source):
            return selected
        next_index = max(selected) + 1
        next_line = by_index.get(next_index)
        following_line = by_index.get(next_index + 1)
        if next_line is None or following_line is None:
            return selected
        if re.match(r"^\s*\d+\.\s", next_line.text):
            return selected
        if not re.match(r"^\s*\d+\.\s", following_line.text):
            return selected
        next_acc = normalize_heading_text(f"{acc} {next_line.text}")
        if source_is_covered(next_acc, corrected_source):
            selected.add(next_index)
        return selected

    source = normalize_heading_text(row.get("detected_heading_text") or row_heading(row))
    corrected_source = normalize_heading_text(row_heading(row))
    if bboxes:
        selected = {
            line.index
            for line in lines
            if line.index >= max(1, start - 2) and any(line_overlaps_vertical_bbox(line, bbox) for bbox in bboxes)
        }
        if selected:
            return extend_to_source(selected)
    if not source or start not in by_index:
        return {start}
    selected: set[int] = set()
    acc = ""
    previous_bottom = 0
    for line_index in range(start, min(start + 4, max(by_index) + 1)):
        line = by_index.get(line_index)
        if line is None:
            break
        if selected and line.bbox and previous_bottom and line.bbox[1] - previous_bottom > 90:
            break
        selected.add(line_index)
        previous_bottom = line.bbox[3] if line.bbox else previous_bottom
        acc = normalize_heading_text(f"{acc} {line.text}")
        ratio = SequenceMatcher(None, source, acc).ratio()
        if source in acc:
            break
        if len(acc) >= len(source) and ratio >= 0.90:
            break
        if len(acc) >= len(source) * 1.25 and ratio >= 0.82:
            break
    return selected


def build(
    fresh_dir: Path,
    manifest_path: Path,
    structure_ledger: Path,
    text_correction_ledger: Path,
    line_role_overrides_path: Path,
    output_path: Path,
    manifest_output: Path,
    registry_output: Path,
) -> None:
    structure_rows = load_structure_ledger(structure_ledger)
    corrections = load_word_corrections(text_correction_ledger)
    line_role_overrides = load_line_role_overrides(line_role_overrides_path)
    pages, image_sizes, manifest = load_hocr_pages(fresh_dir, manifest_path)

    accepted_links = load_accepted_footnote_links(fresh_dir / "review" / "accepted_footnote_links.csv")
    accepted_blocks = load_accepted_footnote_blocks(fresh_dir / "review" / "accepted_footnote_blocks.csv")
    accepted_transcriptions = load_accepted_footnote_transcriptions(
        fresh_dir / "review" / "accepted_footnote_transcriptions.csv"
    )
    rejected_ref_ids = load_rejected_footnote_refs(fresh_dir / "review" / "rejected_footnote_candidates.csv")
    footnotes_by_page, linked_notes_by_word, footnote_rows = link_footnotes(
        pages,
        image_sizes,
        accepted_links,
        accepted_blocks,
        accepted_transcriptions,
        rejected_ref_ids,
    )
    write_footnote_report(fresh_dir, footnote_rows)
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
    sequence_regression_body_lines: set[tuple[int, int]] = set()
    for row in footnote_rows:
        if row.get("status") != "rejected-sequence-body-text":
            continue
        try:
            row_page = int(row.get("page") or "0")
            first_line = int(row.get("note_first_line") or "0")
            line_count = int(row.get("note_line_count") or "1")
        except ValueError:
            continue
        for offset in range(max(1, line_count)):
            sequence_regression_body_lines.add((row_page, first_line + offset))

    by_page: dict[int, list[dict[str, str]]] = defaultdict(list)
    heading_line_for: dict[tuple[int, int], dict[str, str]] = {}
    for row in sorted(structure_rows, key=event_sort_key):
        if not (row.get("pdf_page") or "").isdigit():
            continue
        page = int(row["pdf_page"])
        by_page[page].append(row)

    for page in pages:
        width, height = image_sizes[page.page]
        page_events = by_page.get(page.page, [])
        for row in page_events:
            line_indices = heading_line_indices(row, page.lines)
            if any((page.page, line_index) in heading_line_for for line_index in line_indices):
                row["_source_head_only"] = "1"
                first_section_y = min(
                    [
                        event_y(section)
                        for section in page_events
                        if section.get("source_type") == "section"
                        and section.get("chapter_id") == row.get("chapter_id")
                        and event_y(section) > event_y(row)
                    ],
                    default=0,
                )
                if first_section_y:
                    row["_deferred_event_y"] = str(first_section_y)
                continue
            for line_index in line_indices:
                heading_line_for[(page.page, line_index)] = row

    heading_corrections = build_heading_corrections(pages, heading_line_for, corrections)
    heading_latin_corrections = build_heading_latin_corrections(pages, heading_line_for, corrections)
    source_heading_corrections = build_source_heading_token_corrections(pages, heading_line_for, corrections)
    combined_corrections = merge_correction_layers(
        heading_latin_corrections,
        heading_corrections,
        source_heading_corrections,
        corrections,
    )

    builder = DiplomaticBuilder(
        structure_rows,
        combined_corrections,
        str(Path(manifest.get("local_image_root") or fresh_dir / "images")),
    )
    builder.initialize()

    for page in pages:
        width, height = image_sizes[page.page]
        page_events = by_page.get(page.page, [])
        page_events = sorted(page_events, key=event_sort_key)
        preopened = []
        for row in page_events:
            if open_before_page_break(row, page.lines, width, height):
                builder.open_event(row)
                preopened.append(row.get("row_id", ""))
        builder.emit_page_break(page.page)

        suppressed_note_line_ids = set()
        for block in footnotes_by_page.get(page.page, []):
            if not getattr(block, "status", "").startswith("unresolved"):
                continue
            if any((page.page, block_line.index) in heading_line_for for block_line in block.lines):
                suppressed_note_line_ids.update(id(block_line) for block_line in block.lines)

        for line in page.lines:
            for row in page_events:
                if row.get("row_id", "") in builder.opened_rows:
                    continue
                y = event_y(row)
                if not y or y < line_top(line):
                    builder.open_event(row)

            heading_row = heading_line_for.get((page.page, line.index))
            if heading_row:
                builder.open_event(heading_row)
                builder.emit_heading_line(heading_row, line, linked_notes_by_word)
                continue

            if id(line) in note_line_ids and id(line) not in suppressed_note_line_ids:
                block = note_by_first_line.get(id(line))
                if block is not None:
                    builder.emit_footnote(block)
                continue

            for row in page_events:
                if row.get("row_id", "") in builder.opened_rows:
                    continue
                y = event_y(row)
                if not y or y <= line_top(line) + 4:
                    builder.open_event(row)

            force_body = (page.page, line.index) in sequence_regression_body_lines or line_role_overrides.get(
                (page.page, line.index)
            ) == "body"
            builder.emit_line(line, width, height, linked_notes_by_word, force_body=force_body)

    tree = ET.ElementTree(builder.root)
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    write_manifest(manifest_output, manifest, structure_rows, output_path)
    write_private_registry(registry_output, output_path, manifest_output, fresh_dir)


def write_manifest(path: Path, fresh_manifest: dict, structure_rows: list[dict[str, str]], output_path: Path) -> None:
    rows = sorted(structure_rows, key=event_sort_key)
    book = ""
    chapter = ""
    back_start = min(
        [int(row["pdf_page"]) for row in rows if row.get("source_type") == "back" and row.get("pdf_page", "").isdigit()],
        default=10**9,
    )
    rows_by_page: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if (row.get("pdf_page") or "").isdigit():
            rows_by_page[int(row["pdf_page"])].append(row)

    manifest_pages = []
    for page in fresh_manifest.get("pages", []):
        pdf_page = int(page.get("pdf_page") or page.get("seq") or 0)
        for row in rows_by_page.get(pdf_page, []):
            if row.get("source_type") == "book":
                book = row.get("book_id", "")
                chapter = ""
            elif row.get("source_type") == "chapter":
                chapter = row.get("chapter_id", "")
            elif row.get("source_type") == "back":
                book = ""
                chapter = ""
        copied = dict(page)
        if pdf_page < back_start and not book:
            section = "front"
        elif pdf_page >= back_start:
            section = "back"
        else:
            section = f"book{book}" if book else "body"
        copied.update(
            {
                "section": section,
                "book": book,
                "chapter": chapter,
                "tei": repo_display_path(output_path),
                "xml_id": f"beck-fresh-diplomatic-p{pdf_page:04d}",
            }
        )
        manifest_pages.append(copied)

    payload = {
        **fresh_manifest,
        "source": "Beck 2020 fresh diplomatic EpiDoc from local PDF images, hOCR, and beck.xml structure evidence",
        "private": True,
        "diplomatic": True,
        "tei": repo_display_path(output_path),
        "total_pages": len(manifest_pages),
        "pages": manifest_pages,
        "sections": [
            {"id": "front", "label": "Front matter"},
            *[
                {
                    "id": f"book{book_n}",
                    "label": f"Book {book_n}",
                    "chapter_count": count,
                }
                for book_n, count in sorted(chapter_counts(structure_rows).items())
            ],
            {"id": "back", "label": "Back matter"},
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_private_registry(path: Path, output_path: Path, manifest_path: Path, fresh_dir: Path) -> None:
    local_image_root = repo_display_path(fresh_dir / "images").rstrip("/") + "/"
    payload = {
        "defaultEdition": "beck2020_fresh_diplomatic",
        "private": True,
        "editions": [
            {
                "id": "beck2020_fresh_diplomatic",
                "label": "Beck 2020 fresh diplomatic EpiDoc (private)",
                "tei": repo_display_path(output_path),
                "manifest": repo_display_path(manifest_path),
                "imageMode": "local",
                "localImageRoot": local_image_root,
                "imageLabelRoot": local_image_root,
                "sourceLabel": "Local private Beck PDF fresh diplomatic build",
                "licenseNote": "Private local review only. Do not add to the public registry without a publication-safe policy.",
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-dir", default=DEFAULT_FRESH_DIR)
    parser.add_argument("--fresh-manifest", default=DEFAULT_FRESH_MANIFEST)
    parser.add_argument("--structure-ledger", default=DEFAULT_STRUCTURE_LEDGER)
    parser.add_argument("--text-correction-ledger", default=DEFAULT_TEXT_CORRECTION_LEDGER)
    parser.add_argument("--line-role-overrides", default=DEFAULT_LINE_ROLE_OVERRIDES)
    parser.add_argument("--back-matter-triage-ledger", default=DEFAULT_BACK_MATTER_TRIAGE_LEDGER)
    parser.add_argument("--output", default=DEFAULT_DIPLOMATIC_OUTPUT)
    parser.add_argument("--manifest", default=DEFAULT_DIPLOMATIC_MANIFEST)
    parser.add_argument("--private-registry", default=DEFAULT_DIPLOMATIC_REGISTRY)
    args = parser.parse_args()

    try:
        if not Path(args.back_matter_triage_ledger).exists():
            print(f"ERROR: missing back-matter triage ledger {args.back_matter_triage_ledger}", file=sys.stderr)
            return 1
        build(
            Path(args.fresh_dir),
            Path(args.fresh_manifest),
            Path(args.structure_ledger),
            Path(args.text_correction_ledger),
            Path(args.line_role_overrides),
            Path(args.output),
            Path(args.manifest),
            Path(args.private_registry),
        )
    except (FileNotFoundError, ET.ParseError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {args.output}")
    print(f"Wrote {args.manifest}")
    print(f"Wrote {args.private_registry}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
