#!/usr/bin/env python3
"""Build viewer-ready XML for Sprengel's Commentarius OCR stream."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


XML = "http://www.w3.org/XML/1998/namespace"
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"

ET.register_namespace("xml", XML)

PRIMARY_FACS = (
    "https://archive.org/download/b23982500_0002/"
    "b23982500_0002_jp2.zip/b23982500_0002_jp2%2F"
    "b23982500_0002_{leaf:04d}.jp2"
)
BIU_FACS = (
    "https://archive.org/download/BIUSante_dioscsprengelx02/"
    "BIUSante_dioscsprengelx02_jp2.zip/BIUSante_dioscsprengelx02_jp2%2F"
    "BIUSante_dioscsprengelx02_{leaf:04d}.jp2"
)

GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]+(?:[\u0370-\u03ff\u1f00-\u1fff\s.,;:·'’()\[\]-]*[\u0370-\u03ff\u1f00-\u1fff]+)?")
CAP_RE = re.compile(
    r"(?<![A-Za-z])Cap\.\s+([IVXLCDM]+)\.?"
    r"(?:\s*[—-]\s*([IVXLCDM]+)\.|\s+([IVXLCDM]+)\.)?",
    re.IGNORECASE,
)
HEADER_BOOK_RE = re.compile(
    r"IN\s+DIOSCORID[EI]M\.?\s+((?:[IVXLCDM]+\.?\s+[0-9]+(?:\s*[—-]\s*[0-9]+)?\.?\s*)+)",
    re.IGNORECASE,
)
HEADER_RANGE_RE = re.compile(r"([IVXLCDM]+)\.?\s+([0-9]+)(?:\s*[—-]\s*([0-9]+))?", re.IGNORECASE)
ID_ATTRS = {"id", XML_ID}


@dataclass
class ChapterRow:
    n: str
    xml_id: str
    label_la: str
    label_grc: str


@dataclass
class Page:
    n: int
    ranges: list[tuple[int, int, int]] = field(default_factory=list)
    blocks: list["Block"] = field(default_factory=list)
    notes: dict[str, list["Item"]] = field(default_factory=dict)


@dataclass
class Item:
    kind: str
    value: str | ET.Element | None = None
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class Block:
    role: str
    items: list[Item]
    source_tag: str = ""


@dataclass
class Counters:
    p: int = 1
    div: int = 1
    e: int = 1
    ftn: int = 1
    hr: int = 1


@dataclass
class BuildStats:
    pages: int = 0
    chapters: int = 0
    footnotes: int = 0
    paragraphs: int = 0
    unmatched_chapters: list[str] = field(default_factory=list)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def strip_attr_name(name: str) -> str:
    if name == XML_ID:
        return "id"
    if name == XML_LANG:
        return XML_LANG
    return local_name(name)


def roman_to_int(value: str) -> int:
    table = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for char in reversed(value.upper()):
        cur = table[char]
        if cur < prev:
            total -= cur
        else:
            total += cur
            prev = cur
    return total


def load_chapter_table(path: Path) -> dict[str, ChapterRow]:
    rows: dict[str, ChapterRow] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            rows[row["n"]] = ChapterRow(
                n=row["n"],
                xml_id=row["xml_id"],
                label_la=row["label_la"],
                label_grc=row["label_grc"],
            )
    return rows


def facs_url(page: int) -> str:
    # Pages 436 and 437 are missing from the primary IA scan (b23982500_0002)
    # and served from a BIU Santé fallback, where they sit at leaves 0437 and
    # 0438. Because the primary scan has no leaves for those two pages, its
    # leaf-to-page offset drops from +8 (pages 339–435) to +6 from page 438
    # onward — verified against running headers in OCR (file _0444 = p.438,
    # file _0672 = p.666).
    if page == 436:
        return BIU_FACS.format(leaf=437)
    if page == 437:
        return BIU_FACS.format(leaf=438)
    if page >= 438:
        return PRIMARY_FACS.format(leaf=page + 6)
    return PRIMARY_FACS.format(leaf=page + 8)


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("ϑ", "θ")


def append_text(items: list[Item], text: str | None) -> None:
    text = normalize_text(text)
    if text:
        items.append(Item("text", text))


def transform_inline_element(el: ET.Element) -> ET.Element:
    out = ET.Element(local_name(el.tag))
    for key, value in el.attrib.items():
        attr = strip_attr_name(key)
        if attr in {"target"} and local_name(el.tag) == "ref":
            continue
        out.set(attr, normalize_text(value))
    items = flatten_content(el, include_notes=False)
    fill_element(out, items)
    return out


def flatten_content(parent: ET.Element, include_notes: bool = False) -> list[Item]:
    items: list[Item] = []
    append_text(items, parent.text)
    for child in list(parent):
        tag = local_name(child.tag)
        if tag == "lb":
            items.append(Item("break", attrs={"break": child.attrib.get("break", "")}))
        elif tag == "cb":
            items.append(Item("text", " "))
        elif tag == "ref":
            target = child.attrib.get("target", "")
            display = "".join(child.itertext()).strip()
            items.append(Item("note", attrs={"target": target, "display": display}))
        elif tag == "note" and not include_notes:
            pass
        elif tag in {"fw"}:
            pass
        else:
            items.append(Item("elem", transform_inline_element(child)))
        append_text(items, child.tail)
    return join_line_breaks(items)


def text_of_element(el: ET.Element) -> str:
    return "".join(el.itertext())


def plain_text(items: Iterable[Item]) -> str:
    parts: list[str] = []
    for item in items:
        if item.kind == "text":
            parts.append(str(item.value))
        elif item.kind == "elem":
            parts.append(text_of_element(item.value))  # type: ignore[arg-type]
        elif item.kind == "note":
            parts.append(str(item.attrs.get("display") or ""))
    return "".join(parts)


def remove_trailing_hyphen_from_element(el: ET.Element) -> bool:
    children = list(el)
    if children and remove_trailing_hyphen_from_element(children[-1]):
        return True
    if children and children[-1].tail:
        tail = children[-1].tail.rstrip()
        if tail.endswith("-"):
            children[-1].tail = tail[:-1]
            return True
    if el.text:
        text = el.text.rstrip()
        if text.endswith("-"):
            el.text = text[:-1]
            return True
    return False


def remove_trailing_hyphen(items: list[Item]) -> None:
    for item in reversed(items):
        if item.kind == "text":
            text = str(item.value).rstrip()
            if text.endswith("-"):
                item.value = text[:-1]
            return
        if item.kind == "elem" and remove_trailing_hyphen_from_element(item.value):  # type: ignore[arg-type]
            return


def append_join_space(items: list[Item]) -> None:
    if not items:
        return
    text = plain_text(items[-1:])
    if text and not text[-1].isspace():
        items.append(Item("text", "\n"))


def join_line_breaks(items: list[Item]) -> list[Item]:
    out: list[Item] = []
    for item in items:
        if item.kind != "break":
            out.append(item)
            continue
        if item.attrs.get("break") == "no":
            remove_trailing_hyphen(out)
        else:
            append_join_space(out)
    return coalesce_text(out)


def coalesce_text(items: list[Item]) -> list[Item]:
    out: list[Item] = []
    for item in items:
        if item.kind == "text" and out and out[-1].kind == "text":
            out[-1].value = str(out[-1].value) + str(item.value)
        else:
            out.append(item)
    return out


def fill_element(parent: ET.Element, items: list[Item]) -> None:
    last: ET.Element | None = None
    for item in items:
        if item.kind == "text":
            text = str(item.value)
            if last is None:
                parent.text = (parent.text or "") + text
            else:
                last.tail = (last.tail or "") + text
        elif item.kind == "elem":
            child = item.value  # type: ignore[assignment]
            parent.append(child)  # type: ignore[arg-type]
            last = child  # type: ignore[assignment]
        elif item.kind == "note":
            marker = ET.Element("note")
            for key, value in item.attrs.items():
                marker.set(key, value)
            parent.append(marker)
            last = marker


def copy_items(items: list[Item]) -> list[Item]:
    copied: list[Item] = []
    for item in items:
        if item.kind == "elem":
            copied.append(Item("elem", ET.fromstring(ET.tostring(item.value, encoding="unicode"))))  # type: ignore[arg-type]
        else:
            copied.append(Item(item.kind, item.value, dict(item.attrs)))
    return copied


def collapse_output_space(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def clean_element_text(el: ET.Element) -> None:
    if el.text:
        el.text = collapse_output_space(el.text)
    for child in list(el):
        clean_element_text(child)
        if child.tail:
            child.tail = collapse_output_space(child.tail)


def clean_items_for_output(items: list[Item]) -> list[Item]:
    cleaned: list[Item] = []
    for item in items:
        if item.kind == "text":
            cleaned.append(Item("text", collapse_output_space(str(item.value))))
        elif item.kind == "elem":
            el = item.value  # type: ignore[assignment]
            clean_element_text(el)  # type: ignore[arg-type]
            cleaned.append(item)
        else:
            cleaned.append(item)
    return coalesce_text(cleaned)


def item_len(item: Item) -> int:
    if item.kind == "text":
        return len(str(item.value))
    if item.kind == "elem":
        return len(text_of_element(item.value))  # type: ignore[arg-type]
    if item.kind == "note":
        return len(item.attrs.get("display", ""))
    return 0


def split_items_at(items: list[Item], offset: int) -> tuple[list[Item], list[Item]]:
    before: list[Item] = []
    after: list[Item] = []
    pos = 0
    for item in items:
        length = item_len(item)
        next_pos = pos + length
        if next_pos <= offset:
            before.append(item)
        elif pos >= offset:
            after.append(item)
        elif item.kind == "text":
            text = str(item.value)
            cut = offset - pos
            before.append(Item("text", text[:cut]))
            after.append(Item("text", text[cut:]))
        else:
            after.append(item)
        pos = next_pos
    return coalesce_text(before), coalesce_text(after)


def split_chapter_blocks(block: Block) -> list[Block]:
    if block.role != "p":
        return [block]
    text = plain_text(block.items)
    matches = [m for m in CAP_RE.finditer(text) if is_chapter_boundary(text, m)]
    if not matches:
        return [block]

    offsets = [m.start() for m in matches if m.start() > 0]
    pieces = [block.items]
    base = 0
    for offset in offsets:
        current = pieces.pop()
        left, right = split_items_at(current, offset - base)
        if left and plain_text(left).strip():
            pieces.append(left)
        pieces.append(right)
        base = offset
    return [Block("p", piece, block.source_tag) for piece in pieces if plain_text(piece).strip()]


def is_chapter_boundary(text: str, match: re.Match[str]) -> bool:
    prefix = text[: match.start()]
    if not prefix.strip():
        return True
    tail = prefix[-8:]
    if "\n" in tail:
        return True
    return False


def parse_header_ranges(text: str) -> list[tuple[int, int, int]]:
    ranges: list[tuple[int, int, int]] = []
    for header in HEADER_BOOK_RE.finditer(text):
        for part in HEADER_RANGE_RE.finditer(header.group(1)):
            book = roman_to_int(part.group(1))
            start = int(part.group(2))
            end = int(part.group(3) or start)
            ranges.append((book, start, end))
    return ranges


def is_running_furniture(text: str, source_tag: str = "") -> bool:
    value = re.sub(r"\s+", " ", text).strip()
    if not value:
        return True
    upper = value.upper()
    if upper in {"COMMENTARIUS", "IN", "DIOSCORIDEM.", "IN DIOSCORIDEM."}:
        return True
    if re.fullmatch(r"\d+\s+COMMENTARIUS|COMMENTARIUS\s+\d+", upper):
        return True
    if upper.startswith("IN DIOSCORIDEM") or upper.startswith("IN DIOSCORIDIS"):
        return True
    if re.fullmatch(r"[A-Z][a-z]?\s*\d+", value):
        return True
    if source_tag == "fw":
        return True
    return False


def strip_leading_furniture(items: list[Item]) -> list[Item]:
    while True:
        text = plain_text(items)
        if not text.strip():
            return []
        leading_ws = len(text) - len(text.lstrip())
        rest = text[leading_ws:]
        line, sep, _tail = rest.partition("\n")
        line_end = leading_ws + len(line) + (1 if sep else 0)
        if is_running_furniture(line) or re.fullmatch(r"\d+\s+COMMENTARIUS|COMMENTARIUS\s+\d+", line.strip(), re.IGNORECASE):
            _before, items = split_items_at(items, line_end)
            continue
        return items


def heading_role(text: str) -> str | None:
    value = re.sub(r"\s+", " ", text).strip()
    upper = value.upper()
    if "ANNOTATIONES" in upper:
        return "annotationes"
    if upper == "PRAEFATIO." or upper == "PRAEFATIO":
        return "h2"
    if re.fullmatch(r"LIB\.\s+[IVXLCDM]+\.?", upper):
        return "h2"
    return None


def extract_pages(source: Path) -> list[Page]:
    tree = ET.parse(source)
    body = tree.getroot().find(f".//{{{TEI}}}body")
    if body is None:
        raise ValueError("No TEI body found in source")

    pages: list[Page] = []
    current: Page | None = None

    def ensure_page() -> Page:
        nonlocal current
        if current is None:
            current = Page(0)
            pages.append(current)
        return current

    def add_block(el: ET.Element, role_override: str | None = None) -> None:
        page = ensure_page()
        tag = local_name(el.tag)
        if tag == "note":
            xml_id = el.attrib.get(XML_ID) or el.attrib.get("xml:id") or el.attrib.get("id")
            if xml_id:
                page.notes[xml_id] = flatten_content(el, include_notes=True)
            return
        if tag == "div" and el.attrib.get("type") == "footnotes":
            for note in el.findall(f".//{{{TEI}}}note"):
                add_block(note)
            return
        if tag == "div":
            for child in list(el):
                add_block(child)
            return
        items = flatten_content(el)
        text = plain_text(items)
        page.ranges.extend(parse_header_ranges(text))
        role = role_override or heading_role(text) or "p"
        if is_running_furniture(text, tag):
            return
        if role == "h2" and CAP_RE.search(text):
            role = "p"
        page.blocks.append(Block(role, items, tag))

    direct_items: list[Item] = []

    def append_inline_child(child: ET.Element) -> None:
        tag = local_name(child.tag)
        if tag == "lb":
            direct_items.append(Item("break", attrs={"break": child.attrib.get("break", "")}))
        elif tag == "cb":
            direct_items.append(Item("text", " "))
        elif tag == "ref":
            target = child.attrib.get("target", "")
            display = "".join(child.itertext()).strip()
            direct_items.append(Item("note", attrs={"target": target, "display": display}))
        elif tag in {"foreign", "hi", "span"}:
            direct_items.append(Item("elem", transform_inline_element(child)))
        else:
            pseudo = ET.Element("span")
            pseudo.text = child.text
            for grandchild in list(child):
                pseudo.append(grandchild)
            direct_items.extend(flatten_content(pseudo))
        append_text(direct_items, child.tail)

    def flush_direct_items() -> None:
        nonlocal direct_items
        direct_items = join_line_breaks(direct_items)
        raw_text = plain_text(direct_items)
        page = ensure_page()
        page.ranges.extend(parse_header_ranges(raw_text))
        direct_items = strip_leading_furniture(direct_items)
        text = plain_text(direct_items)
        if not text.strip():
            direct_items = []
            return
        role = heading_role(text) or "p"
        if not is_running_furniture(text):
            page.blocks.append(Block(role, direct_items, "body"))
        direct_items = []

    if body.text and body.text.strip():
        append_text(direct_items, body.text)

    for child in list(body):
        tag = local_name(child.tag)
        if tag == "pb":
            flush_direct_items()
            n_raw = child.attrib.get("n")
            if n_raw is None:
                raise ValueError("Encountered pb without n")
            current = Page(int(n_raw))
            pages.append(current)
            append_text(direct_items, child.tail)
        elif tag in {"p", "head", "label", "div"}:
            flush_direct_items()
            add_block(child)
            append_text(direct_items, child.tail)
        elif tag == "note":
            flush_direct_items()
            add_block(child)
            append_text(direct_items, child.tail)
        elif tag == "fw":
            flush_direct_items()
            page = ensure_page()
            text = "".join(child.itertext())
            page.ranges.extend(parse_header_ranges(text))
            append_text(direct_items, child.tail)
        else:
            append_inline_child(child)
    flush_direct_items()
    return [page for page in pages if page.n]


def choose_chapter(
    cap: int,
    cap_end: int | None,
    page: Page,
    chapter_rows: dict[str, ChapterRow],
    last_key: tuple[int, int],
) -> tuple[str, bool]:
    end_cap = cap_end or cap
    for range_book, _start, end in page.ranges:
        if range_book == last_key[0] and cap < last_key[1] and last_key[1] < end:
            corrected = last_key[1] + 1
            corrected_n = f"{range_book}.{corrected}"
            return (corrected_n, corrected_n in chapter_rows)
    if last_key[0] and cap < last_key[1]:
        corrected = last_key[1] + 1
        corrected_n = f"{last_key[0]}.{corrected}"
        if corrected_n in chapter_rows:
            return (corrected_n, True)

    candidate_books = {
        int(n.split(".", 1)[0])
        for n in chapter_rows
        if int(n.split(".", 1)[1]) == cap
    }
    for range_book, start, end in page.ranges:
        if start <= cap <= end and start <= end_cap <= end:
            candidate_books.add(range_book)
    if last_key[0]:
        candidate_books.add(last_key[0])

    candidates: list[tuple[int, int, int, bool]] = []
    for book in candidate_books:
        chapter = cap
        matched = f"{book}.{chapter}" in chapter_rows
        score = 10
        header_match = any(
            book == range_book and start <= cap <= end and start <= end_cap <= end
            for range_book, start, end in page.ranges
        )
        if book < last_key[0]:
            header_match = False
        if (book, chapter) < last_key and not header_match:
            score += 100
        else:
            score -= 4
        for range_book, start, end in page.ranges:
            if book == range_book and start <= cap <= end and start <= end_cap <= end and book >= last_key[0]:
                score -= 200
            elif book == range_book:
                score -= 2
        if book == last_key[0]:
            score -= 5
        if matched:
            score -= 1
        candidates.append((score, book, chapter, matched))
    if not candidates:
        return (f"?.{cap}", False)
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    _, book, chapter, matched = candidates[0]
    if cap_end and cap_end != cap:
        end_matched = f"{book}.{cap_end}" in chapter_rows
        return (f"{book}.{chapter}-{book}.{cap_end}", matched and end_matched)
    return (f"{book}.{chapter}", matched)


def first_cap_match(items: list[Item]) -> re.Match[str] | None:
    text = plain_text(items).lstrip()
    return CAP_RE.match(text)


def make_tei_header() -> ET.Element:
    header = ET.Element("teiHeader")
    file_desc = ET.SubElement(header, "fileDesc")
    title_stmt = ET.SubElement(file_desc, "titleStmt")
    ET.SubElement(title_stmt, "title").text = "Commentarius in Pedanii Dioscoridis Anazarbei De Materia Medica"
    ET.SubElement(title_stmt, "author").text = "Kurt Sprengel"
    ET.SubElement(title_stmt, "date").text = "1830"
    source_desc = ET.SubElement(file_desc, "sourceDesc")
    bibl = ET.SubElement(source_desc, "bibl")
    ET.SubElement(bibl, "title").text = "Pedanii Dioscoridis Anazarbei De materia medica libri quinque"
    ET.SubElement(bibl, "editor").text = "Kurt Polykarp Joachim Sprengel"
    ET.SubElement(bibl, "publisher").text = "Car. Cnoblochii"
    ET.SubElement(bibl, "pubPlace").text = "Leipzig"
    ET.SubElement(bibl, "date").text = "1830"
    ET.SubElement(bibl, "note").text = "Tomus II: Commentarius"
    return header


def add_pb(parent: ET.Element, page: int, counters: Counters) -> None:
    pb = ET.SubElement(parent, "pb")
    pb.set("n", str(page))
    pb.set("facs", facs_url(page))
    pb.set("id", f"e-{counters.e}")
    counters.e += 1


def add_h2(parent: ET.Element, items: list[Item]) -> None:
    h2 = ET.SubElement(parent, "h2")
    fill_element(h2, copy_items(items))


def normalize_paragraph_items(items: list[Item], page: Page, counters: Counters, stats: BuildStats) -> list[Item]:
    out: list[Item] = []
    for item in items:
        if item.kind == "elem":
            normalize_note_markers_in_element(item.value, page, counters, stats)  # type: ignore[arg-type]
            out.append(item)
            continue
        if item.kind != "note":
            out.append(item)
            continue
        target = item.attrs.get("target", "")
        note_id = target[1:] if target.startswith("#") else target
        cite = re.sub(r"^fn", "", note_id)
        marker = Item(
            "note",
            attrs={
                "n": page.notes.get(note_id, [Item("text", item.attrs.get("display", ""))])[0].attrs.get("n", "")
                if False
                else (item.attrs.get("display", "").strip("[]") or ""),
                "display": f"[{item.attrs.get('display', '').strip('[]')}]",
                "corresp": f"#cite_note-{cite}",
                "id": f"ftn-{counters.ftn}",
            },
        )
        counters.ftn += 1
        stats.footnotes += 1
        out.append(marker)
    return clean_items_for_output(out)


def normalize_note_markers_in_element(el: ET.Element, page: Page, counters: Counters, stats: BuildStats) -> None:
    for child in list(el):
        if local_name(child.tag) == "note" and child.attrib.get("target"):
            target = child.attrib.pop("target")
            display = child.attrib.get("display", "")
            note_id = target[1:] if target.startswith("#") else target
            cite = re.sub(r"^fn", "", note_id)
            child.set("n", display.strip("[]"))
            child.set("display", f"[{display.strip('[]')}]")
            child.set("corresp", f"#cite_note-{cite}")
            child.set("id", f"ftn-{counters.ftn}")
            counters.ftn += 1
            stats.footnotes += 1
        normalize_note_markers_in_element(child, page, counters, stats)


def add_paragraph(parent: ET.Element, block: Block, page: Page, counters: Counters, stats: BuildStats) -> None:
    p = ET.SubElement(parent, "p")
    p.set("id", f"p-{counters.p}")
    counters.p += 1
    stats.paragraphs += 1
    fill_element(p, normalize_paragraph_items(copy_items(block.items), page, counters, stats))


def add_footnotes(parent: ET.Element, page: Page, counters: Counters) -> None:
    if not page.notes:
        return
    hr = ET.SubElement(parent, "hr")
    hr.set("id", f"hr-{counters.hr}")
    counters.hr += 1
    wrap = ET.SubElement(parent, "div")
    wrap.set("class", "mw-references-wrap")
    wrap.set("id", f"div-fn-{page.n}")
    ol = ET.SubElement(wrap, "ol")
    ol.set("class", "references")
    for note_id in sorted(page.notes, key=note_sort_key):
        cite = re.sub(r"^fn", "", note_id)
        li = ET.SubElement(ol, "li")
        li.set("id", f"cite_note-{cite}")
        span = ET.SubElement(li, "span")
        span.set("class", "reference-text")
        fill_element(span, clean_items_for_output(copy_items(page.notes[note_id])))


def note_sort_key(note_id: str) -> tuple[int, str]:
    match = re.search(r"_(\d+)([a-z]?)$", note_id)
    if match:
        return (int(match.group(1)), match.group(2))
    return (9999, note_id)


def start_chapter(
    parent: ET.Element,
    n: str,
    page: int,
    chapter_rows: dict[str, ChapterRow],
    counters: Counters,
    stats: BuildStats,
    matched: bool,
) -> ET.Element:
    first_n = n.split("-", 1)[0]
    row = chapter_rows.get(first_n)
    div = ET.SubElement(parent, "div")
    div.set("type", "chapter")
    div.set("n", first_n)
    div.set("tuid", f"SprengelComm:{n}")
    div.set("id", f"div-{counters.div}")
    if "-" in n:
        div.set("chapter-range", n)
    if row:
        div.set("corresp", f"sprengel1829_epidoc.xml#{row.xml_id}")
    counters.div += 1
    milestone = ET.SubElement(div, "milestone")
    milestone.set("type", "section")
    milestone.set("n", first_n)
    milestone.set("id", f"e-{counters.e}")
    counters.e += 1
    milestone.set("page", str(page))
    if row:
        milestone.set("display", row.label_la)
        milestone.set("display-grc", row.label_grc)
    else:
        milestone.set("display", first_n)
    stats.chapters += 1
    if not matched:
        stats.unmatched_chapters.append(n)
    return div


def build(source: Path, chapter_table: Path) -> tuple[ET.ElementTree, BuildStats]:
    chapter_rows = load_chapter_table(chapter_table)
    pages = extract_pages(source)
    counters = Counters()
    stats = BuildStats(pages=len(pages))

    root = ET.Element("TEI")
    root.append(make_tei_header())
    text = ET.SubElement(root, "text")
    current_container = text
    current_chapter: ET.Element | None = None
    last_key = (0, 0)
    in_annotations = False

    for page in pages:
        add_pb(current_container, page.n, counters)
        for raw_block in page.blocks:
            for block in split_chapter_blocks(raw_block):
                block_text = plain_text(block.items)
                role = heading_role(block_text) or block.role
                if role == "annotationes":
                    current_chapter = None
                    current_container = text
                    in_annotations = True
                    add_h2(text, block.items)
                    continue
                if role == "h2":
                    add_h2(current_container, block.items)
                    continue
                cap_match = None if in_annotations else first_cap_match(block.items)
                if cap_match:
                    cap = roman_to_int(cap_match.group(1))
                    cap_end_raw = cap_match.group(2) or cap_match.group(3)
                    cap_end = roman_to_int(cap_end_raw) if cap_end_raw else None
                    n, matched = choose_chapter(cap, cap_end, page, chapter_rows, last_key)
                    if not n.startswith("?."):
                        first = n.split("-", 1)[0]
                        book_s, chapter_s = first.split(".")
                        last_key = (int(book_s), int(chapter_s))
                    current_chapter = start_chapter(text, n, page.n, chapter_rows, counters, stats, matched)
                    current_container = current_chapter
                add_paragraph(current_container, block, page, counters, stats)
        add_footnotes(current_container, page, counters)

    wrap_bare_greek(root)
    validate(root)
    return ET.ElementTree(root), stats


def is_foreign_grc(el: ET.Element) -> bool:
    return local_name(el.tag) == "foreign" and el.attrib.get(XML_LANG) == "grc"


def make_foreign(text: str) -> ET.Element:
    el = ET.Element("foreign")
    el.set(XML_LANG, "grc")
    el.text = text
    return el


def split_greek_text(text: str) -> list[str | ET.Element]:
    parts: list[str | ET.Element] = []
    pos = 0
    for match in GREEK_RE.finditer(text):
        if match.start() > pos:
            parts.append(text[pos : match.start()])
        parts.append(make_foreign(match.group(0)))
        pos = match.end()
    if pos < len(text):
        parts.append(text[pos:])
    return parts


def wrap_parent_text(parent: ET.Element) -> None:
    if not parent.text or not GREEK_RE.search(parent.text):
        return
    parts = split_greek_text(parent.text)
    parent.text = ""
    insert_at = 0
    last: ET.Element | None = None
    for part in parts:
        if isinstance(part, str):
            if last is None:
                parent.text = (parent.text or "") + part
            else:
                last.tail = (last.tail or "") + part
        else:
            parent.insert(insert_at, part)
            insert_at += 1
            last = part


def wrap_child_tail(parent: ET.Element, child: ET.Element, index: int) -> int:
    if not child.tail or not GREEK_RE.search(child.tail):
        return index
    parts = split_greek_text(child.tail)
    child.tail = ""
    last = child
    insert_at = index + 1
    inserted = 0
    for part in parts:
        if isinstance(part, str):
            last.tail = (last.tail or "") + part
        else:
            parent.insert(insert_at, part)
            insert_at += 1
            inserted += 1
            last = part
    return inserted


def wrap_bare_greek(root: ET.Element) -> None:
    def visit(parent: ET.Element, inside_foreign: bool = False) -> None:
        inside = inside_foreign or local_name(parent.tag) == "foreign"
        if not inside:
            wrap_parent_text(parent)
        for child in list(parent):
            visit(child, inside)
        if not inside:
            for child in reversed(list(parent)):
                wrap_child_tail(parent, child, list(parent).index(child))

    visit(root)


def iter_ids(root: ET.Element) -> Iterable[str]:
    for el in root.iter():
        for attr in ID_ATTRS:
            if attr in el.attrib:
                yield el.attrib[attr]


def has_bare_greek(root: ET.Element) -> bool:
    bare = False

    def visit(el: ET.Element, inside_grc: bool = False) -> None:
        nonlocal bare
        inside = inside_grc or is_foreign_grc(el)
        if not inside and el.text and GREEK_RE.search(el.text):
            bare = True
        for child in list(el):
            visit(child, inside)
            if not inside and child.tail and GREEK_RE.search(child.tail):
                bare = True

    visit(root)
    return bare


def validate(root: ET.Element) -> None:
    ids = list(iter_ids(root))
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate ids: {', '.join(duplicate_ids[:10])}")
    missing_facs = [pb.attrib.get("n", "?") for pb in root.findall(".//pb") if not pb.attrib.get("facs")]
    if missing_facs:
        raise ValueError(f"pb without facs: {', '.join(missing_facs[:10])}")
    if root.findall(".//lb"):
        raise ValueError("Output still contains lb elements")
    if "ϑ" in ET.tostring(root, encoding="unicode"):
        raise ValueError("Output still contains U+03D1 theta symbol")
    if has_bare_greek(root):
        raise ValueError("Output still contains bare Greek text outside foreign xml:lang=\"grc\"")
    li_ids = [li.attrib.get("id") for li in root.findall(".//li")]
    for note in root.findall(".//note"):
        corresp = note.attrib.get("corresp")
        if not corresp:
            continue
        target = corresp[1:] if corresp.startswith("#") else corresp
        if li_ids.count(target) != 1:
            raise ValueError(f"Inline note target does not resolve exactly once: {corresp}")
    for div in root.findall(".//div"):
        if div.attrib.get("type") == "chapter" and div.find("milestone") is None:
            raise ValueError(f"Chapter div has no milestone: {div.attrib.get('id')}")


def indent(elem: ET.Element, level: int = 0) -> None:
    space = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = space + "  "
        for child in elem:
            indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = space + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = space
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = space


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--chapter-table", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tree, stats = build(args.source, args.chapter_table)
    indent(tree.getroot())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"wrote: {args.output}")
    print(f"pages: {stats.pages}")
    print(f"chapters/sections detected: {stats.chapters}")
    print(f"footnotes: {stats.footnotes}")
    print(f"paragraphs: {stats.paragraphs}")
    if stats.unmatched_chapters:
        print("unmatched chapter headings:")
        for n in stats.unmatched_chapters:
            print(f"  {n}")
    else:
        print("unmatched chapter headings: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
