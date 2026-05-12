#!/usr/bin/env python3
"""Validate the isolated Beck fresh-OCR TEI stream."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def xml_id(element: ET.Element) -> str:
    return element.get(XML_ID) or element.get("xml:id") or ""


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolved_refs(root: ET.Element) -> tuple[set[str], set[str], set[str]]:
    ids = {xml_id(element) for element in root.iter() if xml_id(element)}
    target_refs: set[str] = set()
    corresp_refs: set[str] = set()
    for element in root.iter():
        target = element.get("target") or ""
        if target.startswith("#"):
            target_refs.add(target[1:])
        corresp = element.get("corresp") or ""
        for token in corresp.split():
            if token.startswith("#"):
                corresp_refs.add(token[1:])
    return ids, target_refs, corresp_refs


def page_body_texts_and_note_pages(root: ET.Element) -> tuple[dict[str, str], dict[str, str]]:
    page_parts: dict[str, list[str]] = {}
    note_pages: dict[str, str] = {}
    state = {"page": ""}

    def walk(element: ET.Element, excluded: bool = False) -> None:
        tag = local_name(element.tag)
        if tag == "pb":
            state["page"] = element.get("n") or state["page"]
            return

        is_footnote = tag == "note" and element.get("type") == "footnote"
        if is_footnote and xml_id(element):
            note_pages[xml_id(element)] = state["page"]
        excluded_here = excluded or tag == "fw" or is_footnote
        if state["page"] and not excluded_here and element.text and element.text.strip():
            page_parts.setdefault(state["page"], []).append(element.text)
        for child in list(element):
            walk(child, excluded_here)
            if state["page"] and not excluded_here and child.tail and child.tail.strip():
                page_parts.setdefault(state["page"], []).append(child.tail)

    walk(root)
    return ({page: normalize_ws(" ".join(parts)) for page, parts in page_parts.items()}, note_pages)


def footnote_state_by_page(root: ET.Element) -> dict[str, dict[str, list[ET.Element]]]:
    state: dict[str, dict[str, list[ET.Element]]] = {}
    current_page = ""
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            current_page = element.get("n") or current_page
            continue
        if not current_page:
            continue
        page_state = state.setdefault(current_page, {"refs": [], "notes": []})
        if tag == "ref" and element.get("type") == "footnote-ref":
            page_state["refs"].append(element)
        elif tag == "note" and element.get("type") == "footnote":
            page_state["notes"].append(element)
    return state


def linked_note_for_n(page_state: dict[str, list[ET.Element]], n: str) -> ET.Element | None:
    for note in page_state.get("notes", []):
        if note.get("n") == n and note.get("corresp"):
            return note
    return None


def is_review_accepted(note: ET.Element) -> bool:
    return (note.get("resp") or "").startswith("accepted-sidecar:")


def validate(xml_path: Path, manifest_path: Path, expected_pdf_pages: int | None = None) -> list[str]:
    issues: list[str] = []
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as exc:
        return [f"XML_PARSE: {exc}"]
    root = tree.getroot()
    manifest = load_manifest(manifest_path)
    manifest_pages = manifest.get("pages") or []
    manifest_facs = {page.get("facs") or page.get("tei_facs") for page in manifest_pages}
    manifest_facs.discard(None)

    ids, target_refs, corresp_refs = resolved_refs(root)
    all_id_values = [xml_id(element) for element in root.iter() if xml_id(element)]
    duplicates = [value for value, count in Counter(all_id_values).items() if count > 1]
    if duplicates:
        issues.append(f"DUPLICATE_XML_ID: {len(duplicates)} duplicate values")

    unresolved = sorted((target_refs | corresp_refs) - ids)
    if unresolved:
        issues.append(f"ORPHAN_TARGETS: {len(unresolved)} target/corresp refs without matching xml:id")

    parent_by_child = {child: parent for parent in root.iter() for child in list(parent)}
    pbs = [element for element in root.iter() if local_name(element.tag) == "pb"]
    if not pbs:
        issues.append("NO_PAGE_BREAKS: no <pb> elements found")
    if len(pbs) != len(manifest_pages):
        issues.append(f"PB_MANIFEST_COUNT_MISMATCH: {len(pbs)} TEI page breaks vs {len(manifest_pages)} manifest pages")
    if expected_pdf_pages is not None and len(pbs) != expected_pdf_pages:
        issues.append(f"PB_EXPECTED_COUNT_MISMATCH: {len(pbs)} TEI page breaks vs expected {expected_pdf_pages}")

    pbs_missing_facs = [pb for pb in pbs if not pb.get("facs")]
    if pbs_missing_facs:
        issues.append(f"PB_NO_FACS: {len(pbs_missing_facs)} <pb> elements without @facs")

    pbs_missing_n = [pb for pb in pbs if not pb.get("n")]
    if pbs_missing_n:
        issues.append(f"PB_NO_N: {len(pbs_missing_n)} <pb> elements without @n")

    pbs_missing_manifest = [pb.get("facs") for pb in pbs if pb.get("facs") and pb.get("facs") not in manifest_facs]
    if pbs_missing_manifest:
        issues.append(f"PB_FACS_NOT_IN_MANIFEST: {len(pbs_missing_manifest)} <pb> facs values missing from manifest")

    body_lbs = []
    for lb in root.iter():
        if local_name(lb.tag) != "lb":
            continue
        parent = parent_by_child.get(lb)
        if parent is not None and local_name(parent.tag) == "note" and parent.get("type") == "footnote":
            continue
        body_lbs.append(lb)
    body_lbs_missing_n = [lb for lb in body_lbs if not lb.get("n")]
    if body_lbs_missing_n:
        issues.append(f"LB_NO_N: {len(body_lbs_missing_n)} main-text <lb> elements without @n")

    footnote_notes = {
        xml_id(element): element
        for element in root.iter()
        if local_name(element.tag) == "note" and element.get("type") == "footnote" and xml_id(element)
    }
    footnote_refs = [
        element
        for element in root.iter()
        if local_name(element.tag) == "ref" and element.get("type") == "footnote-ref"
    ]
    refs_missing_id = [ref for ref in footnote_refs if not xml_id(ref)]
    refs_missing_target = [ref for ref in footnote_refs if not (ref.get("target") or "").startswith("#")]
    if refs_missing_id:
        issues.append(f"FOOTNOTE_REF_NO_XML_ID: {len(refs_missing_id)} footnote refs without xml:id")
    if refs_missing_target:
        issues.append(f"FOOTNOTE_REF_NO_TARGET: {len(refs_missing_target)} footnote refs without local target")

    refs_by_target: dict[str, list[str]] = {}
    for ref in footnote_refs:
        target = (ref.get("target") or "").lstrip("#")
        if target:
            refs_by_target.setdefault(target, []).append(xml_id(ref))

    missing_notes = [target for target in refs_by_target if target not in footnote_notes]
    if missing_notes:
        issues.append(f"FOOTNOTE_TARGET_NO_NOTE: {len(missing_notes)} footnote targets without note")

    incomplete_notes = []
    bad_corresp = []
    for target, ref_ids in refs_by_target.items():
        note = footnote_notes.get(target)
        if note is None:
            continue
        expected = {f"#{ref_id}" for ref_id in ref_ids if ref_id}
        actual = set((note.get("corresp") or "").split())
        if not (note.get("n") and note.get("place") == "bottom" and note.get("corresp")):
            incomplete_notes.append(target)
        if expected and actual != expected:
            bad_corresp.append(target)
    if incomplete_notes:
        issues.append(f"FOOTNOTE_NOTE_INCOMPLETE: {len(incomplete_notes)} linked notes missing n/place/corresp")
    if bad_corresp:
        issues.append(f"FOOTNOTE_CORRESP_MISMATCH: {len(bad_corresp)} linked notes have unexpected corresp")

    empty_linked_notes = []
    for target in refs_by_target:
        note = footnote_notes.get(target)
        if note is not None and not re.sub(r"\s+", "", "".join(note.itertext())):
            empty_linked_notes.append(target)
    if empty_linked_notes:
        issues.append(f"FOOTNOTE_NOTE_EMPTY: {len(empty_linked_notes)} linked notes are empty")

    page_body_texts, note_pages = page_body_texts_and_note_pages(root)
    body_leaks = []
    for note_id, note in footnote_notes.items():
        note_text = normalize_ws("".join(note.itertext()))
        page = note_pages.get(note_id, "")
        if page and len(note_text) >= 30 and note_text in page_body_texts.get(page, ""):
            body_leaks.append(note_id)
    if body_leaks:
        issues.append(f"FOOTNOTE_BODY_SELECTION_LEAK: {len(body_leaks)} footnote bodies also appear in page body text")

    footnotes_by_page = footnote_state_by_page(root)
    page58 = footnotes_by_page.get("58", {"refs": [], "notes": []})
    page45 = footnotes_by_page.get("45", {"refs": [], "notes": []})
    if linked_note_for_n(page58, "47") is None:
        issues.append("FOOTNOTE_FIXTURE_58_47_UNLINKED: page 58 note 47 is not linked")
    note58_48 = linked_note_for_n(page58, "48")
    if note58_48 is not None and not is_review_accepted(note58_48):
        issues.append("FOOTNOTE_FIXTURE_58_48_AUTO_LINKED: page 58 note 48 linked without accepted sidecar")
    if linked_note_for_n(page45, "27") is None:
        issues.append("FOOTNOTE_FIXTURE_45_27_UNLINKED: page 45 note 27 is not linked")
    note45_28 = linked_note_for_n(page45, "28")
    if note45_28 is not None and not is_review_accepted(note45_28):
        issues.append("FOOTNOTE_FIXTURE_45_28_AUTO_LINKED: page 45 note 28 linked without accepted sidecar")

    ambiguous_auto_links = []
    for page in ("23", "24", "33"):
        for note in footnotes_by_page.get(page, {"notes": []}).get("notes", []):
            if note.get("corresp") and not is_review_accepted(note):
                ambiguous_auto_links.append(xml_id(note) or f"page-{page}-note-{note.get('n', '')}")
    if ambiguous_auto_links:
        issues.append(f"FOOTNOTE_AMBIGUOUS_PAGE_AUTO_LINK: {len(ambiguous_auto_links)} notes on pages 23/24/33 linked without accepted sidecar")

    print(f"  Manifest pages: {len(manifest_pages)}")
    print(f"  Page breaks: {len(pbs)}")
    print(f"  Main-text line breaks: {len(body_lbs)}")
    print(f"  XML IDs: {len(all_id_values)} total, {len(ids)} unique")
    print(f"  Targets: {len(target_refs)} target + {len(corresp_refs)} corresp refs, {len(unresolved)} unresolved")
    print(f"  Footnote refs: {len(footnote_refs)}, targeted notes: {len(refs_by_target)}")
    print(f"\n{len(issues)} issues found")
    for issue in issues:
        print(f"  - {issue}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file")
    parser.add_argument("--manifest", default="editions/beck2020_fresh/manifest.json")
    parser.add_argument("--expected-pdf-pages", type=int, default=None)
    args = parser.parse_args()

    issues = validate(Path(args.xml_file), Path(args.manifest), args.expected_pdf_pages)
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
