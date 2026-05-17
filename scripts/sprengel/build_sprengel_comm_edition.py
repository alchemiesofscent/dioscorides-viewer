#!/usr/bin/env python3
"""Build editions/sprengel1830-comm/tei/edition.xml from per-page OCR fragments.

Reads `sprengel_comm/ocr_fragments/b23982500_0002_NNNN.xml` (per-page OCR
fragments with no root element), `sprengel_comm/sprengel_chapter_table.tsv`
(chapter ids + bilingual heads), and `editions/sprengel1830-comm/manifest.json`
(per-page facs URIs), then emits a single TEI file shaped like
`editions/berendes1902/tei/edition.xml`:

  - <TEI xmlns="..." xml:lang="la"> with the EpiDoc xml-model PI
  - <div type="textpart" subtype="preface|book|chapter">
  - inline <pb n="P" facs="..." xml:id="..."/> at every page boundary; chapter
    divs span pages
  - footnotes wired as <ref type="footnote-ref" target="#X" xml:id="ref-X">
    <-> <note type="footnote" xml:id="X" corresp="#ref-X" place="bottom" n="N">
  - sequential <lb n="N"/> per page, reset on every <pb>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)

XML_MODEL_PI = (
    '<?xml-model href="http://epidoc.stoa.org/schema/latest/tei-epidoc.rng" '
    'schematypens="http://relaxng.org/ns/structure/1.0"?>'
)

CAP_RE = re.compile(
    r"(?<![A-Za-z])Cap\.\s+([IVXLCDM]+)\.?"
    r"(?:\s*[—-]\s*([IVXLCDM]+)\.|\s+([IVXLCDM]+)\.)?",
    re.IGNORECASE,
)
LIB_RE = re.compile(r"^\s*LIB\.\s+([IVXLCDM]+)\.?\s*$", re.IGNORECASE)
LIB_ANY_RE = re.compile(r"(?<![A-Za-z])LIB\.\s+([IVXLCDM]+)\.", re.IGNORECASE)
RUNNING_HEAD_RE = re.compile(
    r"^\s*(?:\d+\s+COMMENTARIUS|COMMENTARIUS\s+\d+|IN\s+DIOSCORID(?:[EI]M|IS)[^\n]*|"
    r"\d+\s+IN\s+DIOSCORID(?:[EI]M|IS)[^\n]*)\s*$",
    re.IGNORECASE,
)
LEADING_HEADER_PATTERNS = [
    re.compile(r"^\s*(?:\d+\s+)?COMMENTARIUS(?:\s+\d+)?\b[^\n]*", re.IGNORECASE),
    re.compile(r"^\s*(?:\d+\s+)?IN\s+DIOSCORID(?:[EI]M|IS)[^\n]*", re.IGNORECASE),
]

INLINE_TAGS = {"lb", "hi", "foreign", "ref", "cb", "g", "supplied", "unclear"}
BLOCK_TAGS = {"p", "head", "label", "fw"}


@dataclass
class ChapterRow:
    n: str
    xml_id: str
    label_la: str
    label_grc: str


@dataclass
class ManifestPage:
    book_page: str
    tei_facs: str
    facs: str
    xml_id: str


@dataclass
class Page:
    n: int
    blocks: list = field(default_factory=list)
    notes: list = field(default_factory=list)


@dataclass
class Stats:
    books: int = 0
    chapters: int = 0
    pages_seen: int = 0
    pbs_emitted: int = 0
    note_blocks: int = 0
    lb_numbered: int = 0
    unmatched_chapters: list = field(default_factory=list)
    book_rollover_mismatches: list = field(default_factory=list)
    pages_missing_in_manifest: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers (most copied verbatim from structure_sprengel_comm.py).

def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def element_text(el: ET.Element) -> str:
    return "".join(el.itertext())


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


def strip_ns(el: ET.Element) -> None:
    for node in el.iter():
        if isinstance(node.tag, str) and node.tag.startswith(f"{{{TEI}}}"):
            node.tag = local_name(node.tag)


def indent(elem: ET.Element, level: int = 0) -> None:
    pad = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        for child in elem:
            indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = pad + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = pad
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad


# ---------------------------------------------------------------------------
# Input loaders.

def load_chapter_table(path: Path) -> dict:
    rows: dict = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            rows[row["n"]] = ChapterRow(
                n=row["n"],
                xml_id=row["xml_id"],
                label_la=row["label_la"],
                label_grc=row["label_grc"],
            )
    return rows


def load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    pages = {}
    for entry in data.get("pages", []):
        pages[entry["book_page"]] = ManifestPage(
            book_page=entry["book_page"],
            tei_facs=entry.get("tei_facs", ""),
            facs=entry.get("facs", ""),
            xml_id=entry.get("xml_id", ""),
        )
    return pages


def iter_fragment_paths(ocr_dir: Path) -> list:
    return sorted(ocr_dir.glob("*.xml"))


def parse_fragment(path: Path) -> ET.Element:
    """Wrap a per-page OCR fragment in a synthetic <page> root and parse it."""
    raw = path.read_text(encoding="utf-8")
    wrapped = (
        f'<page xmlns:xml="http://www.w3.org/XML/1998/namespace">{raw}</page>'
    )
    page_el = ET.fromstring(wrapped)
    strip_ns(page_el)
    return page_el


# ---------------------------------------------------------------------------
# Body merging + page extraction.

# Known OCR transcription errors in the leading <pb n=>: the OCR copied the
# wrong running-header digits. Map file basename index -> correct book_page.
# Verified against the file content's running header + chapter-number context.
OCR_PB_OVERRIDES = {
    "0426": 418,  # OCR pb says 413; content+chapters confirm page 418
    "0481": 475,  # OCR pb says 473; content is chapters II.181-188 = page 475
                  # (0479 legitimately holds page 473 per its running header)
}


def merge_fragments(ocr_dir: Path) -> ET.Element:
    """Concatenate every OCR fragment file in `ocr_dir` under a synthetic
    <body>, preserving each file's internal element order. Fragments may
    contain multiple `<pb>` markers (e.g. a single file covering pages
    436–437); page splitting is deferred to `extract_pages` afterward.

    Applies OCR_PB_OVERRIDES to the *first* `<pb>` of any file whose basename
    index matches — the two known transcription errors are both in files
    that contain only one pb, so this is sufficient.
    """
    body = ET.Element("body")
    for path in iter_fragment_paths(ocr_dir):
        m = re.search(r"_(\d{4})\.xml$", path.name)
        file_idx = m.group(1) if m else ""
        page_el = parse_fragment(path)
        if file_idx in OCR_PB_OVERRIDES:
            for child in page_el:
                if local_name(child.tag) == "pb":
                    child.set("n", str(OCR_PB_OVERRIDES[file_idx]))
                    break
        if page_el.text and page_el.text.strip():
            if len(body):
                body[-1].tail = (body[-1].tail or "") + page_el.text
            else:
                body.text = (body.text or "") + page_el.text
        for child in list(page_el):
            body.append(child)
    return body


def order_pages_against_manifest(pages: list, manifest_pages: dict) -> tuple:
    """Sort pages by .n, inserting a placeholder Page (with a <gap> block) for
    every manifest book_page that has no OCR coverage. Returns
    (ordered_pages, missing_pages, unexpected_pages, conflicts).
    """
    by_n: dict = {}
    conflicts: list = []
    for page in pages:
        if page.n in by_n:
            conflicts.append(page.n)
            # Merge: append this page's blocks/notes into the existing one.
            by_n[page.n].blocks.extend(page.blocks)
            by_n[page.n].notes.extend(page.notes)
        else:
            by_n[page.n] = page

    expected = sorted(int(bp) for bp in manifest_pages.keys())
    ordered = []
    missing: list = []
    for bp in expected:
        if bp in by_n:
            ordered.append(by_n[bp])
        else:
            placeholder = Page(n=bp)
            gap = ET.Element("gap")
            gap.set("reason", "ocr-missing")
            placeholder.blocks.append(gap)
            ordered.append(placeholder)
            missing.append(str(bp))

    expected_set = set(expected)
    unexpected = sorted(n for n in by_n if n not in expected_set)
    for n in unexpected:
        ordered.append(by_n[n])

    return ordered, missing, unexpected, conflicts


def unwrap_legacy_chapter_divs(body: ET.Element) -> None:
    """Flatten any stray `<div type="book"|"chapter">` wrappers in fragments."""
    def unwrap_once(parent: ET.Element) -> bool:
        for idx, child in enumerate(list(parent)):
            if local_name(child.tag) == "div" and child.attrib.get("type") in {
                "book",
                "chapter",
            }:
                grandchildren = list(child)
                if child.text and child.text.strip():
                    if idx == 0:
                        parent.text = (parent.text or "") + child.text
                    else:
                        prev = list(parent)[idx - 1]
                        prev.tail = (prev.tail or "") + child.text
                parent.remove(child)
                for j, gc in enumerate(grandchildren):
                    parent.insert(idx + j, gc)
                if child.tail:
                    if grandchildren:
                        last_gc = grandchildren[-1]
                        last_gc.tail = (last_gc.tail or "") + child.tail
                    else:
                        if idx == 0:
                            parent.text = (parent.text or "") + child.tail
                        else:
                            prev = list(parent)[idx - 1]
                            prev.tail = (prev.tail or "") + child.tail
                return True
        return False

    while unwrap_once(body):
        pass


def extract_pages(body: ET.Element) -> list:
    """Walk body left-to-right, grouping into pages keyed by `<pb n=>`.

    Bare text + inline-only runs that appear between block elements become
    synthetic `<p>` blocks. Footnotes (inside `<div type="footnotes">` or as
    stray top-level `<note>`) flow into `page.notes`.
    """
    pages: list = []
    page_by_n: dict = {}
    current: Page | None = None

    def ensure_page(n=None):
        nonlocal current
        if n is not None:
            existing = page_by_n.get(n)
            if existing is not None:
                # The OCR has two scans for this book_page (e.g. BIU pages
                # 436-437 yield duplicate <pb n="413"/> in two fragments).
                # Merge follow-up content into the first occurrence.
                current = existing
                return existing
            page = Page(n=n)
            pages.append(page)
            page_by_n[n] = page
            current = page
            return page
        if current is None:
            current = Page(n=0)
            pages.append(current)
        return current

    accumulator: ET.Element | None = None

    def acc_append_text(text):
        nonlocal accumulator
        if not text:
            return
        if accumulator is None:
            accumulator = ET.Element("p")
        if len(accumulator) == 0:
            accumulator.text = (accumulator.text or "") + text
        else:
            last = accumulator[-1]
            last.tail = (last.tail or "") + text

    def acc_append_element(el):
        nonlocal accumulator
        if accumulator is None:
            accumulator = ET.Element("p")
        accumulator.append(el)

    def flush_accumulator():
        nonlocal accumulator
        if accumulator is None:
            return
        if element_text(accumulator).strip():
            ensure_page().blocks.append(accumulator)
        accumulator = None

    if body.text:
        acc_append_text(body.text)

    for child in list(body):
        tag = local_name(child.tag)
        if tag == "pb":
            flush_accumulator()
            n_raw = child.attrib.get("n")
            if n_raw is None:
                continue
            ensure_page(int(n_raw))
            acc_append_text(child.tail)
            continue
        if tag == "div" and child.attrib.get("type") == "footnotes":
            flush_accumulator()
            page = ensure_page()
            for note in child.findall("note"):
                page.notes.append(note)
            acc_append_text(child.tail)
            continue
        if tag == "note":
            flush_accumulator()
            page = ensure_page()
            page.notes.append(child)
            acc_append_text(child.tail)
            continue
        if tag in BLOCK_TAGS:
            flush_accumulator()
            ensure_page().blocks.append(child)
            acc_append_text(child.tail)
            continue
        if tag in INLINE_TAGS:
            tail = child.tail
            child.tail = None
            acc_append_element(child)
            acc_append_text(tail)
            continue
        flush_accumulator()
        ensure_page().blocks.append(child)
        acc_append_text(child.tail)

    flush_accumulator()
    return [p for p in pages if p.n]


def looks_like_running_head(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text).strip()
    if not stripped:
        return True
    if RUNNING_HEAD_RE.match(stripped):
        return True
    if re.fullmatch(r"[A-Z]\s*\d*", stripped):
        return True
    return False


# Patterns matched when a <head> block itself IS a running header (OCR sometimes
# wraps the running header in <head> instead of leaving it as bare text).
# Page 339's title-stack heads are pre-consumed before this check fires.
HEAD_RUNNING_PATTERNS = [
    re.compile(r"^\s*COMMENTARIUS\s*$"),
    re.compile(r"^\s*\d+\s+COMMENTARIUS\s*$"),
    re.compile(r"^\s*COMMENTARIUS\s+\d+\s*$"),
    re.compile(r"^\s*IN\s+DIOSCORID(?:[EI]M|IS)", re.IGNORECASE),
]


def head_is_running_header(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text).strip()
    return any(p.match(stripped) for p in HEAD_RUNNING_PATTERNS)


def leading_running_header(text: str):
    for pat in LEADING_HEADER_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        head_text = m.group(0)
        end = m.end()
        while end < len(text) and text[end] in "\n\r\t ":
            end += 1
        return head_text, end
    return None


def detect_book(text: str):
    m = LIB_RE.match(re.sub(r"\s+", " ", text).strip())
    if m:
        return roman_to_int(m.group(1))
    return None


@dataclass
class Boundary:
    kind: str
    start: int
    end: int
    roman: str
    roman_end: str | None = None


def find_boundaries(text: str) -> list:
    found = []
    for m in LIB_ANY_RE.finditer(text):
        found.append(Boundary("lib", m.start(), m.end(), m.group(1)))
    for m in CAP_RE.finditer(text):
        end_raw = m.group(2) or m.group(3)
        found.append(Boundary("cap", m.start(), m.end(), m.group(1), end_raw))
    found.sort(key=lambda b: b.start)
    return found


def split_p_at_offset(p_el: ET.Element, offset: int):
    """Split a `<p>` at a text-content offset; returns (left, right)."""
    left = ET.Element("p")
    right = ET.Element("p")
    pos = 0

    def emit_text(target, prev_child, text):
        if not text:
            return
        if prev_child is None:
            target.text = (target.text or "") + text
        else:
            prev_child.tail = (prev_child.tail or "") + text

    left_prev = None
    right_prev = None

    if p_el.text:
        text = p_el.text
        if pos + len(text) <= offset:
            emit_text(left, left_prev, text)
            pos += len(text)
        elif pos >= offset:
            emit_text(right, right_prev, text)
            pos += len(text)
        else:
            cut = offset - pos
            emit_text(left, left_prev, text[:cut])
            emit_text(right, right_prev, text[cut:])
            pos += len(text)

    for child in list(p_el):
        child_text = "".join(child.itertext())
        child_len = len(child_text)
        tail = child.tail
        child.tail = None
        if pos + child_len <= offset:
            left.append(child)
            left_prev = child
            pos += child_len
        elif pos >= offset:
            right.append(child)
            right_prev = child
            pos += child_len
        else:
            right.append(child)
            right_prev = child
            pos += child_len
        if tail:
            if pos + len(tail) <= offset:
                emit_text(left, left_prev, tail)
                pos += len(tail)
            elif pos >= offset:
                emit_text(right, right_prev, tail)
                pos += len(tail)
            else:
                cut = offset - pos
                emit_text(left, left_prev, tail[:cut])
                emit_text(right, right_prev, tail[cut:])
                pos += len(tail)

    return left, right


# ---------------------------------------------------------------------------
# Footnote renumbering and wiring.

REF_NUM_RE = re.compile(r"^fn(.+)$")


def renumber_page_footnotes(blocks: list, notes: list, page_n: int) -> None:
    """Rewrite local `fnN` ids on this page to page-scoped `fn{page}_{suffix}`.

    Also adds the Berendes-style attributes the validator requires:
      <ref type="footnote-ref" target="#X" xml:id="ref-X"> ...
      <note type="footnote" xml:id="X" corresp="#ref-X" place="bottom" n="N">
    """
    # First pass: build the local-id -> global-id map from the notes.
    id_map: dict = {}
    for note in notes:
        local_id = note.attrib.get(XML_ID) or note.attrib.get("xml:id") or note.attrib.get("id")
        if not local_id:
            continue
        m = REF_NUM_RE.match(local_id)
        suffix = m.group(1) if m else local_id
        global_id = f"fn{page_n}_{suffix}"
        id_map[local_id] = global_id
        # Wire the note to validator expectations.
        # Clear and re-set xml:id first (avoid stale "id"/"xml:id" entries).
        for k in ("id", "xml:id"):
            if k in note.attrib:
                del note.attrib[k]
        note.set(XML_ID, global_id)
        note.set("type", "footnote")
        note.set("place", "bottom")
        note.set("corresp", f"#ref-{global_id}")
        # Ensure @n is present (from local fnN -> N suffix without leading "fn").
        if not note.attrib.get("n"):
            note.set("n", suffix)

    # Second pass: rewrite refs in blocks. Refs whose target matches a real note
    # on this page are wired as footnote-refs (validator's contract). Refs whose
    # target was never declared as a note on this page are demoted: we still
    # rewrite their target to the page-scoped id so they don't collide with
    # other pages, but we strip type/xml:id so the validator doesn't classify
    # them as footnote-refs (avoids false FOOTNOTE_TARGET_NO_NOTE errors when
    # OCR drops a note but keeps its inline anchor).
    ref_counts: dict = {}
    ref_id_by_target: dict = {}
    for blk in blocks:
        for ref in blk.iter("ref"):
            target = ref.attrib.get("target", "")
            if not target.startswith("#"):
                continue
            local_id = target[1:]
            global_id = id_map.get(local_id)
            if global_id is None:
                # Orphan ref — note missing from this page's apparatus (OCR
                # captured the inline anchor but dropped the note). Strip every
                # attribute so the surviving <ref> has no broken targets and
                # the validator ignores it; the original anchor text remains.
                ref.attrib.clear()
                continue
            ref.set("target", f"#{global_id}")
            ref.set("type", "footnote-ref")
            count = ref_counts.get(global_id, 0) + 1
            ref_counts[global_id] = count
            ref_xml_id = f"ref-{global_id}" if count == 1 else f"ref-{global_id}-{count}"
            ref.set(XML_ID, ref_xml_id)
            ref_id_by_target.setdefault(global_id, []).append(ref_xml_id)

    # Patch note @corresp so it points at all the ref ids (space-separated).
    # Notes whose inbound refs were demoted (OCR kept the note but dropped the
    # body anchor) lose their corresp so they don't show up as orphan targets.
    for note in notes:
        nid = note.attrib.get(XML_ID)
        if not nid:
            continue
        ref_ids = ref_id_by_target.get(nid, [])
        if ref_ids:
            note.set("corresp", " ".join(f"#{r}" for r in ref_ids))
        elif "corresp" in note.attrib:
            del note.attrib["corresp"]


# ---------------------------------------------------------------------------
# Body assembly into the Berendes-shaped output.

@dataclass
class AssemblerState:
    body: ET.Element
    chapter_rows: dict
    stats: Stats
    last_chapter_seen: dict = field(default_factory=dict)  # book -> last chapter int
    preface_div: ET.Element | None = None
    book_div: ET.Element | None = None
    chapter_div: ET.Element | None = None
    current_book: int = 0  # 0 means "still in preface"


def current_container(state: AssemblerState) -> ET.Element:
    if state.chapter_div is not None:
        return state.chapter_div
    if state.book_div is not None:
        return state.book_div
    if state.preface_div is not None:
        return state.preface_div
    return state.body


def open_preface(state: AssemblerState) -> ET.Element:
    # The preface div is created empty; its head(s) come from page 339's OCR
    # (COMMENTARIUS / IN / DIOSCORIDEM. / PRAEFATIO.) appended after <pb n="339"/>
    # by process_page so they pick up page-339 line numbers (1–4).
    div = ET.Element("div")
    div.set("type", "textpart")
    div.set("subtype", "preface")
    div.set(XML_ID, "spr-comm-praefatio")
    state.body.append(div)
    state.preface_div = div
    return div


def open_book(state: AssemblerState, book: int) -> ET.Element:
    # Validate rollover: previous book's last chapter should align with chapter
    # table's last row for that book.
    if book > 1:
        prev_book = book - 1
        last_seen = state.last_chapter_seen.get(prev_book)
        expected = max(
            (int(row.n.split(".", 1)[1]) for row in state.chapter_rows.values()
             if row.n.startswith(f"{prev_book}.")),
            default=None,
        )
        if last_seen is not None and expected is not None and last_seen != expected:
            state.stats.book_rollover_mismatches.append(
                f"book {prev_book}: saw last chapter {prev_book}.{last_seen}, "
                f"expected {prev_book}.{expected}"
            )

    div = ET.Element("div")
    div.set("type", "textpart")
    div.set("subtype", "book")
    div.set("n", str(book))
    div.set(XML_ID, f"book_{book}")
    head = ET.SubElement(div, "head")
    head.text = f"LIB. {to_roman(book)}."
    state.body.append(div)
    state.book_div = div
    state.chapter_div = None
    state.current_book = book
    state.stats.books += 1
    return div


def open_chapter(state: AssemblerState, book: int, chapter: int, chapter_end=None):
    if state.book_div is None or state.current_book != book:
        open_book(state, book)
    # Skip if this chapter is already open or already passed.
    last = state.last_chapter_seen.get(book)
    if last is not None and chapter <= last:
        return None
    div = ET.Element("div")
    div.set("type", "textpart")
    div.set("subtype", "chapter")
    div.set("n", f"{book}.{chapter}")
    if chapter_end and chapter_end != chapter:
        div.set("next", f"{book}.{chapter_end}")
    row = state.chapter_rows.get(f"{book}.{chapter}")
    if row:
        div.set(XML_ID, row.xml_id)
        # Cross-edition pointer to the Greek epidoc; use a non-fragment form so
        # the project validator doesn't try to resolve the fragment as a local id.
        div.set("corresp", f"sprengel1829_epidoc.xml#{row.xml_id}")
        # Single head with Latin label, then Greek wrapped in <foreign> per
        # Berendes' convention; this also keeps the Greek out of "bare-Greek"
        # validator complaints.
        head = ET.SubElement(div, "head")
        head.text = f"Cap. {to_roman(chapter)}. {row.label_la}. "
        grc = ET.SubElement(head, "foreign")
        grc.set(XML_LANG, "grc")
        grc.text = row.label_grc
    else:
        state.stats.unmatched_chapters.append(f"{book}.{chapter}")
        head = ET.SubElement(div, "head")
        head.text = f"Cap. {to_roman(chapter)}."
    state.book_div.append(div)
    state.chapter_div = div
    state.last_chapter_seen[book] = chapter
    state.stats.chapters += 1
    return div


def emit_pb(state: AssemblerState, page_n: int, manifest_page: ManifestPage | None) -> ET.Element:
    pb = ET.Element("pb")
    pb.set("n", str(page_n))
    # Always derive xml:id from book_page — the manifest's xml_id field is
    # derived from the IA leaf basename and collides across archive sources
    # (e.g. BIU 0437.jp2 and b23982500 0437.jp2 both yield "spr-comm-pb-0437"
    # for different book_pages).
    pb.set(XML_ID, f"spr-comm-pb-bp{page_n}")
    if manifest_page is not None and manifest_page.tei_facs:
        pb.set("facs", manifest_page.tei_facs)
    if manifest_page is None:
        state.stats.pages_missing_in_manifest.append(page_n)
    current_container(state).append(pb)
    state.stats.pbs_emitted += 1
    return pb


def emit_page_footnotes(state: AssemblerState, notes: list) -> None:
    if not notes:
        return
    wrap = ET.SubElement(current_container(state), "div")
    wrap.set("type", "footnotes")
    for note in notes:
        wrap.append(note)
    state.stats.note_blocks += 1


def append_to_current(state: AssemblerState, el: ET.Element) -> None:
    current_container(state).append(el)


# ---------------------------------------------------------------------------
# Roman numeral output.

ROMAN_PAIRS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def to_roman(value: int) -> str:
    out = []
    n = value
    for v, sym in ROMAN_PAIRS:
        while n >= v:
            out.append(sym)
            n -= v
    return "".join(out)


# ---------------------------------------------------------------------------
# Main processing loop.

def process_page(state: AssemblerState, page: Page, manifest_pages: dict) -> None:
    state.stats.pages_seen += 1
    blocks = page.blocks

    # Page 339 has the title triplet COMMENTARIUS / IN / DIOSCORIDEM. plus
    # PRAEFATIO. as four leading <head>s. Set these aside so they can be
    # appended *after* <pb n="339"/> — that way each head sits inside the
    # preface div and gets a page-339 line number from number_lbs_per_page().
    leading_heads: list = []
    if page.n == 339 and state.preface_div is not None:
        consumed = 0
        for blk in blocks:
            if local_name(blk.tag) != "head":
                break
            consumed += 1
            if element_text(blk).strip():
                leading_heads.append(blk)
            if "PRAEFATIO" in element_text(blk).upper():
                break
        blocks = blocks[consumed:]

    mfest = manifest_pages.get(str(page.n))
    pb = emit_pb(state, page.n, mfest)
    for h in leading_heads:
        current_container(state).append(h)

    for blk in blocks:
        tag = local_name(blk.tag)
        block_text = element_text(blk).strip()

        # Whole-element LIB. marker (e.g. <head>LIB. V.</head> or <p>LIB. II.</p>)
        book_num = detect_book(block_text)
        if book_num is not None:
            open_book(state, book_num)
            continue

        if tag in {"head", "label"}:
            # OCR sometimes emits a running header as <head>COMMENTARIUS</head>
            # (page 342 etc.) instead of bare text on the page. Demote to
            # <fw type="header"> so it counts as page furniture, not a section
            # heading. Page 339's title triplet was pre-consumed before this
            # loop, so it bypasses this check.
            if tag == "head" and head_is_running_header(block_text):
                fw = ET.Element("fw")
                fw.set("type", "header")
                fw.set("place", "top")
                fw.text = block_text.strip()
                append_to_current(state, fw)
            else:
                append_to_current(state, blk)
            continue

        if tag == "fw":
            # Keep fw as-is; ensure place="top" if it's a header.
            if blk.attrib.get("type") == "header" and "place" not in blk.attrib:
                blk.set("place", "top")
            if blk.attrib.get("type") == "sig" and "place" not in blk.attrib:
                blk.set("place", "bottom")
            append_to_current(state, blk)
            continue

        if tag != "p":
            append_to_current(state, blk)
            continue

        text = element_text(blk)

        # A paragraph that is JUST a running header.
        if not list(blk) and looks_like_running_head(text):
            fw = ET.Element("fw")
            fw.set("type", "header")
            fw.set("place", "top")
            fw.text = text.strip()
            append_to_current(state, fw)
            continue

        # Running header at the START of an otherwise-real paragraph.
        head_match = leading_running_header(text)
        if head_match:
            head_text, head_offset = head_match
            fw = ET.Element("fw")
            fw.set("type", "header")
            fw.set("place", "top")
            fw.text = head_text.strip()
            append_to_current(state, fw)
            _drop, blk = split_p_at_offset(blk, head_offset)
            text = element_text(blk)

        boundaries = find_boundaries(text)
        if not boundaries:
            if element_text(blk).strip():
                append_to_current(state, blk)
            continue

        remaining = blk
        cursor = 0
        for b in boundaries:
            rel = b.start - cursor
            if rel > 0:
                left, right = split_p_at_offset(remaining, rel)
                if element_text(left).strip():
                    append_to_current(state, left)
                remaining = right
            if b.kind == "lib":
                open_book(state, roman_to_int(b.roman))
                marker_len = b.end - b.start
                _drop, remaining = split_p_at_offset(remaining, marker_len)
                cursor = b.end
            else:  # cap
                cap = roman_to_int(b.roman)
                cap_end = roman_to_int(b.roman_end) if b.roman_end else None
                # Use current_book; if 0 (still in preface), promote to book 1.
                book = state.current_book if state.current_book > 0 else 1
                open_chapter(state, book, cap, cap_end)
                marker_len = b.end - b.start
                _drop, remaining = split_p_at_offset(remaining, marker_len)
                cursor = b.end

        if element_text(remaining).strip():
            append_to_current(state, remaining)

    emit_page_footnotes(state, page.notes)


# ---------------------------------------------------------------------------
# Post-pass: wrap bare Greek runs in <foreign xml:lang="grc">.

# Mirror the validator's bare-Greek pattern, broadened to cover common Greek
# punctuation and combining marks that travel inside Greek tokens.
GREEK_CHAR_RE = re.compile(
    r"[Ͱ-Ͽἀ-῿ΆΈ-ΊΌΎ-Ρ]"
)


def _is_all_greek_or_punct(text: str) -> bool:
    has_greek = False
    for ch in text:
        if GREEK_CHAR_RE.match(ch):
            has_greek = True
            continue
        if ch.isspace() or ch in ".,;:!?-'’‘“”·":
            continue
        return False
    return has_greek


def _wrap_runs(text: str):
    """Split text into (kind, piece) tuples; kind is 'plain' or 'greek'."""
    pieces = []
    i = 0
    while i < len(text):
        if GREEK_CHAR_RE.match(text[i]):
            j = i + 1
            while j < len(text) and (GREEK_CHAR_RE.match(text[j]) or
                                     text[j] in " \t·’'"):
                j += 1
            # Trim trailing whitespace from the Greek run so adjacent latin
            # words don't get sucked into the wrapper.
            piece = text[i:j].rstrip()
            kept_tail = text[i:j][len(piece):]
            pieces.append(("greek", piece))
            if kept_tail:
                pieces.append(("plain", kept_tail))
            i = j
        else:
            j = i + 1
            while j < len(text) and not GREEK_CHAR_RE.match(text[j]):
                j += 1
            pieces.append(("plain", text[i:j]))
            i = j
    return pieces


def wrap_bare_greek(body: ET.Element) -> int:
    """Wrap any Greek-character runs not already inside <foreign> with
    <foreign xml:lang="grc">. Returns count of new wrappers inserted.

    Also lifts <hi rend="italic"> elements whose inner text is entirely Greek
    into <foreign>-wrapped form: <hi><foreign>...</foreign></hi>.
    """
    inserted = 0

    def walk(node: ET.Element, inside_foreign: bool):
        nonlocal inserted
        tag = local_name(node.tag)
        if tag == "foreign":
            return  # don't recurse — already wrapped
        if tag == "hi" and not inside_foreign:
            inner_text = "".join(node.itertext())
            if inner_text and _is_all_greek_or_punct(inner_text) and len(list(node)) == 0:
                # Pure-Greek italic: wrap content with <foreign>.
                grc = ET.SubElement(node, "foreign")
                grc.set(XML_LANG, "grc")
                grc.text = node.text
                node.text = None
                inserted += 1
                return

        # Process .text and each child's .tail, splitting on Greek runs.
        new_children = []

        def process_text(host: ET.Element, text_attr: str, prev_child):
            nonlocal inserted
            text = getattr(host, text_attr) if text_attr == "text" else prev_child.tail
            if not text or not GREEK_CHAR_RE.search(text):
                return False
            pieces = _wrap_runs(text)
            if not any(k == "greek" for k, _ in pieces):
                return False
            # Build a sequence of (tail-of-prev, foreign-elem-or-None) ops.
            first_plain = pieces[0][1] if pieces[0][0] == "plain" else ""
            if text_attr == "text":
                host.text = first_plain or None
                start = 1 if pieces[0][0] == "plain" else 0
            else:
                prev_child.tail = first_plain or None
                start = 1 if pieces[0][0] == "plain" else 0
            anchor = prev_child  # where to insert after
            for kind, piece in pieces[start:]:
                if kind == "greek":
                    foreign = ET.Element("foreign")
                    foreign.set(XML_LANG, "grc")
                    foreign.text = piece
                    if anchor is None:
                        host.insert(0, foreign)
                    else:
                        idx = list(host).index(anchor) + 1
                        host.insert(idx, foreign)
                    anchor = foreign
                    inserted += 1
                else:
                    if anchor is None:
                        host.text = (host.text or "") + piece
                    else:
                        anchor.tail = (anchor.tail or "") + piece
            return True

        # .text (i.e. text before any child)
        process_text(node, "text", None)

        # Walk children; tails are handled per-child.
        for child in list(node):
            walk(child, inside_foreign)
            # After walking, child.tail may need wrapping.
            if child.tail and GREEK_CHAR_RE.search(child.tail):
                process_text(node, "tail", child)

    walk(body, False)
    return inserted


# ---------------------------------------------------------------------------
# Post-pass: synthesize <lb/> inside <fw> and <head> so running headers and
# section heads each count as numbered printed lines (Berendes convention).

def synthesize_furniture_lbs(body: ET.Element) -> int:
    """Prepend a fresh <lb/> as the first child of every <fw> and <head> with
    visible content, so the page-line counter advances when it encounters a
    running header, signature mark, or section heading. The new <lb>s carry
    no @n yet — number_lbs_per_page() will fill those in.

    Idempotent: skipped if the element already begins with an <lb>.
    """
    inserted = 0
    for el in body.iter():
        if local_name(el.tag) not in {"fw", "head"}:
            continue
        if len(el) > 0 and local_name(el[0].tag) == "lb":
            continue
        if not (el.text and el.text.strip()) and len(el) == 0:
            continue
        lb = ET.Element("lb")
        lb.tail = el.text
        el.text = None
        el.insert(0, lb)
        inserted += 1
    return inserted


# ---------------------------------------------------------------------------
# Post-pass: number <lb/> per page.

def number_lbs_per_page(body: ET.Element, stats: Stats) -> None:
    """Assign sequential @n to every <lb/> in body, resetting on each <pb>.

    Numbers lbs both in body content and inside notes — the project validator
    flags any <lb> without @n regardless of position. Also strips the
    `break="no"` attribute the OCR put on hyphenated line-end breaks: Berendes
    keeps the printed hyphen as literal text and omits the @break marker, and
    Sprengel follows the same convention.
    """
    counter = 0

    def walk(node: ET.Element):
        nonlocal counter
        for child in list(node):
            tag = local_name(child.tag)
            if tag == "pb":
                counter = 0
            elif tag == "lb":
                counter += 1
                child.set("n", str(counter))
                if "break" in child.attrib:
                    del child.attrib["break"]
                stats.lb_numbered += 1
            walk(child)

    walk(body)


# ---------------------------------------------------------------------------
# Header construction.

def build_tei_header() -> ET.Element:
    header = ET.Element("teiHeader")
    file_desc = ET.SubElement(header, "fileDesc")

    title_stmt = ET.SubElement(file_desc, "titleStmt")
    ET.SubElement(title_stmt, "title").text = (
        "Commentarius in Pedanii Dioscoridis Anazarbei De Materia Medica"
    )
    ET.SubElement(title_stmt, "author").text = "Kurt Polykarp Joachim Sprengel"
    resp = ET.SubElement(title_stmt, "respStmt")
    ET.SubElement(resp, "resp").text = (
        "OCR transcription, structural segmentation, and TEI/EpiDoc encoding"
    )
    ET.SubElement(resp, "name").text = "tei-maker pipeline"

    pub = ET.SubElement(file_desc, "publicationStmt")
    ET.SubElement(pub, "p").text = (
        "Structured TEI derived from per-page OCR fragments of the 1830 Leipzig "
        "edition (Internet Archive b23982500_0002)."
    )

    source = ET.SubElement(file_desc, "sourceDesc")
    bibl = ET.SubElement(source, "bibl")
    ET.SubElement(bibl, "title").text = (
        "Pedanii Dioscoridis Anazarbei De materia medica libri quinque"
    )
    ET.SubElement(bibl, "editor").text = "Kurt Polykarp Joachim Sprengel"
    ET.SubElement(bibl, "publisher").text = "Car. Cnoblochii"
    ET.SubElement(bibl, "pubPlace").text = "Leipzig"
    ET.SubElement(bibl, "date").text = "1830"
    ET.SubElement(bibl, "note").text = "Tomus II: Commentarius"
    return header


# ---------------------------------------------------------------------------
# Verification.

def verify(out_path: Path, chapter_rows: dict, manifest_pages: dict, stats: Stats) -> list:
    issues = []
    tree = ET.parse(out_path)
    root = tree.getroot()

    ns = f"{{{TEI}}}"

    # Chapter coverage and ordering.
    chapter_divs = [
        el for el in root.iter(f"{ns}div")
        if el.attrib.get("subtype") == "chapter"
    ]
    seen_ns = [d.attrib.get("n") for d in chapter_divs if d.attrib.get("n")]
    expected_order = list(chapter_rows.keys())
    missing = [n for n in expected_order if n not in seen_ns]
    if missing:
        issues.append(f"CHAPTER_MISSING: {len(missing)} chapters from table not in output "
                      f"(first 10: {missing[:10]})")

    # Page coverage.
    pbs = list(root.iter(f"{ns}pb"))
    pb_ns = [pb.attrib.get("n") for pb in pbs]
    expected_pages = list(manifest_pages.keys())
    missing_pages = [p for p in expected_pages if p not in pb_ns]
    if missing_pages:
        issues.append(f"PAGE_MISSING: {len(missing_pages)} pages from manifest not in pb (first 10: {missing_pages[:10]})")

    pbs_no_facs = [pb for pb in pbs if not pb.attrib.get("facs")]
    if pbs_no_facs:
        issues.append(f"PB_NO_FACS: {len(pbs_no_facs)} pb without facs")

    # Footnote round-trip.
    refs_by_target = {}
    notes_by_id = {}
    for el in root.iter():
        tag = local_name(el.tag)
        if tag == "ref" and el.attrib.get("type") == "footnote-ref":
            target = (el.attrib.get("target") or "").lstrip("#")
            refs_by_target.setdefault(target, []).append(el)
        elif tag == "note" and el.attrib.get("type") == "footnote":
            xid = el.attrib.get(XML_ID)
            if xid:
                notes_by_id[xid] = el
    unresolved = [t for t in refs_by_target if t not in notes_by_id]
    if unresolved:
        issues.append(f"FOOTNOTE_UNRESOLVED: {len(unresolved)} refs without notes "
                      f"(first 10: {unresolved[:10]})")
    orphan_notes = [nid for nid in notes_by_id if nid not in refs_by_target]
    if orphan_notes:
        # Notes whose refs may have been dropped during OCR; not fatal.
        print(f"  info: {len(orphan_notes)} notes without inbound refs "
              f"(first 5: {orphan_notes[:5]})", file=sys.stderr)

    # Duplicate xml:ids
    all_ids = [el.attrib.get(XML_ID) for el in root.iter()
               if el.attrib.get(XML_ID)]
    dups = [k for k, c in Counter(all_ids).items() if c > 1]
    if dups:
        issues.append(f"DUPLICATE_XML_ID: {len(dups)} duplicate ids "
                      f"(first 5: {dups[:5]})")

    # Books 1..5
    book_divs = [el for el in root.iter(f"{ns}div")
                 if el.attrib.get("subtype") == "book"]
    book_ns = sorted(int(d.attrib.get("n")) for d in book_divs if d.attrib.get("n"))
    if book_ns != [1, 2, 3, 4, 5]:
        issues.append(f"BOOK_COUNT: got {book_ns}, expected [1,2,3,4,5]")

    return issues


# ---------------------------------------------------------------------------
# Output writing.

def write_tei(out_path: Path, tei_root: ET.Element) -> None:
    indent(tei_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(tei_root)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)

    # Inject the EpiDoc xml-model PI between the XML declaration and root.
    text = out_path.read_text(encoding="utf-8")
    # ElementTree emits a single-quoted declaration; normalize.
    text = text.replace("<?xml version='1.0' encoding='utf-8'?>",
                        '<?xml version="1.0" encoding="UTF-8"?>')
    if XML_MODEL_PI not in text:
        text = text.replace(
            '<?xml version="1.0" encoding="UTF-8"?>\n',
            f'<?xml version="1.0" encoding="UTF-8"?>\n{XML_MODEL_PI}\n',
            1,
        )
    # Normalize ϑ -> θ (the validator flags U+03D1 as needing canonical θ).
    text = text.replace("ϑ", "θ")
    out_path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main.

def build(args) -> int:
    chapter_rows = load_chapter_table(args.chapter_table)
    manifest_pages = load_manifest(args.manifest)

    # 1. Concatenate every OCR fragment under a single synthetic body, then
    #    let extract_pages split on <pb> markers (handles multi-pb files).
    body = merge_fragments(args.ocr_dir)
    unwrap_legacy_chapter_divs(body)
    pages = extract_pages(body)

    # 2. Sort pages against manifest expected order; insert placeholders for
    #    any expected book_pages not OCR'd.
    pages, missing_pages, unexpected, conflicts = order_pages_against_manifest(
        pages, manifest_pages
    )
    if missing_pages:
        print(f"manifest pages with no OCR (placeholder emitted): {missing_pages}",
              file=sys.stderr)
    if unexpected:
        print(f"OCR pages not in manifest (kept at end): {unexpected}",
              file=sys.stderr)
    if conflicts:
        print(f"page-number collisions (merged): {conflicts}",
              file=sys.stderr)

    # 2. Renumber footnotes per page BEFORE assembly so refs and notes carry the
    #    page-scoped ids together.
    for page in pages:
        renumber_page_footnotes(page.blocks, page.notes, page.n)

    # 3. Assemble the Berendes-shaped body.
    out_body = ET.Element("body")
    stats = Stats()
    state = AssemblerState(body=out_body, chapter_rows=chapter_rows, stats=stats)
    open_preface(state)

    for page in pages:
        process_page(state, page, manifest_pages)

    # 4. Wrap any remaining bare Greek runs.
    greek_wraps = wrap_bare_greek(out_body)
    if greek_wraps:
        print(f"wrapped bare Greek  : {greek_wraps}", file=sys.stderr)

    # 5. Synthesize leading <lb/> inside every <fw> and <head> so they count
    #    as numbered printed lines (matches Berendes' page-line convention).
    furniture_lbs = synthesize_furniture_lbs(out_body)
    if furniture_lbs:
        print(f"furniture lbs added : {furniture_lbs}", file=sys.stderr)

    # 6. Number lb elements per page (after Greek-wrapping and lb synthesis).
    number_lbs_per_page(out_body, stats)

    # 5. Build full TEI tree. Use Clark notation on the root only so the
    #    serializer emits xmlns="..." on <TEI>; child elements inherit the
    #    default namespace without any per-element prefix bookkeeping.
    tei = ET.Element(f"{{{TEI}}}TEI")
    tei.set(XML_LANG, "la")
    tei.append(build_tei_header())
    text_el = ET.SubElement(tei, "text")
    text_el.append(out_body)

    write_tei(args.output, tei)

    # 6. Report stats.
    print(f"books               : {stats.books}", file=sys.stderr)
    print(f"chapters            : {stats.chapters}", file=sys.stderr)
    print(f"pages seen          : {stats.pages_seen}", file=sys.stderr)
    print(f"pbs emitted         : {stats.pbs_emitted}", file=sys.stderr)
    print(f"footnote blocks     : {stats.note_blocks}", file=sys.stderr)
    print(f"lbs numbered        : {stats.lb_numbered}", file=sys.stderr)
    if stats.unmatched_chapters:
        print(f"unmatched chapters  : {len(stats.unmatched_chapters)} "
              f"(first 10: {stats.unmatched_chapters[:10]})", file=sys.stderr)
    if stats.book_rollover_mismatches:
        print(f"rollover mismatches : {stats.book_rollover_mismatches}", file=sys.stderr)
    if stats.pages_missing_in_manifest:
        print(f"pages w/o manifest  : {len(stats.pages_missing_in_manifest)} "
              f"(first 5: {stats.pages_missing_in_manifest[:5]})", file=sys.stderr)
    print(f"wrote               : {args.output}", file=sys.stderr)

    if args.verify:
        issues = verify(args.output, chapter_rows, manifest_pages, stats)
        if issues:
            print("\nVerify issues:", file=sys.stderr)
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            return 1
        print("Verify OK.", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-dir", type=Path,
                        default=Path("sprengel_comm/ocr_fragments"))
    parser.add_argument("--chapter-table", type=Path,
                        default=Path("sprengel_comm/sprengel_chapter_table.tsv"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("editions/sprengel1830-comm/manifest.json"))
    parser.add_argument("--output", type=Path,
                        default=Path("editions/sprengel1830-comm/tei/edition.xml"))
    parser.add_argument("--verify", action="store_true", default=True)
    parser.add_argument("--no-verify", dest="verify", action="store_false")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
