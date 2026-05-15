#!/usr/bin/env python3
"""Validate the private Beck fresh diplomatic EpiDoc build."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from beck_fresh_diplomatic import (
    DEFAULT_BACK_MATTER_TRIAGE_LEDGER,
    DEFAULT_DIPLOMATIC_MANIFEST,
    DEFAULT_FRESH_DIR,
    DEFAULT_STRUCTURE_LEDGER,
    EXPECTED_CHAPTERS,
    XML_ID,
    XML_SPACE,
    local_name,
    normalize_ws,
    read_csv_rows,
)


def xml_id(element: ET.Element) -> str:
    return element.get(XML_ID) or element.get("xml:id") or ""


def ancestors(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def has_ancestor(element: ET.Element, parent_by_child: dict[ET.Element, ET.Element], tag: str) -> bool:
    current = parent_by_child.get(element)
    while current is not None:
        if local_name(current.tag) == tag:
            return True
        current = parent_by_child.get(current)
    return False


def resolved_refs(root: ET.Element) -> tuple[list[str], set[str], set[str], list[str]]:
    id_values = [xml_id(element) for element in root.iter() if xml_id(element)]
    ids = set(id_values)
    target_refs: set[str] = set()
    corresp_refs: set[str] = set()
    for element in root.iter():
        target = element.get("target") or ""
        if target.startswith("#"):
            target_refs.add(target[1:])
        for token in (element.get("corresp") or "").split():
            if token.startswith("#"):
                corresp_refs.add(token[1:])
    unresolved = sorted((target_refs | corresp_refs) - ids)
    return id_values, target_refs, corresp_refs, unresolved


def textpart(root: ET.Element, subtype: str) -> list[ET.Element]:
    return [
        element
        for element in root.iter()
        if local_name(element.tag) == "div" and element.get("type") == "textpart" and element.get("subtype") == subtype
    ]


def direct_head(element: ET.Element) -> ET.Element | None:
    for child in list(element):
        if local_name(child.tag) == "head":
            return child
    return None


GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")


def heading_tokens(value: str) -> list[str]:
    value = re.sub(r"^([IVX]+),(\d+)\b", r"\1, \2", value.strip())
    return [part for part in value.split() if part]


def leading_greek_heading_phrase(value: str) -> str:
    tokens = heading_tokens(value)
    if len(tokens) >= 2 and re.fullmatch(r"[IVXIl1LTΠῚH]+,?", tokens[0]) and re.fullmatch(r"\d+", tokens[1]):
        tokens = tokens[2:]
    elif tokens and re.fullmatch(r"[IVXIl1LTΠῚH]+,?\d+", tokens[0]):
        tokens = tokens[1:]

    phrase = []
    for token in tokens:
        if not GREEK_RE.search(token):
            break
        phrase.append(token)
    return " ".join(phrase)


def greek_compare_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", stripped).strip()


def greek_heading_terms(value: str) -> set[str]:
    terms = set()
    for token in leading_greek_heading_phrase(value).split():
        greek_only = greek_term(token)
        if greek_only:
            terms.add(greek_only)
    return terms


def greek_term(value: str) -> str:
    normalized = greek_compare_text(value)
    return "".join(char for char in normalized if "\u0370" <= char <= "\u03ff")


GREEK_ARTICLE_TERMS = {"ο", "η", "το", "οι", "αι", "τα", "τον", "την", "του", "τησ", "των"}


def is_heading_prefix_token(value: str) -> bool:
    value = value.strip()
    return bool(re.fullmatch(r"[IVXIl1LTΠῚH]+,?", value) or re.fullmatch(r"[IVXIl1LTΠῚH]+,?\d+", value) or re.fullmatch(r"\d+", value))


def direct_head_word_elements(head: ET.Element) -> list[ET.Element]:
    return [child for child in list(head) if local_name(child.tag) in {"w", "foreign", "unclear"}]


def element_is_greek_word(element: ET.Element) -> bool:
    lang = element.get("{http://www.w3.org/XML/1998/namespace}lang") or element.get("xml:lang") or element.get("lang")
    return local_name(element.tag) == "foreign" and lang == "grc" and bool(GREEK_RE.search("".join(element.itertext())))


def element_has_word_text(element: ET.Element) -> bool:
    return bool(greek_term("".join(element.itertext())) or re.search(r"[A-Za-z0-9]", "".join(element.itertext())))


LATIN_AUTHORITY_RE = re.compile(
    r"(?:L|Lam|DC|Forsk|Roxb|Dryand|Jacq|Fisch|Stokes|Asch|Pall|Pers|Spach|Nees|Blume|Pell|Maxim|Mill|Desf|Willd|Bieb)\.?"
)


def clean_latin_token(value: str) -> str:
    return value.strip().strip("~()[]{};,\"'“”‘’")


def is_latin_genus(value: str) -> bool:
    value = clean_latin_token(value)
    return bool(re.fullmatch(r"[A-Z][a-zA-Z]+", value) or re.fullmatch(r"[A-Z]\.", value))


def is_latin_species(value: str) -> bool:
    value = clean_latin_token(value)
    return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z-]+", value))


def is_latin_authority(value: str) -> bool:
    return bool(LATIN_AUTHORITY_RE.fullmatch(clean_latin_token(value)))


def element_is_latin_word(element: ET.Element) -> bool:
    lang = element.get("{http://www.w3.org/XML/1998/namespace}lang") or element.get("xml:lang") or element.get("lang")
    return local_name(element.tag) == "foreign" and lang == "lat" and "italic" in (element.get("rend") or "")


def latin_binomial_triplet_indices(tokens: list[str]) -> list[tuple[int, int, int]]:
    indices = []
    for index in range(len(tokens) - 2):
        first, second, third = tokens[index : index + 3]
        if re.fullmatch(r"[A-Z]\.", clean_latin_token(first)) and clean_latin_token(second) and not clean_latin_token(second)[0].islower():
            continue
        if is_latin_genus(first) and is_latin_species(second) and is_latin_authority(third):
            indices.append((index, index + 1, index + 2))
    return indices


def section_counts_from_ledger(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in read_csv_rows(path):
        if row.get("source_type") == "section" and row.get("decision") != "waived":
            counts[row.get("section_id") or row.get("beck_xml_tuid", "").replace("DiosMatMed:", "")] += 1
    return counts


def section_counts_from_tei(root: ET.Element) -> Counter[str]:
    counts: Counter[str] = Counter()
    for div in textpart(root, "section"):
        counts[div.get("n") or ""] += 1
    return counts


def footnote_qa_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[row.get("status") or ""] += 1
    return counts


def footnote_qa_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def back_matter_pages(path: Path) -> set[str]:
    return {row.get("pdf_page", "") for row in read_csv_rows(path) if row.get("classification") in {"encode-lightly", "not-worth-full-modeling"}}


def unresolved_qa_pages(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            status = row.get("status") or ""
            if status.startswith("unresolved"):
                counts[row.get("page") or ""] += 1
    return counts


def accepted_link_rows(path: Path) -> list[dict[str, str]]:
    return [row for row in read_csv_rows(path) if row.get("ref_xml_id") and row.get("note_xml_id")]


def validate(
    xml_path: Path,
    manifest_path: Path,
    expected_pdf_pages: int | None,
    structure_ledger: Path,
    fresh_dir: Path,
    back_matter_triage: Path,
    strict_content: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        return [f"XML_PARSE: {exc}"], []

    parent_by_child = ancestors(root)
    id_values, target_refs, corresp_refs, unresolved_refs = resolved_refs(root)
    by_id = {xml_id(element): element for element in root.iter() if xml_id(element)}
    duplicate_ids = [value for value, count in Counter(id_values).items() if count > 1]
    if duplicate_ids:
        errors.append(f"DUPLICATE_XML_ID: {len(duplicate_ids)} duplicate values")
    if unresolved_refs:
        errors.append(f"ORPHAN_TARGETS: {len(unresolved_refs)} target/corresp refs without matching xml:id")

    pbs = [element for element in root.iter() if local_name(element.tag) == "pb"]
    if expected_pdf_pages is not None and len(pbs) != expected_pdf_pages:
        errors.append(f"PB_EXPECTED_COUNT_MISMATCH: {len(pbs)} page breaks vs expected {expected_pdf_pages}")
    if any(not pb.get("facs") for pb in pbs):
        errors.append("PB_NO_FACS: one or more page breaks lack @facs")

    page_divs = [
        element
        for element in root.iter()
        if local_name(element.tag) == "div" and element.get("type") == "page"
    ]
    if page_divs:
        errors.append(f"PAGE_WRAPPER_DIVS: {len(page_divs)} page wrapper divs remain")

    edition_divs = [
        element
        for element in root.iter()
        if local_name(element.tag) == "div" and element.get("type") == "edition"
    ]
    if len(edition_divs) != 1:
        errors.append(f"EDITION_DIV_COUNT: {len(edition_divs)} edition divs found")
    elif edition_divs[0].get(XML_SPACE) != "preserve":
        errors.append("EDITION_DIV_XML_SPACE: edition div does not have xml:space='preserve'")

    books = textpart(root, "book")
    if [book.get("n") for book in books] != ["1", "2", "3", "4", "5"]:
        errors.append(f"BOOK_SEQUENCE: found {[book.get('n') for book in books]}")
    chapters = textpart(root, "chapter")
    chapter_counts: Counter[int] = Counter()
    missing_heads = []
    for chapter in chapters:
        n = chapter.get("n") or ""
        if "." in n:
            try:
                chapter_counts[int(n.split(".", 1)[0])] += 1
            except ValueError:
                pass
        head = direct_head(chapter)
        if head is None or not "".join(head.itertext()).strip():
            missing_heads.append(n or xml_id(chapter))
    for book, expected in EXPECTED_CHAPTERS.items():
        observed = chapter_counts.get(book, 0)
        if observed != expected:
            errors.append(f"CHAPTER_COUNT_BOOK_{book}: {observed} vs expected {expected}")
    if missing_heads:
        errors.append(f"CHAPTER_HEAD_MISSING: {len(missing_heads)} chapters lack non-empty direct head")
    chapters_by_n = {chapter.get("n") or "": chapter for chapter in chapters}

    bad_greek_heading_starts = []
    for row in read_csv_rows(structure_ledger):
        if row.get("source_type") != "chapter":
            continue
        heading_source = row.get("corrected_heading_text") or row.get("source_heading_text") or ""
        expected_phrase = leading_greek_heading_phrase(heading_source)
        expected_terms = [term for term in greek_heading_terms(expected_phrase)]
        if not expected_phrase or not expected_terms:
            continue
        chapter_id = row.get("chapter_id") or row.get("beck_xml_tuid", "").replace("DiosMatMed:", "")
        chapter = chapters_by_n.get(chapter_id)
        head = direct_head(chapter) if chapter is not None else None
        if head is None:
            continue
        word_elements = direct_head_word_elements(head)
        while word_elements and is_heading_prefix_token("".join(word_elements[0].itertext())):
            word_elements.pop(0)
        word_elements = [element for element in word_elements if element_has_word_text(element)]
        expected_ordered_terms = [greek_term(token) for token in expected_phrase.split() if greek_term(token)]
        required_count = 2 if expected_ordered_terms and expected_ordered_terms[0] in GREEK_ARTICLE_TERMS else 1
        if not word_elements:
            bad_greek_heading_starts.append(chapter_id)
            continue
        if len(word_elements) < required_count or any(not element_is_greek_word(element) for element in word_elements[:required_count]):
            bad_greek_heading_starts.append(chapter_id)
    if bad_greek_heading_starts:
        sample = ", ".join(bad_greek_heading_starts[:12])
        errors.append(
            f"CHAPTER_HEAD_GREEK_START_NOT_TAGGED: {len(bad_greek_heading_starts)} chapter heads lack Greek-tagged leading title token(s); sample {sample}"
        )

    bad_latin_headings = []
    for chapter in chapters:
        chapter_id = chapter.get("n") or xml_id(chapter)
        head = direct_head(chapter)
        if head is None:
            continue
        word_elements = [element for element in direct_head_word_elements(head) if element_has_word_text(element)]
        if not word_elements:
            tokens = normalize_ws(" ".join(head.itertext())).split()
            if latin_binomial_triplet_indices(tokens):
                bad_latin_headings.append(chapter_id)
            continue
        tokens = ["".join(element.itertext()) for element in word_elements]
        bad_triplets = [
            (first, second, third)
            for first, second, third in latin_binomial_triplet_indices(tokens)
            if not (
                element_is_latin_word(word_elements[first])
                and element_is_latin_word(word_elements[second])
                and element_is_latin_word(word_elements[third])
            )
        ]
        if bad_triplets:
            bad_latin_headings.append(chapter_id)
    if bad_latin_headings:
        sample = ", ".join(bad_latin_headings[:12])
        errors.append(
            f"CHAPTER_HEAD_LATIN_BINOMIAL_NOT_TAGGED: {len(bad_latin_headings)} chapter heads have untagged Latin scientific-name tokens; sample {sample}"
        )

    head_4171 = direct_head(chapters_by_n.get("4.171")) if chapters_by_n.get("4.171") is not None else None
    head_4171_text = normalize_ws(" ".join(head_4171.itertext())) if head_4171 is not None else ""
    if "Spurge olive" not in head_4171_text:
        errors.append("PAGE_351_CHAPTER_4_171_HEAD_SPURGE_OLIVE_MISSING: chapter head does not include the line-continuation title")
    if "beck-fresh-diplomatic-p0351-l024" in by_id:
        errors.append("PAGE_351_CHAPTER_4_171_HEAD_CONTINUATION_IN_BODY: line 24 remains emitted as body text")

    expected_sections = section_counts_from_ledger(structure_ledger)
    observed_sections = section_counts_from_tei(root)
    if expected_sections != observed_sections:
        errors.append(
            "SECTION_COUNT_MISMATCH: "
            f"expected {sum(expected_sections.values())} ledger sections, found {sum(observed_sections.values())}"
        )

    footnote_refs = [
        element
        for element in root.iter()
        if local_name(element.tag) == "ref" and element.get("type") == "footnote-ref"
    ]
    footnote_notes = [
        element
        for element in root.iter()
        if local_name(element.tag) == "note" and element.get("type") == "footnote"
    ]
    accepted_rows = accepted_link_rows(fresh_dir / "review" / "accepted_footnote_links.csv")
    ids = set(id_values)
    missing_accepted = [
        row
        for row in accepted_rows
        if row.get("ref_xml_id") not in ids or row.get("note_xml_id") not in ids
    ]
    if missing_accepted:
        errors.append(f"ACCEPTED_FOOTNOTE_ROWS_NOT_IN_TEI: {len(missing_accepted)} accepted rows missing ref or note")

    qa_path = fresh_dir / "qa" / "footnote_links.csv"
    qa_counts = footnote_qa_counts(qa_path)
    qa_rows = footnote_qa_rows(qa_path)
    unresolved_pages = unresolved_qa_pages(qa_path)
    triaged_pages = back_matter_pages(back_matter_triage)
    open_body_unresolved = sum(count for page, count in unresolved_pages.items() if page not in triaged_pages)
    if open_body_unresolved:
        message = f"FOOTNOTE_QA_OPEN_BODY_ROWS: {open_body_unresolved} unresolved QA rows outside triaged back matter"
        (errors if strict_content else warnings).append(message)

    ref353 = next((ref for ref in footnote_refs if xml_id(ref) == "beck-fresh-ref-p0353-scratch-002"), None)
    if ref353 is None:
        errors.append("PAGE_353_NOTE_65_REF_MISSING: accepted note 65 ref was not emitted")
    elif not has_ancestor(ref353, parent_by_child, "head"):
        errors.append("PAGE_353_NOTE_65_REF_NOT_IN_HEAD: note 65 ref is not in the chapter heading")

    page353_latin_ids = {
        "beck-fresh-p0353-l025-w005",
        "beck-fresh-p0353-l025-w006",
        "beck-fresh-p0353-l025-w007",
        "beck-fresh-p0353-l025-w009",
        "beck-fresh-p0353-l025-w010",
        "beck-fresh-p0353-l026-w001",
        "beck-fresh-p0353-l026-w003",
        "beck-fresh-p0353-l026-w004",
        "beck-fresh-p0353-l026-w005",
    }
    bad_latin = []
    for target in page353_latin_ids:
        element = by_id.get(target)
        if element is None:
            bad_latin.append(target)
            continue
        lang = element.get("{http://www.w3.org/XML/1998/namespace}lang") or element.get("xml:lang") or element.get("lang")
        if lang != "lat" or "italic" not in (element.get("rend") or ""):
            bad_latin.append(target)
    if bad_latin:
        errors.append(f"PAGE_353_LATIN_NOT_TAGGED: {len(bad_latin)} expected Latin scientific-name tokens lack xml:lang='lat' rend='italic'")

    chapter_11 = chapters_by_n.get("1.1")
    head_11 = direct_head(chapter_11) if chapter_11 is not None else None
    head_11_text = normalize_ws(" ".join(head_11.itertext())) if head_11 is not None else ""
    iris_word = by_id.get("beck-fresh-p0037-l015-w003")
    iris_text = "".join(iris_word.itertext()).strip() if iris_word is not None else ""
    iris_lang = (
        iris_word.get("{http://www.w3.org/XML/1998/namespace}lang")
        or iris_word.get("xml:lang")
        or iris_word.get("lang")
        if iris_word is not None
        else ""
    )
    if "ipic" in head_11_text or iris_text != "ἶρις," or iris_lang != "grc":
        errors.append("PAGE_37_CHAPTER_1_1_GREEK_NAME_NOT_CORRECTED: head should read ἶρις as Greek, not ipic")

    chapter_12 = chapters_by_n.get("1.2")
    head_12 = direct_head(chapter_12) if chapter_12 is not None else None
    head_12_text = normalize_ws(" ".join(head_12.itertext())) if head_12 is not None else ""
    akoron_word = by_id.get("beck-fresh-p0038-l019-w003")
    akoron_text = "".join(akoron_word.itertext()).strip() if akoron_word is not None else ""
    akoron_lang = (
        akoron_word.get("{http://www.w3.org/XML/1998/namespace}lang")
        or akoron_word.get("xml:lang")
        or akoron_word.get("lang")
        if akoron_word is not None
        else ""
    )
    if "&kopov" in head_12_text or akoron_text != "ἄκορον," or akoron_lang != "grc":
        errors.append("PAGE_38_CHAPTER_1_2_GREEK_NAME_NOT_CORRECTED: head should read ἄκορον as Greek, not &kopov")

    chapter_15 = chapters_by_n.get("1.5")
    head_15 = direct_head(chapter_15) if chapter_15 is not None else None
    head_15_text = normalize_ws(" ".join(head_15.itertext())) if head_15 is not None else ""
    if "ἕτερον εἶδος" not in head_15_text or "galingale" not in head_15_text:
        errors.append("PAGE_40_CHAPTER_1_5_SPLIT_HEAD_MISSING: chapter 1.5 split heading is incomplete")
    for target in {"beck-fresh-p0040-l023-w003", "beck-fresh-p0040-l024-w001"}:
        element = by_id.get(target)
        if element is None or not has_ancestor(element, parent_by_child, "head"):
            errors.append(f"PAGE_40_CHAPTER_1_5_HEADING_WORD_NOT_IN_HEAD: {target}")
    if "beck-fresh-diplomatic-p0040-l023" in by_id or "beck-fresh-diplomatic-p0040-l024" in by_id:
        errors.append("PAGE_40_CHAPTER_1_5_HEADING_LINE_IN_BODY: split heading line remains encoded as body text")

    footnote_21_ref = by_id.get("beck-fresh-ref-p0040-scratch-001")
    uterine_word = by_id.get("beck-fresh-p0040-l018-w009")
    uterine_text = "".join(uterine_word.itertext()).strip() if uterine_word is not None else ""
    if uterine_text != "uterine":
        errors.append("PAGE_40_UTERINE_STRAY_MARKER_TEXT: uterine word should not retain stray ?! marker text")
    if footnote_21_ref is None:
        errors.append("PAGE_40_NOTE_21_REF_MISSING: accepted note 21 ref was not emitted")
    else:
        ref_parent = parent_by_child.get(footnote_21_ref)
        siblings = list(ref_parent) if ref_parent is not None else []
        ref_index = siblings.index(footnote_21_ref) if footnote_21_ref in siblings else -1
        previous_sibling = siblings[ref_index - 1] if ref_index > 0 else None
        if previous_sibling is None or xml_id(previous_sibling) != "beck-fresh-p0040-l018-w009":
            errors.append("PAGE_40_NOTE_21_REF_WRONG_ANCHOR: note 21 should follow uterine")

    chapter_112 = chapters_by_n.get("1.12")
    head_112 = direct_head(chapter_112) if chapter_112 is not None else None
    head_112_text = normalize_ws(" ".join(head_112.itertext())) if head_112 is not None else ""
    if "Pogostemon patchouli Pell.," not in head_112_text or "Malabar" not in head_112_text:
        errors.append("PAGE_44_CHAPTER_1_12_SPLIT_HEAD_MISSING: chapter 1.12 split heading is incomplete")
    for target in {"beck-fresh-p0044-l021-w003", "beck-fresh-p0044-l022-w009"}:
        element = by_id.get(target)
        if element is None or not has_ancestor(element, parent_by_child, "head"):
            errors.append(f"PAGE_44_CHAPTER_1_12_HEADING_WORD_NOT_IN_HEAD: {target}")
    if "beck-fresh-diplomatic-p0044-l021" in by_id or "beck-fresh-diplomatic-p0044-l022" in by_id:
        errors.append("PAGE_44_CHAPTER_1_12_HEADING_LINE_IN_BODY: split heading line remains encoded as body text")
    ref26 = by_id.get("beck-fresh-ref-p0044-002")
    if ref26 is None:
        errors.append("PAGE_44_NOTE_26_REF_MISSING: accepted note 26 ref was not emitted")
    elif not has_ancestor(ref26, parent_by_child, "head"):
        errors.append("PAGE_44_NOTE_26_REF_NOT_IN_HEAD: note 26 should be in the chapter 1.12 heading")

    chapter_124 = chapters_by_n.get("1.24")
    head_124 = direct_head(chapter_124) if chapter_124 is not None else None
    head_124_text = normalize_ws(" ".join(head_124.itertext())) if head_124 is not None else ""
    if "Styrax benzoin Dryand., Bisabol" not in head_124_text:
        errors.append("PAGE_54_CHAPTER_1_24_SPLIT_HEAD_MISSING: chapter 1.24 split heading is incomplete")
    for target in {"beck-fresh-p0054-l006-w001", "beck-fresh-p0054-l006-w002"}:
        element = by_id.get(target)
        if element is None or not has_ancestor(element, parent_by_child, "head"):
            errors.append(f"PAGE_54_CHAPTER_1_24_HEADING_WORD_NOT_IN_HEAD: {target}")
    if "beck-fresh-diplomatic-p0054-l006" in by_id:
        errors.append("PAGE_54_CHAPTER_1_24_HEADING_LINE_IN_BODY: split heading line remains encoded as body text")
    if "beck-fresh-p0054-l006-w003" in by_id:
        errors.append("PAGE_54_CHAPTER_1_24_SCAN_SPECK_REMAINS: isolated comma-like scan speck remains in heading/body text")

    page21_cont = by_id.get("beck-fresh-fn-p0021-scratch-001")
    if page21_cont is None:
        errors.append("PAGE_21_FOOTNOTE_1_CONTINUATION_MISSING: page 20 note continuation was not emitted on page 21")
    elif (
        page21_cont.get("type") != "footnote"
        or page21_cont.get("subtype") != "continuation"
        or page21_cont.get("corresp") != "#beck-fresh-ref-p0020-007"
    ):
        errors.append("PAGE_21_FOOTNOTE_1_CONTINUATION_BAD_ENCODING: page 21 continuation note has unexpected linkage")
    for line_id in {f"beck-fresh-diplomatic-p0021-l{line_index:03d}" for line_index in range(28, 39)}:
        if line_id in by_id:
            errors.append("PAGE_21_FOOTNOTE_1_CONTINUATION_IN_BODY: continuation line remains emitted as body text")
            break

    page53_note41 = by_id.get("beck-fresh-fn-p0053-scratch-001")
    page54_note41 = by_id.get("beck-fresh-fn-p0054-scratch-001")
    if page53_note41 is None:
        errors.append("PAGE_53_NOTE_41_MISSING: accepted note 41 start was not emitted")
    if page54_note41 is None:
        errors.append("PAGE_54_NOTE_41_CONTINUATION_MISSING: page 53 note 41 continuation was not emitted on page 54")
    elif (
        page54_note41.get("type") != "footnote"
        or page54_note41.get("subtype") != "continuation"
        or page54_note41.get("corresp") != "#beck-fresh-ref-p0053-001"
    ):
        errors.append("PAGE_54_NOTE_41_CONTINUATION_BAD_ENCODING: page 54 continuation note has unexpected linkage")
    for line_id in {
        "beck-fresh-diplomatic-p0053-l034",
        "beck-fresh-diplomatic-p0053-l035",
        "beck-fresh-diplomatic-p0054-l029",
        "beck-fresh-diplomatic-p0054-l030",
    }:
        if line_id in by_id:
            errors.append(f"PAGE_54_NOTE_41_CONTINUATION_IN_BODY: {line_id} remains emitted as body text")

    chapter_18 = chapters_by_n.get("1.8")
    head_18 = direct_head(chapter_18) if chapter_18 is not None else None
    head_18_text = normalize_ws(" ".join(head_18.itertext())) if head_18 is not None else ""
    nardos_word = by_id.get("beck-fresh-p0042-l021-w004")
    nardos_text = "".join(nardos_word.itertext()).strip() if nardos_word is not None else ""
    nardos_lang = (
        nardos_word.get("{http://www.w3.org/XML/1998/namespace}lang")
        or nardos_word.get("xml:lang")
        or nardos_word.get("lang")
        if nardos_word is not None
        else ""
    )
    if "The Celtic spikenard grows" in head_18_text or "It is a small shrub" in head_18_text:
        errors.append("PAGE_42_CHAPTER_1_8_BODY_TEXT_IN_HEAD: section prose remains part of the chapter heading")
    if nardos_text != "νάρδος," or nardos_lang != "grc" or "vápóoc" in head_18_text:
        errors.append("PAGE_42_CHAPTER_1_8_GREEK_NAME_NOT_CORRECTED: head should read νάρδος as Greek, not vápóoc")
    if "beck-fresh-diplomatic-p0042-l022" not in by_id or "beck-fresh-diplomatic-p0042-l024" not in by_id:
        errors.append("PAGE_42_CHAPTER_1_8_SECTION_BODY_MISSING: section 1 prose lines should remain body text")
    page42_place_ids = {
        "beck-fresh-p0042-l022-w008",
        "beck-fresh-p0042-l022-w009",
        "beck-fresh-p0042-l022-w010",
    }
    italic_place_names = []
    for target in page42_place_ids:
        element = by_id.get(target)
        if element is None:
            italic_place_names.append(target)
            continue
        lang = element.get("{http://www.w3.org/XML/1998/namespace}lang") or element.get("xml:lang") or element.get("lang")
        if local_name(element.tag) != "w" or lang == "lat" or "italic" in (element.get("rend") or ""):
            italic_place_names.append(target)
    if italic_place_names:
        errors.append("PAGE_42_PLACE_NAMES_WRONGLY_LATIN_ITALIC: Alps/around/Liguria should remain plain prose")
    if "beck-fresh-diplomatic-p0042-l035" in by_id:
        errors.append("PAGE_42_FOOTNOTE_23_CONTINUATION_IN_BODY: line 35 remains emitted as chapter body text")
    page42_cont = by_id.get("beck-fresh-fn-p0042-cont-p0041-001")
    page42_cont_text = normalize_ws(" ".join(page42_cont.itertext())) if page42_cont is not None else ""
    if page42_cont is None:
        errors.append("PAGE_42_FOOTNOTE_23_CONTINUATION_MISSING: page 41 note continuation was not emitted on page 42")
    elif (
        page42_cont.get("type") != "footnote"
        or page42_cont.get("subtype") != "continuation"
        or page42_cont.get("corresp") != "#beck-fresh-ref-p0041-scratch-001"
        or "Arabia, which is probably the one meant here." not in page42_cont_text
    ):
        errors.append("PAGE_42_FOOTNOTE_23_CONTINUATION_BAD_ENCODING: page 42 continuation note has unexpected text or linkage")

    chapter_19 = chapters_by_n.get("1.9")
    head_19 = direct_head(chapter_19) if chapter_19 is not None else None
    head_19_text = normalize_ws(" ".join(head_19.itertext())) if head_19 is not None else ""
    nardos_19 = by_id.get("beck-fresh-p0043-l015-w004")
    nardos_19_text = "".join(nardos_19.itertext()).strip() if nardos_19 is not None else ""
    nardos_19_lang = (
        nardos_19.get("{http://www.w3.org/XML/1998/namespace}lang")
        or nardos_19.get("xml:lang")
        or nardos_19.get("lang")
        if nardos_19 is not None
        else ""
    )
    if "vápóoc" in head_19_text or nardos_19_text != "νάρδος," or nardos_19_lang != "grc":
        errors.append("PAGE_43_CHAPTER_1_9_GREEK_NAME_NOT_CORRECTED: head should read νάρδος as Greek, not vápóoc")

    chapter_110 = chapters_by_n.get("1.10")
    head_110 = direct_head(chapter_110) if chapter_110 is not None else None
    head_110_text = normalize_ws(" ".join(head_110.itertext())) if head_110 is not None else ""
    asaron = by_id.get("beck-fresh-p0043-l023-w003")
    asaron_text = "".join(asaron.itertext()).strip() if asaron is not None else ""
    asaron_lang = (
        asaron.get("{http://www.w3.org/XML/1998/namespace}lang")
        or asaron.get("xml:lang")
        or asaron.get("lang")
        if asaron is not None
        else ""
    )
    if "ácapov" in head_110_text or asaron_text != "ἄσαρον," or asaron_lang != "grc":
        errors.append("PAGE_43_CHAPTER_1_10_GREEK_NAME_NOT_CORRECTED: head should read ἄσαρον as Greek, not ácapov")

    page43_l031 = by_id.get("beck-fresh-diplomatic-p0043-l031")
    if page43_l031 is None:
        errors.append("PAGE_43_SECTION_2_BODY_LINE_MISSING: line 31 should remain chapter body text")
    elif local_name(page43_l031.tag) != "ab" or page43_l031.get("type") != "line":
        errors.append("PAGE_43_SECTION_2_WRONGLY_EMITTED_AS_NOTE: section 2 line is still encoded as a bottom note")
    page43_sequence_rejection = any(
        row.get("page") == "43"
        and row.get("raw_n") == "2"
        and row.get("status") == "rejected-sequence-body-text"
        for row in qa_rows
    )
    if not page43_sequence_rejection:
        errors.append("PAGE_43_SECTION_2_SEQUENCE_REJECTION_MISSING: backward candidate note 2 should be rejected by sequence")

    footnote_15_ref = by_id.get("beck-fresh-ref-p0038-scratch-001")
    fetuses_word = by_id.get("beck-fresh-p0038-l011-w001")
    pessary_word = by_id.get("beck-fresh-p0038-l010-w005")
    fetuses_text = "".join(fetuses_word.itertext()).strip() if fetuses_word is not None else ""
    if fetuses_text != "embryos/fetuses,":
        errors.append("PAGE_38_FETUSES_STRAY_MARKER_TEXT: embryos/fetuses word should not retain stray question mark")
    if footnote_15_ref is None:
        errors.append("PAGE_38_NOTE_15_REF_MISSING: accepted note 15 ref was not emitted")
    else:
        ref_parent = parent_by_child.get(footnote_15_ref)
        siblings = list(ref_parent) if ref_parent is not None else []
        ref_index = siblings.index(footnote_15_ref) if footnote_15_ref in siblings else -1
        previous_sibling = siblings[ref_index - 1] if ref_index > 0 else None
        if previous_sibling is None or xml_id(previous_sibling) != "beck-fresh-p0038-l011-w001":
            errors.append("PAGE_38_NOTE_15_REF_WRONG_ANCHOR: note 15 should follow embryos/fetuses")
    if pessary_word is not None:
        pessary_parent = parent_by_child.get(pessary_word)
        siblings = list(pessary_parent) if pessary_parent is not None else []
        pessary_index = siblings.index(pessary_word) if pessary_word in siblings else -1
        next_sibling = siblings[pessary_index + 1] if 0 <= pessary_index + 1 < len(siblings) else None
        if next_sibling is not None and xml_id(next_sibling) == "beck-fresh-ref-p0038-scratch-001":
            errors.append("PAGE_38_NOTE_15_REF_AFTER_PESSARY: note 15 remains attached after pessary")

    scan_artifact_ids = {
        "beck-fresh-p0348-l026-w009",
        "beck-fresh-p0349-l002-w001",
        "beck-fresh-p0349-l008-w001",
        "beck-fresh-p0349-l009-w001",
        "beck-fresh-p0349-l010-w001",
        "beck-fresh-p0349-l012-w001",
        "beck-fresh-p0349-l013-w001",
        "beck-fresh-p0349-l014-w001",
    }
    remaining_artifacts = sorted(scan_artifact_ids & by_id.keys())
    if remaining_artifacts:
        errors.append(f"PAGE_349_SCAN_ARTIFACTS_REMAIN: {len(remaining_artifacts)} gutter or heading scan artifacts still emitted")

    print(f"  Page breaks: {len(pbs)}")
    print(f"  Books: {len(books)}")
    print(f"  Chapters: {len(chapters)}")
    print(f"  Sections: {sum(observed_sections.values())}")
    print(f"  XML IDs: {len(id_values)} total, {len(set(id_values))} unique")
    print(f"  Targets: {len(target_refs)} target + {len(corresp_refs)} corresp refs, {len(unresolved_refs)} unresolved")
    print(f"  Footnote refs: {len(footnote_refs)}")
    print(f"  Footnote notes: {len(footnote_notes)}")
    print(f"  Footnote QA statuses: {dict(sorted(qa_counts.items()))}")
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    for issue in errors:
        print(f"  ERROR {issue}")
    for warning in warnings:
        print(f"  WARN {warning}")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file")
    parser.add_argument("--manifest", default=DEFAULT_DIPLOMATIC_MANIFEST)
    parser.add_argument("--expected-pdf-pages", type=int, default=None)
    parser.add_argument("--structure-ledger", default=DEFAULT_STRUCTURE_LEDGER)
    parser.add_argument("--fresh-dir", default=DEFAULT_FRESH_DIR)
    parser.add_argument("--back-matter-triage", default=DEFAULT_BACK_MATTER_TRIAGE_LEDGER)
    parser.add_argument("--strict-content", action="store_true")
    args = parser.parse_args()

    errors, _warnings = validate(
        Path(args.xml_file),
        Path(args.manifest),
        args.expected_pdf_pages,
        Path(args.structure_ledger),
        Path(args.fresh_dir),
        Path(args.back_matter_triage),
        args.strict_content,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
