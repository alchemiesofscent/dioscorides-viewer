#!/usr/bin/env python3
"""
Phase 6c: Structural integrity checks on the final TEI XML.

Usage:
    python3 scripts/validate_structure.py output/berendes1902_epidoc.xml
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter


def validate(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        text = f.read()

    issues = []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        root = None
        issues.append("XML_PARSE: %s" % e)

    # 1. Check all 5 books present
    for b in range(1, 6):
        pattern = r'subtype="book"\s+n="%d"' % b
        if not re.search(pattern, text):
            issues.append("MISSING: Book %d div" % b)

    # 2. Count chapters per book
    book_chapters = {}
    for m in re.finditer(r'subtype="chapter"\s+n="(\d+)\.(\d+)"', text):
        book = int(m.group(1))
        book_chapters.setdefault(book, []).append(int(m.group(2)))

    for b in range(1, 6):
        chs = book_chapters.get(b, [])
        if chs:
            print("  Book %d: %d chapters (1..%d)" % (b, len(chs), max(chs)))
        else:
            print("  Book %d: NO CHAPTERS FOUND" % b)
            issues.append("NO_CHAPTERS: Book %d" % b)

    # 3. Check pb elements
    pbs = re.findall(r'<pb\s+[^>]*n="([^"]+)"', text)
    print("  Page breaks: %d" % len(pbs))
    if len(pbs) < 400:
        issues.append("LOW_PB_COUNT: only %d page breaks (expected ~550+)" % len(pbs))

    pbs_no_n = len(re.findall(r'<pb\s+(?![^>]*n=)[^>]*>', text))
    if pbs_no_n > 0:
        issues.append("PB_NO_N: %d <pb> elements without @n" % pbs_no_n)

    # Check pb has facs
    pbs_no_facs = len(re.findall(r'<pb\s+(?![^>]*facs=)[^>]*>', text))
    if pbs_no_facs > 0:
        issues.append("PB_NO_FACS: %d <pb> elements without @facs" % pbs_no_facs)

    # 4. Check lb elements
    lbs = re.findall(r'<lb\s+[^>]*n="(\d+)"', text)
    print("  Line breaks: %d" % len(lbs))
    lbs_no_n = len(re.findall(r'<lb\s+(?![^>]*n=)[^>]*>', text))
    if lbs_no_n > 0:
        issues.append("LB_NO_N: %d <lb> elements without @n" % lbs_no_n)

    # 5. Check Greek wrapping
    # Find bare Greek chars outside of <foreign>
    greek_pattern = re.compile(r'[ἀ-῿Α-Ω]')
    foreign_ranges = [(m.start(), m.end()) for m in re.finditer(r'<foreign[^>]*>.*?</foreign>', text, re.DOTALL)]

    bare_greek = 0
    for m in greek_pattern.finditer(text):
        pos = m.start()
        in_foreign = any(s <= pos <= e for s, e in foreign_ranges)
        if not in_foreign:
            # Check if in an attribute value (facs, etc)
            preceding = text[max(0, pos-100):pos]
            if '="' in preceding and '"' not in preceding.split('="')[-1]:
                continue
            bare_greek += 1
    if bare_greek > 0:
        issues.append("BARE_GREEK: %d Greek chars outside <foreign> tags" % bare_greek)
    print("  Bare Greek chars: %d" % bare_greek)

    theta_symbols = text.count("ϑ")
    if theta_symbols:
        issues.append("THETA_SYMBOL: %d instances of ϑ; normalize to θ" % theta_symbols)
    print("  Theta symbols: %d" % theta_symbols)

    # 6. Check ID uniqueness and target resolution
    xml_ids = re.findall(r'xml:id="([^"]+)"', text)
    duplicate_ids = [xml_id for xml_id, count in Counter(xml_ids).items() if count > 1]
    if duplicate_ids:
        issues.append("DUPLICATE_XML_ID: %d duplicate values" % len(duplicate_ids))
    print("  XML IDs: %d total, %d unique" % (len(xml_ids), len(set(xml_ids))))

    targets = set(re.findall(r'target="#([^"]+)"', text))
    corresp_refs = set()
    for value in re.findall(r'\bcorresp="([^"]+)"', text):
        for token in value.split():
            if token.startswith("#"):
                corresp_refs.add(token[1:])
    missing_targets = (targets | corresp_refs) - set(xml_ids)
    if missing_targets:
        issues.append("ORPHAN_TARGETS: %d target/corresp refs without matching xml:id" % len(missing_targets))
    print("  Targets: %d target + %d corresp refs, %d unresolved" % (len(targets), len(corresp_refs), len(missing_targets)))

    # 6b. Page furniture and footnote-link normalization checks.
    top_lb_pattern = re.compile(
        r'<pb\b[^>]*/>\s*<lb\b(?=[^>]*\bn="1")[^>]*/>\s*'
        r'<fw\b(?=[^>]*\bplace="top[^"]*")',
        re.DOTALL,
    )
    top_lb_count = len(top_lb_pattern.findall(text))
    if top_lb_count:
        issues.append("TOP_HEADER_LB_N1: %d <pb>/<lb n=\"1\"/>/<fw place=\"top\"> sequences remain" % top_lb_count)
    print("  Top-header lb n=1 sequences: %d" % top_lb_count)

    if root is not None:
        footnote_refs = []
        footnote_notes = {}
        ref_ids_missing = 0

        def local(tag):
            return tag.rsplit("}", 1)[-1]

        for el in root.iter():
            if local(el.tag) == "ref" and el.get("type") == "footnote-ref":
                target = (el.get("target") or "").lstrip("#")
                ref_id = el.get("{http://www.w3.org/XML/1998/namespace}id") or el.get("xml:id") or ""
                if target:
                    footnote_refs.append((target, ref_id))
                if not ref_id:
                    ref_ids_missing += 1
            elif local(el.tag) == "note" and el.get("type") == "footnote":
                note_id = el.get("{http://www.w3.org/XML/1998/namespace}id") or el.get("xml:id") or ""
                if note_id:
                    footnote_notes[note_id] = el

        if ref_ids_missing:
            issues.append("FOOTNOTE_REF_NO_XML_ID: %d footnote refs without xml:id" % ref_ids_missing)

        refs_by_target = {}
        for target, ref_id in footnote_refs:
            refs_by_target.setdefault(target, []).append(ref_id)

        missing_footnote_targets = [target for target in refs_by_target if target not in footnote_notes]
        if missing_footnote_targets:
            issues.append("FOOTNOTE_TARGET_NO_NOTE: %d footnote targets without note" % len(missing_footnote_targets))

        incomplete_notes = []
        bad_corresp = []
        for target, ref_ids in refs_by_target.items():
            note = footnote_notes.get(target)
            if note is None:
                continue
            note_id = note.get("{http://www.w3.org/XML/1998/namespace}id") or note.get("xml:id")
            corresp = note.get("corresp") or ""
            expected = set("#" + ref_id for ref_id in ref_ids if ref_id)
            actual = set(corresp.split())
            if not (note_id and note.get("n") and corresp and note.get("place") == "bottom"):
                incomplete_notes.append(target)
            if expected and actual != expected:
                bad_corresp.append(target)

        if incomplete_notes:
            issues.append("FOOTNOTE_NOTE_INCOMPLETE: %d targeted footnote notes missing n/xml:id/corresp/place" % len(incomplete_notes))
        if bad_corresp:
            issues.append("FOOTNOTE_CORRESP_MISMATCH: %d targeted footnote notes have unexpected corresp" % len(bad_corresp))
        print("  Footnote refs: %d, targeted notes: %d, incomplete targeted notes: %d" % (
            len(footnote_refs), len(refs_by_target), len(incomplete_notes)))

    # 7. Check chapter @n values agree with their containing book.
    if root is not None:
        ns = "{http://www.tei-c.org/ns/1.0}"
        mismatches = []

        def walk(el, current_book=None):
            if el.tag == ns + "div":
                subtype = el.get("subtype")
                n = el.get("n")
                if subtype == "book":
                    current_book = n
                elif subtype == "chapter" and current_book and n:
                    chapter_book = n.split(".", 1)[0]
                    if chapter_book != current_book:
                        mismatches.append((current_book, n))
            for child in list(el):
                walk(child, current_book)

        walk(root)
        if mismatches:
            issues.append("CHAPTER_BOOK_MISMATCH: %d chapter @n values disagree with containing book" % len(mismatches))

    # 8. XML well-formedness check (basic)
    open_tags = len(re.findall(r'<div\b', text))
    close_tags = len(re.findall(r'</div>', text))
    if open_tags != close_tags:
        issues.append("UNBALANCED_DIV: %d open vs %d close" % (open_tags, close_tags))
    print("  Div balance: %d open, %d close" % (open_tags, close_tags))

    # Summary
    print("\n%d issues found" % len(issues))
    for issue in issues:
        print("  - %s" % issue)

    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("xml_file")
    parser.add_argument("--output", default=None, help="Write issues to JSON file")
    args = parser.parse_args()

    issues = validate(args.xml_file)
    if args.output:
        with open(args.output, "w") as f:
            json.dump(issues, f, indent=2)

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
