#!/usr/bin/env python3
"""Build a private, page-first Beck EpiDoc file and local review manifest."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

EXPECTED_PAGES = 710
EXPECTED_CHAPTERS = {1: 129, 2: 186, 3: 158, 4: 192, 5: 162}
DMM_TUID_RE = re.compile(r"^DiosMatMed:(\d+(?:\.\d+)*(?:_\d+)?)$")
BOOK_TUID_RE = re.compile(r"^DiosMatMed:(\d+)$")
CHAPTER_TUID_RE = re.compile(r"^DiosMatMed:(\d+\.\d+)$")
BAD_XML_ID_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")
SPACE_BEFORE_RE = re.compile(r"^[,.;:!?%)\]\u2019\u201d]$")
NO_SPACE_AFTER_RE = re.compile(r"[(\[\u2018\u201c]$")
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
ACCEPTED_STATUSES = {"accepted", "approved", "auto", "auto-accepted"}
FURNITURE_ROLES = {"header", "pageNum", "omit"}


@dataclass
class PageToken:
    source_id: str
    text: str
    page: int
    x: int | None
    y: int | None
    chapter: str
    context: str
    index: int


@dataclass
class AnchorCandidate:
    token_id: str
    page: int
    x: int | None
    y: int | None
    index: int
    token_text: str
    marker_text: str
    marker_label: str
    snippet: str = ""


@dataclass
class NoteInfo:
    source_id: str
    n: str
    page: int
    parent_tag: str
    parent_id: str
    role: str
    text: str
    y: int | None
    chapter: str
    order: int
    note_xml_id: str = ""
    ref_xml_id: str = ""
    target_note_id: str = ""
    paired_note_source_id: str = ""
    anchor_token_id: str = ""
    anchor_snippet: str = ""
    match_method: str = ""
    status: str = ""
    confidence: str = ""
    corresp_ref_ids: list[str] = field(default_factory=list)
    candidate_count: int = 0
    candidate_summary: str = ""
    evidence_status: str = ""


@dataclass(frozen=True)
class TokenCorrection:
    source_id: str
    corrected_text: str
    xml_lang: str = ""
    status: str = ""
    confidence: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class LineRole:
    source_id: str
    role: str
    place: str = ""
    text: str = ""
    status: str = ""
    confidence: str = ""
    evidence: str = ""


class BeckBuilder:
    def __init__(
        self,
        ocr_candidates_by_note: dict[str, list[dict[str, str]]] | None = None,
        token_corrections: dict[str, TokenCorrection] | None = None,
        line_roles: dict[str, LineRole] | None = None,
    ) -> None:
        self.id_counts: Counter[str] = Counter()
        self.raw_id_counts: Counter[str] = Counter()
        self.tuid_counts: Counter[str] = Counter()
        self.corresp_values: defaultdict[str, list[str]] = defaultdict(list)
        self.pages: list[dict[str, object]] = []
        self.line_n = 0
        self.current_page: dict[str, object] | None = None
        self.parent_by_obj: dict[int, ET.Element] = {}
        self.note_info_by_obj: dict[int, NoteInfo] = {}
        self.note_infos: list[NoteInfo] = []
        self.note_infos_by_id: dict[str, NoteInfo] = {}
        self.page_tokens: defaultdict[int, list[PageToken]] = defaultdict(list)
        self.anchor_candidates_by_page: defaultdict[int, list[AnchorCandidate]] = defaultdict(list)
        self.ocr_refs_by_token_id: defaultdict[str, list[NoteInfo]] = defaultdict(list)
        self.ocr_candidates_by_note = ocr_candidates_by_note or {}
        self.token_corrections = token_corrections or {}
        self.line_roles = line_roles or {}
        self.line_text_by_id: dict[str, str] = {}
        self.token_line_id: dict[str, str] = {}

    def build(self, source: Path) -> ET.ElementTree:
        src_root = ET.parse(source).getroot()
        self.inventory_source(src_root)
        for el in src_root.iter():
            if el.get("id"):
                self.raw_id_counts[el.get("id", "")] += 1
            if el.get("tuid"):
                self.tuid_counts[el.get("tuid", "")] += 1
            if el.get("corresp"):
                self.corresp_values[el.get("corresp", "")].append(el.get("tuid") or el.get("id") or el.tag)

        root = ET.Element(NS + "TEI")
        root.set(XML_ID, "beck2020")
        tei_header = ET.SubElement(root, NS + "teiHeader")
        file_desc = ET.SubElement(tei_header, NS + "fileDesc")
        title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
        ET.SubElement(title_stmt, NS + "title").text = "Beck 2020 private OCR ingest"
        pub_stmt = ET.SubElement(file_desc, NS + "publicationStmt")
        ET.SubElement(pub_stmt, NS + "p").text = "Private local review artifact; not for public publication."
        source_desc = ET.SubElement(file_desc, NS + "sourceDesc")
        ET.SubElement(source_desc, NS + "p").text = "Generated from local beck.xml OCR/XML source."
        encoding_desc = ET.SubElement(tei_header, NS + "encodingDesc")
        ET.SubElement(encoding_desc, NS + "p").text = (
            "Token bounding boxes are intentionally dropped from this public-shaped TEI. "
            "Source NER corresp values are preserved as evidence only."
        )

        text = ET.SubElement(root, NS + "text")
        body = ET.SubElement(text, NS + "body")
        src_text = src_root.find("text")
        if src_text is None:
            raise SystemExit(f"{source}: expected a top-level <text> element")

        self.plan_footnotes()
        self.convert_text(src_text, body)
        return ET.ElementTree(root)

    def inventory_source(self, src_root: ET.Element) -> None:
        for parent in src_root.iter():
            for child in list(parent):
                self.parent_by_obj[id(child)] = parent

        state = {"page": 0, "book": "", "chapter": "", "section": "front", "line_id": ""}
        note_order = 0

        def walk(el: ET.Element, in_note: bool = False) -> None:
            nonlocal note_order
            tag = local_name(el.tag)
            previous = state.copy()

            if tag == "pb":
                state["page"] = int(el.get("seq") or state["page"] or 0)
                state["line_id"] = ""
            elif tag == "lb":
                state["line_id"] = el.get("id", "")
            elif tag == "div":
                tuid = el.get("tuid", "")
                book_match = BOOK_TUID_RE.match(tuid)
                chapter_match = CHAPTER_TUID_RE.match(tuid)
                if book_match:
                    state["book"] = book_match.group(1)
                    state["chapter"] = ""
                    state["section"] = f"book{state['book']}"
                elif chapter_match:
                    state["book"] = chapter_match.group(1).split(".", 1)[0]
                    state["chapter"] = chapter_match.group(1)
                    state["section"] = f"book{state['book']}"
                elif el.get("n"):
                    state["section"] = slug(el.get("n", ""))

            if tag == "tok" and not in_note:
                token_id = el.get("id", "")
                token_text = token_full_text(el)
                if token_id and token_text:
                    if state.get("line_id"):
                        self.token_line_id[token_id] = str(state["line_id"])
                        current = self.line_text_by_id.get(str(state["line_id"]), "")
                        self.line_text_by_id[str(state["line_id"])] = normalize_ws(f"{current} {token_text}")
                    page = int(state["page"] or 0)
                    tokens = self.page_tokens[page]
                    tokens.append(
                        PageToken(
                            source_id=token_id,
                            text=token_text,
                            page=page,
                            x=bbox_x(el.get("bbox")),
                            y=bbox_y(el.get("bbox")),
                            chapter=str(state.get("chapter") or ""),
                            context=token_text,
                            index=len(tokens),
                        )
                    )

            if tag == "note":
                note_order += 1
                parent = self.parent_by_obj.get(id(el))
                parent_tag = local_name(parent.tag) if parent is not None else ""
                parent_id = parent.get("id", "") if parent is not None else ""
                text = normalize_ws(" ".join(el.itertext()))
                role = "bottom"
                if parent_tag in {"tok", "head", "p"}:
                    role = "inline-text" if text else "inline-marker"
                elif text and parent_tag == "div" and is_between_token_siblings(el, parent):
                    role = "inline-text"
                elif not text:
                    role = "empty-bottom"
                source_id = el.get("id") or f"note-{note_order}"
                info = NoteInfo(
                    source_id=source_id,
                    n=(el.get("n") or "").strip(),
                    page=int(state["page"] or 0),
                    parent_tag=parent_tag,
                    parent_id=parent_id,
                    role=role,
                    text=text,
                    y=first_note_y(el, parent),
                    chapter=str(state.get("chapter") or ""),
                    order=note_order,
                    note_xml_id=stable_xml_id("beck-fn", source_id),
                    ref_xml_id=stable_xml_id("beck-ref", source_id),
                )
                self.note_info_by_obj[id(el)] = info
                self.note_infos.append(info)
                self.note_infos_by_id[source_id] = info
                in_note = True

            for child in list(el):
                walk(child, in_note=in_note)

            if tag == "div":
                latest_page = state["page"]
                state.update(previous)
                state["page"] = latest_page

        walk(src_root)

    def plan_footnotes(self) -> None:
        self.inventory_anchor_candidates()
        markers_by_page_n: defaultdict[tuple[int, str], list[NoteInfo]] = defaultdict(list)
        for info in self.note_infos:
            if info.role == "inline-marker" and info.n:
                markers_by_page_n[(info.page, info.n)].append(info)

        used_markers: set[str] = set()
        used_anchor_tokens: set[str] = set()
        for info in self.note_infos:
            if info.role not in {"bottom", "empty-bottom"}:
                continue
            info.note_xml_id = stable_xml_id("beck-fn", info.source_id)
            if not info.text:
                info.status = "unresolved-empty-source-note"
                info.match_method = "none"
                info.confidence = "0.00"
                continue
            if info.n:
                markers = [m for m in markers_by_page_n.get((info.page, info.n), []) if m.source_id not in used_markers]
                if len(markers) == 1:
                    marker = markers[0]
                    used_markers.add(marker.source_id)
                    marker.target_note_id = info.note_xml_id
                    marker.paired_note_source_id = info.source_id
                    marker.match_method = "explicit-same-page-n"
                    marker.status = "resolved"
                    marker.confidence = "1.00"
                    info.corresp_ref_ids.append(marker.ref_xml_id)
                    info.match_method = "explicit-same-page-n"
                    info.status = "resolved"
                    info.confidence = "1.00"
                    info.anchor_snippet = self.source_context_for_parent(marker.parent_id)
                    continue

                exact = self.find_exact_label_anchor(info, used_anchor_tokens)
                if exact is not None:
                    self.link_token_anchor(info, exact, "same-page-label-marker", "0.95")
                    used_anchor_tokens.add(exact.token_id)
                    continue

            info.status = "unresolved-anchor"
            info.match_method = "none"
            info.confidence = "0.00"

        self.resolve_unambiguous_page_sequences(used_anchor_tokens)
        for info in self.note_infos:
            if info.status == "unresolved-anchor":
                self.record_candidate_evidence(info, used_anchor_tokens)

        for info in self.note_infos:
            if info.role == "inline-text":
                info.target_note_id = info.note_xml_id
                info.corresp_ref_ids.append(info.ref_xml_id)
                info.match_method = "inline-text-note"
                info.status = "resolved"
                info.confidence = "1.00"
                info.anchor_snippet = self.source_context_for_parent(info.parent_id)
            elif info.role == "inline-marker" and not info.target_note_id:
                info.target_note_id = info.note_xml_id
                info.corresp_ref_ids.append(info.ref_xml_id)
                info.match_method = "inline-marker-without-source-body"
                info.status = "missing-source-note-body"
                info.confidence = "1.00"
                info.anchor_snippet = self.source_context_for_parent(info.parent_id)

    def inventory_anchor_candidates(self) -> None:
        for page, tokens in self.page_tokens.items():
            candidates: list[AnchorCandidate] = []
            for token in tokens:
                marker = marker_from_token(token.text)
                if not marker:
                    continue
                marker_text, marker_label = marker
                candidates.append(
                    AnchorCandidate(
                        token_id=token.source_id,
                        page=page,
                        x=token.x,
                        y=token.y,
                        index=token.index,
                        token_text=token.text,
                        marker_text=marker_text,
                        marker_label=marker_label,
                        snippet=self.source_context_for_parent(token.source_id),
                    )
                )
            self.anchor_candidates_by_page[page] = candidates

    def link_token_anchor(self, info: NoteInfo, candidate: AnchorCandidate, method: str, confidence: str) -> None:
        info.ref_xml_id = stable_xml_id("beck-ref", info.source_id)
        info.corresp_ref_ids.append(info.ref_xml_id)
        info.anchor_token_id = candidate.token_id
        info.anchor_snippet = candidate.snippet
        info.match_method = method
        info.status = "resolved"
        info.confidence = confidence
        info.candidate_count = 1
        info.candidate_summary = format_candidate(candidate)
        info.evidence_status = "auto-linked"
        self.ocr_refs_by_token_id[candidate.token_id].append(info)

    def find_exact_label_anchor(self, info: NoteInfo, used_anchor_tokens: set[str]) -> AnchorCandidate | None:
        if not info.n or info.page <= 0:
            return None
        normalized_note = normalize_marker(info.n)
        if not normalized_note:
            return None
        candidates = [
            candidate
            for candidate in self.page_anchor_candidates(info, used_anchor_tokens)
            if normalize_marker(candidate.marker_label) == normalized_note
        ]
        if len(candidates) != 1:
            return None
        return candidates[0]

    def resolve_unambiguous_page_sequences(self, used_anchor_tokens: set[str]) -> None:
        notes_by_page: defaultdict[int, list[NoteInfo]] = defaultdict(list)
        for info in self.note_infos:
            if info.status == "unresolved-anchor" and info.role in {"bottom", "empty-bottom"} and info.text:
                notes_by_page[info.page].append(info)
        for page, notes in notes_by_page.items():
            notes.sort(key=lambda item: ((item.y if item.y is not None else 10**9), item.order))
            page_candidates = self.page_anchor_candidates_for_notes(notes, used_anchor_tokens)
            if not notes or len(notes) != len(page_candidates):
                continue
            if len({candidate.token_id for candidate in page_candidates}) != len(page_candidates):
                continue
            for info, candidate in zip(notes, page_candidates):
                self.link_token_anchor(info, candidate, "page-order-marker-sequence", "0.90")
                used_anchor_tokens.add(candidate.token_id)

    def page_anchor_candidates_for_notes(
        self,
        notes: list[NoteInfo],
        used_anchor_tokens: set[str],
    ) -> list[AnchorCandidate]:
        if not notes:
            return []
        page = notes[0].page
        first_note_y = min((info.y for info in notes if info.y is not None), default=None)
        candidates: list[AnchorCandidate] = []
        for candidate in self.anchor_candidates_by_page.get(page, []):
            if candidate.token_id in used_anchor_tokens:
                continue
            if first_note_y is not None and candidate.y is not None and candidate.y >= first_note_y - 8:
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda item: ((item.y if item.y is not None else 10**9), item.index))
        return candidates

    def page_anchor_candidates(self, info: NoteInfo, used_anchor_tokens: set[str]) -> list[AnchorCandidate]:
        candidates = []
        for candidate in self.anchor_candidates_by_page.get(info.page, []):
            if candidate.token_id in used_anchor_tokens:
                continue
            if info.y is not None and candidate.y is not None and candidate.y >= info.y - 8:
                continue
            candidates.append(candidate)
        candidates.sort(key=lambda item: ((item.y if item.y is not None else 10**9), item.index))
        return candidates

    def record_candidate_evidence(self, info: NoteInfo, used_anchor_tokens: set[str]) -> None:
        candidates = self.page_anchor_candidates(info, used_anchor_tokens)
        info.candidate_count = len(candidates)
        info.candidate_summary = " | ".join(format_candidate(candidate) for candidate in candidates[:8])
        if len(candidates) > 8:
            info.candidate_summary += f" | +{len(candidates) - 8} more"
        info.evidence_status = "candidate-set" if candidates else "no-candidate-found"
        ocr_rows = [
            row
            for row in self.ocr_candidates_by_note.get(info.source_id, [])
            if row.get("evidence_status") == "ocr-candidate"
        ]
        if ocr_rows:
            ocr_summary = " | ".join(format_ocr_candidate(row) for row in ocr_rows[:8])
            if info.candidate_summary:
                info.candidate_summary = f"{info.candidate_summary} | OCR: {ocr_summary}"
            else:
                info.candidate_summary = f"OCR: {ocr_summary}"
            info.evidence_status = "candidate-set"
            info.candidate_count += len(ocr_rows)

    def source_context_for_parent(self, source_id: str) -> str:
        if not source_id:
            return ""
        for tokens in self.page_tokens.values():
            for idx, token in enumerate(tokens):
                if token.source_id == source_id:
                    start = max(0, idx - 4)
                    end = min(len(tokens), idx + 5)
                    return normalize_ws(" ".join(t.text for t in tokens[start:end]))
        return ""

    def convert_text(self, src_text: ET.Element, body: ET.Element) -> None:
        context = {"book": "", "chapter": "", "section": "front"}
        text_buffer: list[str] = []
        text_context: dict[str, object] = context.copy()
        text_context["_text_buffer"] = text_buffer
        current_book_el: ET.Element | None = None
        current_book_n = ""

        for child in list(src_text):
            tag = local_name(child.tag)
            tuid = child.get("tuid", "")
            book_match = BOOK_TUID_RE.match(tuid) if tag == "div" else None
            chapter_match = CHAPTER_TUID_RE.match(tuid) if tag == "div" else None
            if book_match:
                flush_text_buffer(body, text_buffer)
                current_book_n = book_match.group(1)
                context = {"book": current_book_n, "chapter": "", "section": f"book{current_book_n}"}
                text_context = context.copy()
                text_context["_text_buffer"] = text_buffer
                current_book_el = self.convert_element(child, context)
                if current_book_el is not None:
                    body.append(current_book_el)
                continue

            if chapter_match and current_book_el is not None and chapter_match.group(1).split(".", 1)[0] == current_book_n:
                flush_text_buffer(current_book_el, text_buffer)
                chapter_context = {"book": current_book_n, "chapter": chapter_match.group(1), "section": f"book{current_book_n}"}
                converted = self.convert_element(child, chapter_context)
                if converted is not None:
                    current_book_el.append(converted)
                continue

            if tag == "div" and current_book_el is not None and not tuid:
                current_book_el = None
                current_book_n = ""
                context = {"book": "", "chapter": "", "section": slug(child.get("n", "") or "back")}
                text_context = context.copy()
                text_context["_text_buffer"] = text_buffer

            target = current_book_el if current_book_el is not None else body
            converted = self.convert_element_with_text_buffer(child, text_context)
            flush_text_buffer(target, text_buffer)
            if converted is not None:
                target.append(converted)
            append_pending_elements(target, text_context)
            if child.tail and child.tail.strip():
                append_source_text(target, child.tail.strip())

        flush_text_buffer(current_book_el if current_book_el is not None else body, text_buffer)

    def convert_children(self, src_parent: ET.Element, dst_parent: ET.Element, context: dict[str, str]) -> None:
        text_buffer: list[str] = []
        text_context: dict[str, object] = context.copy()
        text_context["_text_buffer"] = text_buffer
        if src_parent.text and src_parent.text.strip():
            append_source_text(dst_parent, src_parent.text.strip())
        for child in list(src_parent):
            converted = self.convert_element_with_text_buffer(child, text_context)
            flush_text_buffer(dst_parent, text_buffer)
            if converted is not None:
                dst_parent.append(converted)
            append_pending_elements(dst_parent, text_context)
            if child.tail and child.tail.strip():
                append_source_text(dst_parent, child.tail.strip())
        flush_text_buffer(dst_parent, text_buffer)

    def convert_element(self, src: ET.Element, context: dict[str, str]) -> ET.Element | None:
        tag = local_name(src.tag)
        if tag == "pb":
            return self.convert_pb(src, context)
        if tag == "lb":
            return self.convert_lb(src)
        if tag == "tok":
            return self.convert_token_element(src, context)
        if tag == "note":
            return self.convert_note(src, context)

        if tag == "div":
            out, next_context = self.convert_div(src, context)
        elif tag == "term":
            out = self.new_element("term", src, keep=("corresp", "type", "subtype", "n"))
            next_context = context.copy()
        elif tag in {"head", "p", "ab", "seg", "list", "item", "milestone"}:
            out = self.new_element(tag, src, keep=("type", "subtype", "n", "unit", "corresp"))
            next_context = context.copy()
        else:
            out = self.new_element("seg", src, keep=("type", "subtype", "n", "corresp"))
            out.set("subtype", tag)
            next_context = context.copy()

        text_buffer: list[str] = []
        text_context: dict[str, object] = next_context.copy()
        text_context["_text_buffer"] = text_buffer  # type: ignore[assignment]
        if src.text and src.text.strip():
            append_source_text(out, src.text.strip())
        for child in list(src):
            child_el = self.convert_element_with_text_buffer(child, text_context)
            flush_text_buffer(out, text_buffer)
            if child_el is not None:
                out.append(child_el)
            append_pending_elements(out, text_context)
            if child.tail and child.tail.strip():
                append_source_text(out, child.tail.strip())
        flush_text_buffer(out, text_buffer)
        return out

    def convert_element_with_text_buffer(self, src: ET.Element, context: dict[str, object]) -> ET.Element | None:
        tag = local_name(src.tag)
        if tag == "lb" and context.get("_in_note"):
            line_ref = context.setdefault("_note_line_n", [0])
            assert isinstance(line_ref, list)
            line_ref[0] += 1
            return self.convert_lb(src, count_line=False, n=line_ref[0])
        if tag == "lb":
            line_id = src.get("id", "")
            context["_current_line_id"] = line_id
            role = self.line_roles.get(line_id)
            context["_current_line_role"] = role.role if role else "body"
            if role and role.role in FURNITURE_ROLES:
                return self.convert_line_furniture(src, role)
        if tag == "note":
            return self.convert_note(src, context)
        if tag == "tok":
            if self.should_skip_token(src, context):
                return None
            text = self.token_text(src)
            has_note_child = any(local_name(child.tag) == "note" for child in list(src))
            has_ocr_ref = bool(src.get("id") and src.get("id") in self.ocr_refs_by_token_id)
            if text and GREEK_RE.search(text):
                return self.convert_token_element(src, context)
            if has_note_child or has_ocr_ref:
                return self.convert_token_element(src, context)
            if text:
                context.setdefault("_text_buffer", []).append(text)  # type: ignore[union-attr]
            return None
        return self.convert_element(src, context)  # type: ignore[arg-type]

    def convert_token_element(self, src: ET.Element, context: dict[str, object] | None = None) -> ET.Element | None:
        if context is not None and self.should_skip_token(src, context):
            return None
        text = self.token_text(src)
        if not text and not list(src):
            return None
        if GREEK_RE.search(self.token_full_text(src)):
            out = ET.Element(NS + "foreign")
            out.set(XML_LANG, "grc")
        else:
            out = ET.Element(NS + "w")
        if src.get("id"):
            out.set(XML_ID, self.xml_id(src.get("id", "")))
        if text:
            out.text = text
        if context is None:
            context = {}
        for child in list(src):
            child_el = self.convert_element_with_text_buffer(child, context)
            if child_el is not None:
                out.append(child_el)
            if child.tail and child.tail.strip():
                append_text(out, child.tail.strip())
        for info in self.ocr_refs_by_token_id.get(src.get("id", ""), []):
            out.append(self.make_ref(info, info.note_xml_id))
        return out

    def token_text(self, src: ET.Element) -> str:
        token_id = src.get("id", "")
        correction = self.token_corrections.get(token_id)
        if correction:
            return correction.corrected_text.strip()
        return (src.text or "").strip()

    def token_full_text(self, src: ET.Element) -> str:
        token_id = src.get("id", "")
        correction = self.token_corrections.get(token_id)
        if correction:
            return correction.corrected_text.strip()
        return token_full_text(src)

    def should_skip_token(self, src: ET.Element, context: dict[str, object]) -> bool:
        token_id = src.get("id", "")
        line_id = self.token_line_id.get(token_id) or str(context.get("_current_line_id") or "")
        role = self.line_roles.get(line_id)
        return bool(role and role.role in FURNITURE_ROLES)

    def convert_line_furniture(self, src: ET.Element, role: LineRole) -> ET.Element | None:
        if role.role == "omit":
            return None
        fw = ET.Element(NS + "fw")
        fw.set("type", "pageNum" if role.role == "pageNum" else "header")
        fw.set("place", role.place or ("top-outer" if role.role == "pageNum" else "top"))
        fw.set(XML_ID, self.xml_id(f"fw-{src.get('id') or role.source_id}"))
        text = role.text or self.line_text_by_id.get(src.get("id", ""), "")
        if text:
            fw.text = text
        return fw

    def convert_note(self, src: ET.Element, context: dict[str, object]) -> ET.Element | None:
        info = self.note_info_by_obj.get(id(src))
        if info is None:
            return None
        if info.role == "inline-marker":
            ref = self.make_ref(info, info.target_note_id or info.note_xml_id)
            if info.status == "missing-source-note-body":
                pending_note = self.make_footnote_note(info, subtype="missing-source-note-body")
                context.setdefault("_pending_elements", []).append(pending_note)  # type: ignore[union-attr]
            return ref
        if info.role == "inline-text":
            ref = self.make_ref(info, info.note_xml_id)
            pending_note = self.make_footnote_note(info, source=src)
            context.setdefault("_pending_elements", []).append(pending_note)  # type: ignore[union-attr]
            return ref
        if info.role in {"bottom", "empty-bottom"}:
            subtype = "unresolved-anchor" if info.status.startswith("unresolved") else ""
            return self.make_footnote_note(info, source=src, subtype=subtype)
        return None

    def make_ref(self, info: NoteInfo, target_note_id: str) -> ET.Element:
        ref = ET.Element(NS + "ref")
        ref.set("type", "footnote-ref")
        ref.set(XML_ID, info.ref_xml_id)
        ref.set("target", f"#{target_note_id}")
        ref.text = info.n or str(info.order)
        return ref

    def make_footnote_note(self, info: NoteInfo, source: ET.Element | None = None, subtype: str = "") -> ET.Element:
        note = ET.Element(NS + "note")
        note.set("type", "footnote")
        note.set(XML_ID, info.note_xml_id)
        note.set("n", info.n or str(info.order))
        note.set("place", "bottom")
        if subtype:
            note.set("subtype", subtype)
        if info.corresp_ref_ids:
            note.set("corresp", " ".join(f"#{ref_id}" for ref_id in info.corresp_ref_ids))
        if source is not None:
            self.convert_note_body(source, note, info)
        return note

    def convert_note_body(self, src: ET.Element, dst: ET.Element, info: NoteInfo) -> None:
        text_buffer: list[str] = []
        note_context: dict[str, object] = {
            "_text_buffer": text_buffer,
            "_in_note": True,
            "_note_line_n": [0],
        }
        strip_label = bool(info.n)
        if src.text and src.text.strip():
            stripped = strip_note_label_from_text(src.text, info.n) if strip_label else src.text
            if stripped.strip():
                append_source_text(dst, stripped.strip())
            if stripped != src.text:
                strip_label = False
        for child in list(src):
            if strip_label and local_name(child.tag) == "tok":
                token_text = token_full_text(child)
                stripped = strip_note_label_from_text(token_text, info.n)
                if stripped != token_text:
                    if stripped.strip():
                        append_source_text(dst, stripped.strip())
                    strip_label = False
                    continue
                if is_note_label_token(token_text, info.n):
                    strip_label = False
                    continue
            child_el = self.convert_element_with_text_buffer(child, note_context)
            flush_text_buffer(dst, text_buffer)
            if child_el is not None:
                dst.append(child_el)
            append_pending_elements(dst, note_context)
            if child.tail and child.tail.strip():
                append_source_text(dst, child.tail.strip())
        flush_text_buffer(dst, text_buffer)

    def convert_div(self, src: ET.Element, context: dict[str, str]) -> tuple[ET.Element, dict[str, str]]:
        tuid = src.get("tuid", "")
        src_type = src.get("type", "")
        next_context = context.copy()

        if src_type == "footnote":
            out = self.new_element("div", src, keep=("n", "corresp"))
            out.set("type", "notes")
            out.set("subtype", "footnote-block")
            return out, next_context

        out = self.new_element("div", src, keep=("corresp",))
        book_match = BOOK_TUID_RE.match(tuid)
        chapter_match = CHAPTER_TUID_RE.match(tuid)
        dmm_match = DMM_TUID_RE.match(tuid)

        out.set("type", "textpart")
        if book_match:
            n = book_match.group(1)
            out.set("subtype", "book")
            out.set("n", n)
            next_context.update({"book": n, "chapter": "", "section": f"book{n}"})
            self.update_current_page(book=n, section=f"book{n}")
        elif chapter_match:
            n = chapter_match.group(1)
            out.set("subtype", "chapter")
            out.set("n", n)
            next_context.update({"book": n.split(".", 1)[0], "chapter": n, "section": f"book{n.split('.', 1)[0]}"})
            self.update_current_page(chapter=n)
        elif dmm_match:
            n = dmm_match.group(1)
            out.set("subtype", "section")
            out.set("n", n)
        else:
            out.set("subtype", "source-section")
            if src.get("n"):
                out.set("n", src.get("n", ""))
                next_context["section"] = slug(src.get("n", ""))
                self.update_current_page(section=next_context["section"])

        return out, next_context

    def convert_pb(self, src: ET.Element, context: dict[str, str]) -> ET.Element:
        seq = int(src.get("seq") or len(self.pages) + 1)
        facs = src.get("facs") or f"beck-{seq}.jpg"
        self.line_n = 0
        out = ET.Element(NS + "pb")
        out.set(XML_ID, self.xml_id(src.get("id") or f"pb-{seq}"))
        out.set("n", str(seq))
        out.set("facs", facs)
        page = {
            "page_index": len(self.pages),
            "pdf_page": seq,
            "seq": seq,
            "book_page": src.get("n") or "",
            "section": context.get("section") or "",
            "book": context.get("book") or "",
            "chapter": context.get("chapter") or "",
            "tei_facs": facs,
            "facs": facs,
            "image": facs,
            "xml_id": out.get(XML_ID),
        }
        self.pages.append(page)
        self.current_page = page
        return out

    def convert_lb(self, src: ET.Element, count_line: bool = True, n: int | None = None) -> ET.Element:
        if count_line:
            self.line_n += 1
            line_n = self.line_n
        else:
            line_n = n or 1
        out = ET.Element(NS + "lb")
        out.set(XML_ID, self.xml_id(src.get("id") or f"lb-{len(self.pages)}-{self.line_n}"))
        out.set("n", str(line_n))
        return out

    def new_element(self, tag: str, src: ET.Element, keep: tuple[str, ...]) -> ET.Element:
        out = ET.Element(NS + tag)
        if src.get("id"):
            out.set(XML_ID, self.xml_id(src.get("id", "")))
        for attr in keep:
            value = src.get(attr)
            if value:
                out.set(attr, value)
        return out

    def xml_id(self, raw: str) -> str:
        base = "beck-" + BAD_XML_ID_CHARS_RE.sub("-", raw.strip())
        base = re.sub(r"-+", "-", base).strip("-")
        if not re.match(r"^[A-Za-z_]", base):
            base = f"beck-{base}"
        self.id_counts[base] += 1
        if self.id_counts[base] == 1:
            return base
        return f"{base}-{self.id_counts[base]}"

    def update_current_page(self, **values: str) -> None:
        if not self.current_page:
            return
        for key, value in values.items():
            if value:
                self.current_page[key] = value

    def manifest(self) -> dict[str, object]:
        sections = Counter(str(page.get("section") or "unsectioned") for page in self.pages)
        return {
            "total_pages": len(self.pages),
            "source": "Beck 2020 private OCR/XML ingest",
            "private": True,
            "image_mode": "local",
            "local_image_root": "editions/beck2020/page_images/",
            "pages": self.pages,
            "sections": {name: {"page_count": count} for name, count in sorted(sections.items())},
        }

    def audit_markdown(self, validation: list[str]) -> str:
        duplicate_ids = {key: count for key, count in self.raw_id_counts.items() if count > 1}
        duplicate_tuids = {key: count for key, count in self.tuid_counts.items() if count > 1}
        bad_corresp = []
        for value, holders in sorted(self.corresp_values.items()):
            match = re.search(r"DMM(\d)(\d+)$", value)
            for holder in holders:
                tuid_match = re.search(r"DiosMatMed:(\d+)\.(\d+)$", holder)
                if match and tuid_match:
                    expected = f"DMM{tuid_match.group(1)}{int(tuid_match.group(2)):03d}"
                    if value.endswith(expected):
                        continue
                    bad_corresp.append((value, holder, expected))

        lines = [
            "# Beck Private Ingest Audit",
            "",
            "Generated from `beck.xml`. This report records inherited source issues; the generated TEI keeps the source evidence but assigns unique `xml:id` values.",
            "",
            "## Validation",
        ]
        if validation:
            lines.extend(f"- {issue}" for issue in validation)
        else:
            lines.append("- No validation issues found.")

        lines.extend(["", "## Duplicate Raw IDs"])
        for key in sorted(duplicate_ids):
            lines.append(f"- `{key}`: {duplicate_ids[key]}")
        if not duplicate_ids:
            lines.append("- None.")

        lines.extend(["", "## Duplicate TUIDs"])
        for key in sorted(duplicate_tuids):
            lines.append(f"- `{key}`: {duplicate_tuids[key]}")
        if not duplicate_tuids:
            lines.append("- None.")

        lines.extend(["", "## Suspicious Corresp Values"])
        for value, holder, expected in bad_corresp:
            lines.append(f"- `{value}` on `{holder}`; expected-looking value is `{expected}`.")
        if not bad_corresp:
            lines.append("- None detected by DMM numeric heuristic.")

        return "\n".join(lines) + "\n"

    def footnote_audit_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for info in self.note_infos:
            rows.append(
                {
                    "source_id": info.source_id,
                    "n": info.n,
                    "page": str(info.page or ""),
                    "source_parent": info.parent_tag,
                    "source_parent_id": info.parent_id,
                    "role": info.role,
                    "note_xml_id": info.note_xml_id,
                    "ref_xml_id": info.ref_xml_id,
                    "target_note_id": info.target_note_id or info.note_xml_id,
                    "paired_note_source_id": info.paired_note_source_id,
                    "match_method": info.match_method,
                    "confidence": info.confidence,
                    "status": info.status,
                    "anchor_token_id": info.anchor_token_id,
                    "anchor_snippet": info.anchor_snippet,
                    "candidate_count": str(info.candidate_count),
                    "evidence_status": info.evidence_status,
                    "candidate_summary": info.candidate_summary,
                    "note_excerpt": info.text[:180],
                }
            )
        return rows

    def footnote_audit_markdown(self, validation: list[str]) -> str:
        status_counts = Counter(info.status or "unknown" for info in self.note_infos)
        role_counts = Counter(info.role for info in self.note_infos)
        unresolved = [info for info in self.note_infos if (info.status or "").startswith("unresolved")]
        missing_body = [info for info in self.note_infos if info.status == "missing-source-note-body"]
        lines = [
            "# Beck Footnote Audit",
            "",
            f"- Source `<note>` elements inventoried: {len(self.note_infos)}",
            f"- Generated footnote refs: {sum(1 for info in self.note_infos if info.ref_xml_id and (info.role.startswith('inline') or info.anchor_token_id))}",
            f"- Explicitly unresolved notes: {len(unresolved)}",
            f"- Empty inline markers without source note body: {len(missing_body)}",
            "",
            "## Status Counts",
        ]
        for status, count in sorted(status_counts.items()):
            lines.append(f"- `{status}`: {count}")
        lines.extend(["", "## Role Counts"])
        for role, count in sorted(role_counts.items()):
            lines.append(f"- `{role}`: {count}")
        lines.extend(["", "## Validation"])
        if validation:
            lines.extend(f"- {issue}" for issue in validation)
        else:
            lines.append("- No generator validation issues found.")
        lines.extend(["", "## Unresolved Anchor Notes"])
        if unresolved:
            for info in unresolved:
                label = info.n or str(info.order)
                excerpt = info.text[:100] or "(empty)"
                lines.append(f"- `{info.source_id}` n=`{label}` page `{info.page}`: {excerpt}")
        else:
            lines.append("- None.")
        return "\n".join(lines) + "\n"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def slug(value: str) -> str:
    text = BAD_XML_ID_CHARS_RE.sub("-", value.lower()).strip("-")
    return text or "section"


def stable_xml_id(prefix: str, raw: str) -> str:
    base = f"{prefix}-{BAD_XML_ID_CHARS_RE.sub('-', raw.strip())}"
    base = re.sub(r"-+", "-", base).strip("-")
    if not re.match(r"^[A-Za-z_]", base):
        base = f"beck-{base}"
    return base


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def bbox_y(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split()
    if len(parts) < 2:
        return None
    try:
        return int(float(parts[1]))
    except ValueError:
        return None


def bbox_x(value: str | None) -> int | None:
    if not value:
        return None
    parts = value.split()
    if not parts:
        return None
    try:
        return int(float(parts[0]))
    except ValueError:
        return None


def marker_from_token(text: str) -> tuple[str, str] | None:
    raw = text.strip()
    if not raw:
        return None
    if re.fullmatch(r"['\u2018\u2019\u201c\u201d]+", raw):
        return None
    numeric = re.search(r"[\^*'\u2019\u201d]+(\d{1,3})$", raw)
    if numeric:
        marker = raw[numeric.start() :]
        return marker, numeric.group(1)
    if "^" in raw or "*" in raw:
        marker_match = re.search(r"[\^*][\^*'\u2019\u201d]*", raw)
        if marker_match:
            marker = marker_match.group(0)
            return marker, normalize_marker(marker)
    quote_marker = re.search(r"(?<![A-Za-z])['\u2019\u201d]{2,}$", raw)
    if quote_marker:
        marker = quote_marker.group(0)
        return marker, normalize_marker(marker)
    return None


def format_candidate(candidate: AnchorCandidate) -> str:
    x = "" if candidate.x is None else str(candidate.x)
    y = "" if candidate.y is None else str(candidate.y)
    return (
        f"{candidate.token_id}@{x},{y}:"
        f"{candidate.token_text}[marker={candidate.marker_text}]"
        f" :: {candidate.snippet[:100]}"
    )


def format_ocr_candidate(row: dict[str, str]) -> str:
    token_id = row.get("source_token_id") or "unmapped"
    text = row.get("source_token_text") or row.get("ocr_text") or ""
    conf = row.get("conf") or ""
    left = row.get("left") or ""
    top = row.get("top") or ""
    return f"{token_id}@{left},{top}:{text}[ocr={row.get('ocr_text') or ''};conf={conf}]"


def first_note_y(note: ET.Element, parent: ET.Element | None) -> int | None:
    for el in note.iter():
        y = bbox_y(el.get("bbox"))
        if y is not None:
            return y
    if parent is not None:
        return bbox_y(parent.get("bbox"))
    return None


def is_between_token_siblings(el: ET.Element, parent: ET.Element | None) -> bool:
    if parent is None:
        return False
    children = list(parent)
    try:
        index = children.index(el)
    except ValueError:
        return False
    if index == 0 or index + 1 >= len(children):
        return False
    return local_name(children[index - 1].tag) == "tok" and local_name(children[index + 1].tag) == "tok"


def token_full_text(tok: ET.Element) -> str:
    return normalize_ws("".join(tok.itertext()))


def normalize_marker(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z*^]+", "", text.strip())


def is_note_label_token(text: str, label: str) -> bool:
    if not label:
        return False
    return normalize_marker(text).lstrip("^") == normalize_marker(label).lstrip("^")


def strip_note_label_from_text(text: str, label: str) -> str:
    if not label:
        return text
    return re.sub(rf"^\s*{re.escape(label)}\s+", "", text, count=1)


def append_pending_elements(parent: ET.Element, context: dict[str, object]) -> None:
    pending = context.get("_pending_elements")
    if not pending:
        return
    assert isinstance(pending, list)
    while pending:
        element = pending.pop(0)
        if isinstance(element, ET.Element):
            parent.append(element)


def flush_text_buffer(parent: ET.Element, buffer: list[str]) -> None:
    for token in buffer:
        append_text(parent, token)
    buffer.clear()


def append_text(parent: ET.Element, text: str) -> None:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return
    if len(parent):
        last = parent[-1]
        if not last.tail and local_name(last.tag) not in {"lb", "pb", "milestone"} and not SPACE_BEFORE_RE.match(text):
            last.tail = " " + text
        else:
            last.tail = join_token(last.tail or "", text)
    else:
        parent.text = join_token(parent.text or "", text)


def join_token(existing: str, token: str) -> str:
    if not existing:
        return token
    if existing.endswith("\n"):
        return existing + token
    if SPACE_BEFORE_RE.match(token) or NO_SPACE_AFTER_RE.search(existing):
        return existing + token
    if existing.endswith(" "):
        return existing + token
    return existing + " " + token


def append_source_text(parent: ET.Element, text: str) -> None:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return
    if not GREEK_RE.search(text):
        append_text(parent, text)
        return
    foreign = ET.Element(NS + "foreign")
    foreign.set(XML_LANG, "grc")
    foreign.text = text
    parent.append(foreign)


def validate_output(xml_path: Path, manifest_path: Path) -> list[str]:
    issues: list[str] = []
    tree = ET.parse(xml_path)
    root = tree.getroot()
    ns = {"tei": TEI}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    pbs = root.findall(".//tei:pb", ns)
    if len(pbs) != EXPECTED_PAGES:
        issues.append(f"PB_COUNT: expected {EXPECTED_PAGES}, found {len(pbs)}")

    ids = [el.get(XML_ID) for el in root.iter() if el.get(XML_ID)]
    dup_ids = [xml_id for xml_id, count in Counter(ids).items() if count > 1]
    if dup_ids:
        issues.append(f"DUPLICATE_XML_ID: {len(dup_ids)} duplicate generated xml:id values")

    lbs_missing_n = [lb for lb in root.findall(".//tei:lb", ns) if not lb.get("n")]
    if lbs_missing_n:
        issues.append(f"LB_NO_N: {len(lbs_missing_n)} lb elements lack @n")

    for book, expected in EXPECTED_CHAPTERS.items():
        book_div = root.find(f'.//tei:div[@subtype="book"][@n="{book}"]', ns)
        if book_div is None:
            issues.append(f"MISSING_BOOK: {book}")
            continue
        chapters = book_div.findall('.//tei:div[@subtype="chapter"]', ns)
        if len(chapters) != expected:
            issues.append(f"CHAPTER_COUNT: book {book} expected {expected}, found {len(chapters)}")

    manifest_images = {page.get("image") for page in manifest.get("pages", []) if page.get("tei_facs")}
    missing_manifest_images = [pb.get("facs") for pb in pbs if pb.get("facs") not in manifest_images]
    if missing_manifest_images:
        issues.append(f"MISSING_MANIFEST_IMAGE: {len(missing_manifest_images)} pb facs values lack manifest image filenames")

    return issues


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_ocr_candidates(path: Path) -> dict[str, list[dict[str, str]]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_note: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        note_source_id = row.get("note_source_id") or ""
        if note_source_id:
            by_note[note_source_id].append(row)
    return dict(by_note)


def read_token_corrections(path: Path) -> dict[str, TokenCorrection]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    corrections: dict[str, TokenCorrection] = {}
    for row in rows:
        source_id = row.get("source_token_id") or row.get("source_id") or row.get("token_id") or ""
        corrected = row.get("corrected_text") or row.get("replacement") or ""
        status = (row.get("status") or "").strip()
        if not source_id or not corrected or status not in ACCEPTED_STATUSES:
            continue
        corrections[source_id] = TokenCorrection(
            source_id=source_id,
            corrected_text=corrected,
            xml_lang=row.get("xml_lang") or "",
            status=status,
            confidence=row.get("confidence") or "",
            evidence=row.get("evidence") or row.get("evidence_note") or "",
        )
    return corrections


def read_line_roles(path: Path) -> dict[str, LineRole]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    roles: dict[str, LineRole] = {}
    for row in rows:
        source_id = row.get("source_line_id") or row.get("source_id") or row.get("line_id") or ""
        role = row.get("role") or ""
        status = (row.get("status") or "").strip()
        if not source_id or role not in FURNITURE_ROLES or status not in ACCEPTED_STATUSES:
            continue
        roles[source_id] = LineRole(
            source_id=source_id,
            role=role,
            place=row.get("place") or "",
            text=row.get("text") or "",
            status=status,
            confidence=row.get("confidence") or "",
            evidence=row.get("evidence") or row.get("evidence_note") or "",
        )
    return roles


def write_footnote_audit(path: Path, builder: BeckBuilder, validation: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    rows = builder.footnote_audit_rows()
    csv_path = path / "footnotes.csv"
    fieldnames = [
        "source_id",
        "n",
        "page",
        "source_parent",
        "source_parent_id",
        "role",
        "note_xml_id",
        "ref_xml_id",
        "target_note_id",
        "paired_note_source_id",
        "match_method",
        "confidence",
        "status",
        "anchor_token_id",
        "anchor_snippet",
        "candidate_count",
        "evidence_status",
        "candidate_summary",
        "note_excerpt",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (path / "summary.md").write_text(builder.footnote_audit_markdown(validation), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="beck.xml", help="Input Beck OCR/XML source")
    parser.add_argument("--output", default="output/beck2020_epidoc.xml", help="Generated TEI output")
    parser.add_argument("--manifest", default="editions/beck2020/manifest.json", help="Generated private review manifest")
    parser.add_argument("--audit", default="output/beck_private_ingest_audit.md", help="Generated audit report")
    parser.add_argument(
        "--footnote-audit-dir",
        default="output/beck_footnote_audit",
        help="Directory for generated Beck footnote CSV and Markdown audit reports",
    )
    parser.add_argument(
        "--ocr-candidates",
        default="",
        help="Optional OCR sidecar from scripts/ocr_beck_footnote_anchors.py",
    )
    parser.add_argument(
        "--cleaning-dir",
        default="output/beck_text_cleaning",
        help="Directory containing ignored Beck text-cleaning sidecars",
    )
    parser.add_argument("--token-corrections", default="", help="Optional token correction CSV sidecar")
    parser.add_argument("--line-roles", default="", help="Optional line role CSV sidecar")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    manifest_path = Path(args.manifest)
    audit_path = Path(args.audit)
    footnote_audit_dir = Path(args.footnote_audit_dir)
    if not source.exists():
        raise SystemExit(f"Beck source XML not found: {source}")

    cleaning_dir = Path(args.cleaning_dir)
    ocr_candidates_path = Path(args.ocr_candidates) if args.ocr_candidates else footnote_audit_dir / "ocr_candidates.csv"
    token_corrections_path = Path(args.token_corrections) if args.token_corrections else cleaning_dir / "token_corrections.csv"
    line_roles_path = Path(args.line_roles) if args.line_roles else cleaning_dir / "line_roles.csv"
    builder = BeckBuilder(
        read_ocr_candidates(ocr_candidates_path),
        token_corrections=read_token_corrections(token_corrections_path),
        line_roles=read_line_roles(line_roles_path),
    )
    tree = builder.build(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(tree, space="  ")
    tree.write(output, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    write_json(manifest_path, builder.manifest())
    validation = validate_output(output, manifest_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(builder.audit_markdown(validation), encoding="utf-8")
    write_footnote_audit(footnote_audit_dir, builder, validation)

    print(f"Wrote {output}")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {audit_path}")
    print(f"Wrote {footnote_audit_dir / 'footnotes.csv'}")
    print(f"Wrote {footnote_audit_dir / 'summary.md'}")
    if validation:
        print("Validation issues:")
        for issue in validation:
            print(f"  - {issue}")
        return 1
    print("Validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
