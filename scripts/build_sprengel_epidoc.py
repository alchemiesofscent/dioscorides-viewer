#!/usr/bin/env python3
"""Build page-first diplomatic Sprengel EpiDoc and viewer manifest."""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
ARCHIVE_ID = "b23982500_0001"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)


FRONT_LABELS = {
    "title_page": "Title Page",
    "dedication": "Dedication",
    "preface": "Praefatio ad Dioscoridem",
    "errata": "Errata",
    "sigla": "Codices et Editiones",
}

GREEK_HEAD_RE = re.compile(r"Κεφ\.\s*([^.\[]+)\.?\s*\[([^\]]+)")
MALFORMED_GREEK_HEAD_REF_RE = re.compile(r"^(?P<prefix>.*\S)\[(?P<label>\d+[a-z]?)\]\s*$", re.IGNORECASE)
LATIN_CAP_RE = re.compile(
    r"Cap\.\s+([IVXLCDM]+)(?:\.\s*(?:\([^)]+\)\.)?)?\s*\[([^\]]+)\]",
    re.IGNORECASE,
)
APPARATUS_SPLIT_RE = re.compile(r"(?:^|\s+)(\d+\s*[a-z]?)\)\s+", re.IGNORECASE)
NOTE_LABEL_RE = re.compile(r"^\[(\d+[a-z]?)\]$", re.IGNORECASE)


@dataclass(frozen=True)
class ChapterMarker:
    lang: str
    key: str


@dataclass
class Page:
    facs: str
    n: str
    xml_id: str
    index: int
    front_section: str = ""
    book: str = ""
    zones: dict[str, list[ET.Element | ChapterMarker]] = field(
        default_factory=lambda: {"grc": [], "la": [], "front": []}
    )
    chapter_starts: dict[str, list[str]] = field(default_factory=lambda: {"grc": [], "la": []})


@dataclass
class Chapter:
    key: str
    book: str
    chapter: str
    labels: dict[str, str] = field(default_factory=dict)
    raw_labels: dict[str, str] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def attr(element: ET.Element, name: str) -> str:
    if name == "xml:id":
        return element.get(XML_ID) or element.get("xml:id") or ""
    if name == "xml:lang":
        return element.get(XML_LANG) or element.get("xml:lang") or ""
    return element.get(name) or ""


def text_content(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def normalize_chapter_label_text(text: str, lang: str) -> str:
    text = " ".join(text.split()).strip()
    if lang == "grc":
        match = MALFORMED_GREEK_HEAD_REF_RE.match(text)
        if match and "[Περὶ" in match.group("prefix"):
            return match.group("prefix").rstrip(" .") + ".]"
    return text


def clean_label(text: str, lang: str) -> str:
    text = normalize_chapter_label_text(text, lang)
    if lang == "grc":
        match = GREEK_HEAD_RE.search(text)
        if match:
            return match.group(2).replace("[", "").strip(" .")
        return re.sub(r"^Κεφ\.\s*[^.]+\.?\s*", "", text).strip(" .")
    match = LATIN_CAP_RE.search(text)
    if match:
        return match.group(2).strip(" .")
    return re.sub(r"^Cap\.\s*[-IVXLCDM().]+\s*", "", text, flags=re.I).strip(" .")


def roman_to_int(value: str) -> int | None:
    roman = value.upper().strip()
    if not re.fullmatch(r"[IVXLCDM]+", roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for index, char in enumerate(roman):
        current = values[char]
        next_value = values.get(roman[index + 1], 0) if index + 1 < len(roman) else 0
        total += -current if current < next_value else current
    return total


def archive_scan_number(facs: str, fallback_index: int) -> int:
    match = re.search(r"page-(\d{4})\.(?:png|jpe?g|jp2)$", facs)
    return int(match.group(1)) if match else fallback_index


def archive_page_url(archive_id: str, scan_number: int) -> str:
    return f"https://archive.org/details/{archive_id}/page/n{max(0, scan_number - 1)}/mode/1up"


def archive_iiif_image_url(archive_id: str, scan_number: int, width: int) -> str:
    path = (
        f"{archive_id}%2F{archive_id}_jp2.zip%2F"
        f"{archive_id}_jp2%2F{archive_id}_{scan_number:04d}.jp2"
    )
    return f"https://iiif.archive.org/image/iiif/3/{path}/full/{width},/0/default.jpg"


def image_name(facs: str, fallback_index: int) -> str:
    return Path(facs).name if facs else f"page-{fallback_index:04d}.png"


def first_page_break(element: ET.Element) -> ET.Element | None:
    for child in element.iter():
        if local_name(child.tag) == "pb":
            return child
    return None


def copy_without_page_breaks(element: ET.Element) -> ET.Element | None:
    if local_name(element.tag) == "pb":
        return None
    clone = copy.deepcopy(element)
    for parent in list(clone.iter()):
        for child in list(parent):
            if local_name(child.tag) == "pb":
                parent.remove(child)
    return clone


def append_to_last_text(element: ET.Element, text: str) -> None:
    children = list(element)
    if children:
        children[-1].tail = (children[-1].tail or "") + text
    else:
        element.text = (element.text or "") + text


def materialize_text_newlines(element: ET.Element) -> None:
    if element.text and "\n" in element.text:
        parts = element.text.split("\n")
        element.text = parts[0]
        for offset, part in enumerate(parts[1:]):
            lb = ET.Element(f"{NS}lb")
            lb.tail = part
            element.insert(offset, lb)

    index = 0
    while index < len(element):
        child = element[index]
        materialize_text_newlines(child)
        if child.tail and "\n" in child.tail:
            parts = child.tail.split("\n")
            child.tail = parts[0]
            insert_at = index + 1
            for part in parts[1:]:
                lb = ET.Element(f"{NS}lb")
                lb.tail = part
                element.insert(insert_at, lb)
                insert_at += 1
            index = insert_at
        else:
            index += 1


def bracketed_synonyma(seg: ET.Element) -> ET.Element:
    clone = copy.deepcopy(seg)
    clone.text = "[" + (clone.text or "").lstrip()
    append_to_last_text(clone, "]")
    materialize_text_newlines(clone)
    return clone


def remove_leading_head_close(element: ET.Element) -> bool:
    pattern = re.compile(r"^\s*\.\]\s*")
    if element.text and pattern.match(element.text):
        element.text = pattern.sub("", element.text, count=1)
        return True
    for child in element.iter():
        if child is element:
            continue
        if child.tail and pattern.match(child.tail):
            child.tail = pattern.sub("", child.tail, count=1)
            return True
        if child.text and pattern.match(child.text):
            child.text = pattern.sub("", child.text, count=1)
            return True
    return False


def paragraph_with_synonyma_after_lemma(
    paragraph: ET.Element,
    seg: ET.Element,
    strip_leading_head_close: bool = False,
) -> tuple[ET.Element, bool]:
    clone = copy.deepcopy(paragraph)
    stripped = remove_leading_head_close(clone) if strip_leading_head_close else False
    synonyma = bracketed_synonyma(seg)

    def split_first_word(text: str) -> tuple[str, str] | None:
        match = re.match(r"(\s*\S+)(\s+.*)?$", text, flags=re.DOTALL)
        if not match:
            return None
        return match.group(1), (match.group(2) or "")

    split = split_first_word(clone.text or "")
    if split:
        first, rest = split
        clone.text = first + " "
        synonyma.tail = rest
        clone.insert(0, synonyma)
        return clone, stripped

    for index, child in enumerate(list(clone)):
        split = split_first_word(child.tail or "")
        if split:
            first, rest = split
            child.tail = first + " "
            synonyma.tail = rest
            clone.insert(index + 1, synonyma)
            return clone, stripped

    clone.insert(0, synonyma)
    return clone, stripped


class SprengelBuilder:
    def __init__(self, source: Path, archive_id: str, iiif_width: int) -> None:
        self.source = source
        self.archive_id = archive_id
        self.iiif_width = iiif_width
        self.root = ET.parse(source).getroot()
        self.pages: dict[str, Page] = {}
        self.page_order: list[str] = []
        self.chapters: dict[str, Chapter] = {}
        self.marker_counts: dict[str, int] = {}
        self.ref_id_counts: defaultdict[str, int] = defaultdict(int)
        self.ref_ids_by_target: defaultdict[str, list[str]] = defaultdict(list)
        self.source_ids = {
            element.get(XML_ID)
            for element in self.root.iter()
            if element.get(XML_ID)
        }
        self.source_targets = {
            (element.get("target") or "").lstrip("#")
            for element in self.root.iter()
            if element.get("target", "").startswith("#")
        }

    def page_for_pb(self, pb: ET.Element) -> Page:
        facs = attr(pb, "facs")
        if not facs:
            facs = f"generated-page-{len(self.page_order) + 1:04d}"
        if facs not in self.pages:
            page = Page(
                facs=facs,
                n="" if attr(pb, "n") == "None" else attr(pb, "n"),
                xml_id=attr(pb, "xml:id") or f"spr-pb-{len(self.page_order) + 1:04d}",
                index=len(self.page_order) + 1,
            )
            self.pages[facs] = page
            self.page_order.append(facs)
        else:
            page = self.pages[facs]
            if not page.n and attr(pb, "n") and attr(pb, "n") != "None":
                page.n = attr(pb, "n")
        return page

    def chapter_for(self, book: str, chapter: str) -> Chapter:
        key = f"{book}.{chapter}"
        if key not in self.chapters:
            self.chapters[key] = Chapter(key=key, book=book, chapter=chapter)
        return self.chapters[key]

    def add_chapter_start(self, page: Page, lang: str, book: str, chapter: str, raw_label: str) -> ChapterMarker:
        normalized_chapter = str(int(chapter)) if chapter.isdigit() else chapter
        chapter_record = self.chapter_for(book, normalized_chapter)
        raw_label = normalize_chapter_label_text(raw_label, lang)
        label = clean_label(raw_label, lang)
        if label:
            chapter_record.labels[lang] = label
        if raw_label:
            chapter_record.raw_labels[lang] = " ".join(raw_label.split())
        chapter_record.pages[lang] = page.facs
        if chapter_record.key not in page.chapter_starts[lang]:
            page.chapter_starts[lang].append(chapter_record.key)
        return ChapterMarker(lang=lang, key=chapter_record.key)

    def target_id_for_label(self, page: Page, book: str, label: str) -> str:
        scan_number = archive_scan_number(page.facs, page.index)
        normalized_label = re.sub(r"\s+", "", label)
        return f"spr-app-{book}-{scan_number:04d}-{normalized_label}"

    def next_ref_id(self, target_id: str) -> str:
        base = f"ref-{target_id}"
        self.ref_id_counts[base] += 1
        return base if self.ref_id_counts[base] == 1 else f"{base}-{self.ref_id_counts[base]}"

    def normalize_ref(self, ref: ET.Element, target_id: str | None = None, label: str | None = None) -> None:
        target = attr(ref, "target")
        if target_id is None and target.startswith("#"):
            target_id = target[1:]
        if not target_id or not target_id.startswith("spr-app-"):
            return

        if label is None:
            label = text_content(ref)
        label_match = NOTE_LABEL_RE.match(label.strip())
        normalized_label = label_match.group(1) if label_match else label.strip("[] ")
        if not normalized_label:
            return

        ref.set("target", f"#{target_id}")
        ref.set("type", "footnote-ref")
        ref_id = attr(ref, "xml:id")
        if not ref_id:
            ref_id = self.next_ref_id(target_id)
            ref.set(XML_ID, ref_id)
        self.ref_ids_by_target[target_id].append(ref_id)
        ref.text = normalized_label
        for child in list(ref):
            ref.remove(child)

    def normalize_refs_in_tree(self, element: ET.Element) -> None:
        for ref in element.iter(f"{NS}ref"):
            self.normalize_ref(ref)

    def normalize_note(self, note: ET.Element) -> ET.Element:
        materialize_text_newlines(note)
        self.normalize_refs_in_tree(note)
        note.set("type", "footnote")
        note.set("place", "bottom")
        note_id = attr(note, "xml:id")
        if note_id:
            ref_ids = self.ref_ids_by_target.get(note_id) or []
            if ref_ids:
                note.set("corresp", " ".join(f"#{ref_id}" for ref_id in ref_ids))
        return note

    def repaired_greek_head(self, head: ET.Element, page: Page, book: str) -> tuple[ET.Element, bool]:
        clone = copy.deepcopy(head)
        text = text_content(clone)
        match = MALFORMED_GREEK_HEAD_REF_RE.match(text)
        if not match or "[Περὶ" not in match.group("prefix"):
            self.normalize_refs_in_tree(clone)
            return clone, False

        label = match.group("label")
        target_id = self.target_id_for_label(page, book, label)
        clone.clear()
        clone.text = match.group("prefix").rstrip(" .")
        ref = ET.SubElement(clone, f"{NS}ref")
        self.normalize_ref(ref, target_id=target_id, label=label)
        ref.tail = ".]"
        return clone, True

    def collect_front(self) -> None:
        front = self.root.find(f".//{NS}front")
        if front is None:
            return
        for child in list(front):
            name = local_name(child.tag)
            section = "title_page" if name == "titlePage" else attr(child, "type") or name
            current_page: Page | None = None
            for node in list(child):
                if local_name(node.tag) == "pb":
                    current_page = self.page_for_pb(node)
                    current_page.front_section = section
                    continue
                if current_page is None:
                    continue
                current_page.zones["front"].extend(self.output_items(node))

    def collect_body_language(self, language_div: ET.Element, lang: str) -> None:
        state = {
            "page": None,
            "book": "",
            "chapter": "",
            "chapter_marker_pending": False,
            "chapter_raw_label": "",
            "consume_leading_head_close": False,
        }

        def process(node: ET.Element) -> None:
            name = local_name(node.tag)
            if name == "pb":
                page = self.page_for_pb(node)
                state["page"] = page
                if state["book"] and not page.book:
                    page.book = str(state["book"])
                return

            if name == "div":
                previous = state.copy()
                subtype = attr(node, "subtype")
                if subtype == "book":
                    state["book"] = attr(node, "n")
                    state["chapter"] = ""
                    state["chapter_marker_pending"] = False
                    for child in list(node):
                        process(child)
                elif subtype == "chapter":
                    state["chapter"] = attr(node, "n")
                    state["chapter_marker_pending"] = True
                    head = next((child for child in list(node) if local_name(child.tag) == "head"), None)
                    state["chapter_raw_label"] = (
                        normalize_chapter_label_text(text_content(head), lang) if head is not None else ""
                    )
                    children = list(node)
                    index = 0
                    while index < len(children):
                        child = children[index]
                        if local_name(child.tag) == "head" and lang == "grc":
                            page = state["page"]
                            if page is not None and state["book"]:
                                if state["chapter_marker_pending"] and state["chapter"]:
                                    page.zones[lang].append(
                                        self.add_chapter_start(
                                            page,
                                            lang,
                                            str(state["book"]),
                                            str(state["chapter"]),
                                            str(state["chapter_raw_label"]),
                                        )
                                    )
                                    state["chapter_marker_pending"] = False
                                repaired_head, consumed = self.repaired_greek_head(child, page, str(state["book"]))
                                page.zones[lang].append(repaired_head)
                                if consumed:
                                    state["consume_leading_head_close"] = True
                                index += 1
                                continue
                        if (
                            lang == "grc"
                            and local_name(child.tag) == "seg"
                            and attr(child, "type") == "synonyma"
                        ):
                            page = state["page"]
                            if (
                                page is not None
                                and index + 1 < len(children)
                                and local_name(children[index + 1].tag) == "p"
                            ):
                                paragraph, stripped = paragraph_with_synonyma_after_lemma(
                                    children[index + 1],
                                    child,
                                    strip_leading_head_close=bool(state["consume_leading_head_close"]),
                                )
                                if stripped:
                                    state["consume_leading_head_close"] = False
                                self.normalize_refs_in_tree(paragraph)
                                page.zones[lang].append(paragraph)
                                index += 2
                                continue
                            if page is not None:
                                synonyma = bracketed_synonyma(child)
                                self.normalize_refs_in_tree(synonyma)
                                page.zones[lang].append(synonyma)
                            index += 1
                            continue
                        if (
                            lang == "grc"
                            and state["consume_leading_head_close"]
                            and local_name(child.tag) == "p"
                        ):
                            page = state["page"]
                            if page is not None:
                                paragraph = copy.deepcopy(child)
                                if remove_leading_head_close(paragraph):
                                    state["consume_leading_head_close"] = False
                                    self.normalize_refs_in_tree(paragraph)
                                    page.zones[lang].append(paragraph)
                                    index += 1
                                    continue
                        process(child)
                        index += 1
                else:
                    for child in list(node):
                        process(child)
                state.update(previous)
                return

            page = state["page"]
            if page is None:
                return
            if state["book"] and not page.book:
                page.book = str(state["book"])

            if lang == "grc" and state["chapter_marker_pending"] and state["book"] and state["chapter"]:
                page.zones[lang].append(
                    self.add_chapter_start(
                        page,
                        lang,
                        str(state["book"]),
                        str(state["chapter"]),
                        str(state["chapter_raw_label"]),
                    )
                )
                state["chapter_marker_pending"] = False

            if lang == "la":
                raw_text = text_content(node)
                for match in LATIN_CAP_RE.finditer(raw_text):
                    chapter_num = roman_to_int(match.group(1))
                    if chapter_num and state["book"]:
                        page.zones[lang].append(
                            self.add_chapter_start(
                                page,
                                lang,
                                str(state["book"]),
                                str(chapter_num),
                                match.group(0),
                            )
                        )

            page.zones[lang].extend(self.output_items(node))

        for child in list(language_div):
            process(child)

    def split_apparatus_note(self, note: ET.Element) -> list[ET.Element]:
        original_id = attr(note, "xml:id")
        original_n = attr(note, "n")
        text = text_content(note)
        matches = list(APPARATUS_SPLIT_RE.finditer(text))
        if not matches or not original_id:
            return [note]

        pieces: list[tuple[str, str]] = [(original_n, text[: matches[0].start()].strip())]
        for index, match in enumerate(matches):
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            pieces.append((match.group(1), text[match.end() : next_start].strip()))

        output = []
        for index, (number, piece_text) in enumerate(pieces):
            if not piece_text:
                continue
            if index == 0:
                clone = copy.deepcopy(note)
                clone.text = piece_text
                for child in list(clone):
                    clone.remove(child)
                output.append(clone)
                continue

            normalized_number = re.sub(r"\s+", "", number)
            if original_n:
                generated_id = re.sub(r"-\d+[a-z]?$", f"-{normalized_number}", original_id, flags=re.IGNORECASE)
            else:
                generated_id = f"{original_id}-{normalized_number}"
            if generated_id not in self.source_targets or generated_id in self.source_ids:
                continue
            clone = copy.deepcopy(note)
            clone.set("n", normalized_number)
            clone.set(XML_ID, generated_id)
            clone.text = piece_text
            for child in list(clone):
                clone.remove(child)
            output.append(clone)
        return output

    def output_items(self, element: ET.Element) -> list[ET.Element]:
        clone = copy_without_page_breaks(element)
        if clone is None:
            return []
        if local_name(clone.tag) == "note" and attr(clone, "type") == "apparatus":
            notes = self.split_apparatus_note(clone)
            output = []
            for note in notes:
                note_id = attr(note, "xml:id")
                match = re.match(r"(.+-)(\d+)[a-z]$", note_id, flags=re.IGNORECASE)
                if match:
                    alias_id = f"{match.group(1)}{match.group(2)}"
                    if alias_id in self.source_targets and alias_id not in self.source_ids:
                        alias = copy.deepcopy(note)
                        alias.set(XML_ID, alias_id)
                        alias.set("n", match.group(2))
                        output.append(self.normalize_note(alias))
                output.append(self.normalize_note(note))
            return output
        self.normalize_refs_in_tree(clone)
        return [clone]

    def collect_body(self) -> None:
        body = self.root.find(f".//{NS}body")
        if body is None:
            return
        for div in body.findall(f"{NS}div"):
            div_type = attr(div, "type")
            lang = attr(div, "xml:lang")
            if div_type == "edition" and lang == "grc":
                self.collect_body_language(div, "grc")
            elif div_type == "translation" and lang == "la":
                self.collect_body_language(div, "la")
        self.resolve_missing_apparatus_targets()

    def resolve_missing_apparatus_targets(self) -> None:
        known_ids = set(self.source_ids)
        for page in self.pages.values():
            for items in page.zones.values():
                for item in items:
                    if isinstance(item, ET.Element):
                        item_id = attr(item, "xml:id")
                        if item_id:
                            known_ids.add(item_id)
                        for child in item.iter():
                            child_id = attr(child, "xml:id")
                            if child_id:
                                known_ids.add(child_id)

        created: set[str] = set()
        for page in self.pages.values():
            for items in page.zones.values():
                missing_for_zone = []
                seen_missing_for_zone = set()
                for item in items:
                    if not isinstance(item, ET.Element):
                        continue
                    for ref in item.iter(f"{NS}ref"):
                        target = attr(ref, "target")
                        if not target.startswith("#"):
                            continue
                        target_id = target[1:]
                        if (
                            target_id in known_ids
                            or target_id in created
                            or target_id in seen_missing_for_zone
                            or not target_id.startswith("spr-app-")
                        ):
                            continue
                        missing_for_zone.append((target_id, text_content(ref).strip("[] ")))
                        seen_missing_for_zone.add(target_id)
                for target_id, label in missing_for_zone:
                    note = ET.Element(
                        f"{NS}note",
                        {
                            "type": "footnote",
                            "subtype": "missing-source-note",
                            "place": "bottom",
                        },
                    )
                    if label:
                        note.set("n", label)
                    note.set(XML_ID, target_id)
                    ref_ids = self.ref_ids_by_target.get(target_id) or []
                    if ref_ids:
                        note.set("corresp", " ".join(f"#{ref_id}" for ref_id in ref_ids))
                    note.text = "Apparatus note missing from source import."
                    items.append(note)
                    created.add(target_id)

    def marker_element(self, marker: ChapterMarker) -> ET.Element:
        chapter = self.chapters[marker.key]
        other_lang = "la" if marker.lang == "grc" else "grc"
        id_base = f"spr-ch-{chapter.key}-{marker.lang}"
        marker_count = self.marker_counts.get(id_base, 0) + 1
        self.marker_counts[id_base] = marker_count
        element = ET.Element(f"{NS}milestone")
        element.set("unit", "chapter")
        element.set("type", "chapterStart")
        element.set("n", chapter.key)
        element.set(XML_ID, id_base if marker_count == 1 else f"{id_base}-{marker_count}")
        element.set(XML_LANG, marker.lang)
        if chapter.labels.get(marker.lang):
            element.set("label", chapter.labels[marker.lang])
        if chapter.raw_labels.get(marker.lang):
            element.set("sourceLabel", chapter.raw_labels[marker.lang])
        if chapter.labels.get(other_lang):
            element.set("pairedLabel", chapter.labels[other_lang])
        if chapter.raw_labels.get(other_lang):
            element.set("pairedSourceLabel", chapter.raw_labels[other_lang])
        if chapter.pages.get(other_lang):
            element.set("corresp", f"#spr-ch-{chapter.key}-{other_lang}")
        return element

    def append_zone_items(self, parent: ET.Element, items: list[ET.Element | ChapterMarker]) -> None:
        for item in items:
            if isinstance(item, ChapterMarker):
                parent.append(self.marker_element(item))
            else:
                parent.append(item)

    def renumber_zone_lines(self, items: list[ET.Element | ChapterMarker]) -> None:
        line_number = 1

        def renumber_element(element: ET.Element, in_note: bool = False) -> None:
            nonlocal line_number
            element_in_note = in_note or local_name(element.tag) == "note"
            if local_name(element.tag) == "lb" and not element_in_note:
                element.set("n", str(line_number))
                line_number += 1
            for child in list(element):
                renumber_element(child, element_in_note)

        for item in items:
            if not isinstance(item, ET.Element):
                continue
            renumber_element(item)

    def build_tei(self) -> ET.ElementTree:
        self.collect_front()
        self.collect_body()
        self.marker_counts = {}

        tei = ET.Element(f"{NS}TEI")
        header = self.root.find(f"{NS}teiHeader")
        if header is not None:
            tei.append(copy.deepcopy(header))

        text = ET.SubElement(tei, f"{NS}text")
        front = ET.SubElement(text, f"{NS}front")
        for section, label in FRONT_LABELS.items():
            section_pages = [self.pages[facs] for facs in self.page_order if self.pages[facs].front_section == section]
            if not section_pages:
                continue
            div = ET.SubElement(front, f"{NS}div", {"type": section, "n": section})
            ET.SubElement(div, f"{NS}head").text = label
            for page in section_pages:
                page_div = ET.SubElement(div, f"{NS}div", {"type": "page", "subtype": "diplomatic-page", "n": page.n})
                page_div.set("facs", page.facs)
                page_div.set(XML_ID, f"spr-page-{page.index:04d}")
                pb = ET.SubElement(page_div, f"{NS}pb")
                if page.n:
                    pb.set("n", page.n)
                pb.set("facs", page.facs)
                pb.set(XML_ID, page.xml_id)
                zone = ET.SubElement(page_div, f"{NS}ab", {"type": "pageZone", "place": "full"})
                zone.set(XML_LANG, "la")
                self.append_zone_items(zone, page.zones["front"])

        body = ET.SubElement(text, f"{NS}body")
        edition = ET.SubElement(
            body,
            f"{NS}div",
            {
                "type": "edition",
                "subtype": "diplomatic",
                "n": "urn:cts:greekLit:tlg0656.tlg001.sprengel-diplomatic",
            },
        )
        body_pages = [self.pages[facs] for facs in self.page_order if self.pages[facs].book]
        for book in ["1", "2", "3", "4", "5"]:
            book_pages = [page for page in body_pages if page.book == book]
            if not book_pages:
                continue
            book_div = ET.SubElement(edition, f"{NS}div", {"type": "textpart", "subtype": "book", "n": book})
            ET.SubElement(book_div, f"{NS}head").text = f"Book {book}"
            for page in book_pages:
                page_div = ET.SubElement(book_div, f"{NS}div", {"type": "page", "subtype": "diplomatic-page", "n": page.n})
                page_div.set("facs", page.facs)
                page_div.set(XML_ID, f"spr-page-{page.index:04d}")
                pb = ET.SubElement(page_div, f"{NS}pb")
                if page.n:
                    pb.set("n", page.n)
                pb.set("facs", page.facs)
                pb.set(XML_ID, page.xml_id)
                for lang, place in (("grc", "top"), ("la", "bottom")):
                    if not page.zones[lang]:
                        continue
                    zone = ET.SubElement(page_div, f"{NS}ab", {"type": "pageZone", "place": place})
                    zone.set(XML_LANG, lang)
                    self.renumber_zone_lines(page.zones[lang])
                    self.append_zone_items(zone, page.zones[lang])

        ET.indent(tei, space="  ")
        return ET.ElementTree(tei)

    def build_manifest(self) -> dict:
        pages = []
        for fallback_index, facs in enumerate(self.page_order, start=1):
            page = self.pages[facs]
            scan_number = archive_scan_number(facs, fallback_index)
            section = page.front_section or (f"book {page.book}" if page.book else "")
            chapter_keys = sorted({key for starts in page.chapter_starts.values() for key in starts})
            pages.append(
                {
                    "pdf_page": scan_number,
                    "archive_page_n": max(0, scan_number - 1),
                    "book_page": page.n,
                    "section": section,
                    "book": page.book,
                    "chapter_starts": chapter_keys,
                    "tei_facs": facs,
                    "facs": archive_page_url(self.archive_id, scan_number),
                    "remoteImage": archive_iiif_image_url(self.archive_id, scan_number, self.iiif_width),
                    "image": image_name(facs, fallback_index),
                    "xml_id": page.xml_id,
                }
            )
        return {
            "total_pages": len(pages),
            "source": "Sprengel 1829/1830 diplomatic TEI normalized as page-first EpiDoc",
            "source_url": f"https://archive.org/details/{self.archive_id}/page/n5/mode/2up",
            "iiif_manifest": f"https://iiif.archive.org/iiif/{self.archive_id}/manifest.json",
            "image_root": f"https://iiif.archive.org/image/iiif/3/{self.archive_id}/",
            "iiif_width": self.iiif_width,
            "pages": pages,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--archive-id", default=ARCHIVE_ID)
    parser.add_argument("--iiif-width", type=int, default=1200)
    args = parser.parse_args()

    builder = SprengelBuilder(args.source, args.archive_id, args.iiif_width)
    tei = builder.build_tei()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    tei.write(args.output, encoding="utf-8", xml_declaration=True)
    args.manifest.write_text(
        json.dumps(builder.build_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
