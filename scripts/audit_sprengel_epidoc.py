#!/usr/bin/env python3
"""Audit Sprengel-specific deterministic normalization rules."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def attr(element: ET.Element, name: str) -> str:
    if name == "xml:id":
        return element.get(XML_ID) or element.get("xml:id") or ""
    return element.get(name) or ""


def text_content(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def nearest_non_page_div(element: ET.Element, parents: dict[ET.Element, ET.Element]) -> ET.Element | None:
    current = parents.get(element)
    while current is not None:
        if local_name(current.tag) == "div" and attr(current, "subtype") != "diplomatic-page":
            return current
        current = parents.get(current)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("xml")
    parser.add_argument("--manifest", default="editions/sprengel1829/manifest.json")
    args = parser.parse_args()

    raw = open(args.xml, encoding="utf-8").read()
    root = ET.fromstring(raw)
    parents = parent_map(root)

    issues: list[str] = []
    warnings: list[str] = []

    front = root.find(f".//{{{TEI}}}front")
    if front is None:
        issues.append("FRONT_MISSING")
    else:
        front_ids = {
            attr(element, "xml:id")
            for element in list(front)
            if local_name(element.tag) == "div"
        }
        expected_front_ids = {
            "spr-front-title-page",
            "spr-front-dedication",
            "spr-front-preface",
            "spr-front-errata",
            "spr-front-sigla",
        }
        missing_front_ids = sorted(expected_front_ids - front_ids)
        if missing_front_ids:
            issues.append(f"FRONT_TOP_SECTION_MISSING: {missing_front_ids}")
        preface = next(
            (
                element
                for element in list(front)
                if local_name(element.tag) == "div" and attr(element, "type") == "preface"
            ),
            None,
        )
        if preface is None:
            issues.append("FRONT_PREFACE_MISSING")
        else:
            if attr(preface, "xml:id") != "spr-front-preface":
                issues.append("FRONT_PREFACE_BAD_ID")
            direct_preface_pages = [
                child
                for child in list(preface)
                if local_name(child.tag) == "div" and attr(child, "subtype") == "diplomatic-page"
            ]
            if direct_preface_pages:
                issues.append(f"FRONT_PREFACE_DIRECT_PAGE_WRAPPERS: {len(direct_preface_pages)}")
            subsection_titles = set()
            for child in list(preface):
                if local_name(child.tag) != "div" or attr(child, "subtype") != "front-subsection":
                    continue
                head = child.find(f"{{{TEI}}}head")
                if head is not None:
                    subsection_titles.add(text_content(head))
            expected_titles = {
                "I. De nomine auctoris.",
                "II. De patria Dioscoridis, et de homonymis scriptoribus.",
                "III. De aetate Dioscoridis.",
                "IV. De vitae genere.",
                "V. De secta, cui nomen dederit.",
                "VI. De dictionis genere.",
                "VII. De genuinorum a spuriis libris distinctione.",
                "C. De synonymis plantarum barbaris.",
                "VIII. De codicibus manuscriptis.",
                "IX. De editionibus.",
                "X. De aliis adminiculis.",
                "XI. De hujus editionis ratione.",
            }
            missing_titles = sorted(expected_titles - subsection_titles)
            if missing_titles:
                issues.append(f"FRONT_PREFACE_SUBSECTION_MISSING: {missing_titles}")
        page_xvii = next(
            (
                element
                for element in root.iter()
                if local_name(element.tag) == "div"
                and attr(element, "subtype") == "diplomatic-page"
                and attr(element, "n") == "XVII"
            ),
            None,
        )
        if page_xvii is None:
            issues.append("FRONT_PAGE_XVII_MISSING")
        else:
            nearest = nearest_non_page_div(page_xvii, parents)
            if nearest is None or attr(nearest, "xml:id") != "spr-front-preface-viii":
                issues.append(
                    "FRONT_PAGE_XVII_BAD_SECTION: %s"
                    % (attr(nearest, "xml:id") if nearest is not None else "")
                )
            if "principis, qui, dum Xerxem comitaretur" not in text_content(page_xvii):
                issues.append("FRONT_PAGE_XVII_TEXT_MISSING")

    head_numeric_markers = sum(
        1
        for element in root.iter()
        if local_name(element.tag) == "head" and re.search(r"\[\d+[a-z]?\]", text_content(element), re.IGNORECASE)
    )
    checks = {
        "HEAD_NUMERIC_MARKER": head_numeric_markers,
        "PARAGRAPH_LEADING_HEAD_CLOSE": len(re.findall(r"<p>\s*<lb\b[^>]*/>\s*\.\]", raw)),
        "BRACKETED_REF_TEXT": len(re.findall(r"<ref\b[^>]*>\[\d+[a-z]?\]</ref>", raw)),
        "POLLUTED_PI_LABEL": len(re.findall(r'\blabel="Περὶ[^"]*\d+"', raw)),
    }

    standalone_synonyma_after_head = 0
    standalone_greek_chapter_heads = 0
    for element in root.iter():
        if local_name(element.tag) != "ab":
            continue
        lang = element.get(f"{{{XML}}}lang") or element.get("xml:lang") or ""
        if lang == "grc":
            standalone_greek_chapter_heads += sum(
                1
                for child in list(element)
                if local_name(child.tag) == "head" and text_content(child).startswith("Κεφ.")
            )
        children = [child for child in list(element) if local_name(child.tag) != "milestone"]
        for left, right in zip(children, children[1:]):
            if (
                local_name(left.tag) == "head"
                and local_name(right.tag) == "seg"
                and attr(right, "type") == "synonyma"
            ):
                standalone_synonyma_after_head += 1
    checks["STANDALONE_SYNONYMA_AFTER_HEAD"] = standalone_synonyma_after_head
    checks["STANDALONE_GREEK_CHAPTER_HEAD"] = standalone_greek_chapter_heads
    for name, count in checks.items():
        if count:
            issues.append(f"{name}: {count}")

    ids = {attr(element, "xml:id") for element in root.iter() if attr(element, "xml:id")}
    id_counts = Counter(attr(element, "xml:id") for element in root.iter() if attr(element, "xml:id"))
    duplicate_ids = [xml_id for xml_id, count in id_counts.items() if count > 1]
    if duplicate_ids:
        issues.append(f"DUPLICATE_XML_ID: {len(duplicate_ids)}")

    footnote_refs = []
    notes_by_id = {}
    for element in root.iter():
        name = local_name(element.tag)
        if name == "ref" and attr(element, "type") == "footnote-ref":
            target = attr(element, "target")
            ref_id = attr(element, "xml:id")
            label = text_content(element)
            footnote_refs.append((target, ref_id, label))
            if not ref_id:
                issues.append(f"FOOTNOTE_REF_NO_XML_ID: target={target}")
            if label.startswith("[") or label.endswith("]"):
                issues.append(f"FOOTNOTE_REF_BRACKETED_LABEL: target={target}")
        elif name == "note" and attr(element, "type") == "footnote":
            note_id = attr(element, "xml:id")
            if note_id:
                notes_by_id[note_id] = element

    refs_by_target: dict[str, list[str]] = defaultdict(list)
    for target, ref_id, _label in footnote_refs:
        if not target.startswith("#"):
            issues.append(f"FOOTNOTE_REF_BAD_TARGET: {target}")
            continue
        target_id = target[1:]
        refs_by_target[target_id].append(ref_id)
        if target_id not in ids:
            issues.append(f"UNRESOLVED_TARGET: {target_id}")

    for target_id, ref_ids in refs_by_target.items():
        note = notes_by_id.get(target_id)
        if note is None:
            issues.append(f"FOOTNOTE_TARGET_NO_NOTE: {target_id}")
            continue
        if not attr(note, "n"):
            issues.append(f"FOOTNOTE_NOTE_NO_N: {target_id}")
        if attr(note, "place") != "bottom":
            issues.append(f"FOOTNOTE_NOTE_BAD_PLACE: {target_id}")
        corresp = set((attr(note, "corresp") or "").split())
        missing_corresp = [ref_id for ref_id in ref_ids if ref_id and f"#{ref_id}" not in corresp]
        if missing_corresp:
            issues.append(f"FOOTNOTE_CORRESP_MISSING_REF: {target_id}")

    def count_non_note_lbs(element: ET.Element, in_note: bool = False) -> int:
        element_in_note = in_note or local_name(element.tag) == "note"
        count = 1 if local_name(element.tag) == "lb" and not element_in_note else 0
        return count + sum(count_non_note_lbs(child, element_in_note) for child in list(element))

    by_page_lang: dict[tuple[str, str], int] = defaultdict(int)
    current_page = ""
    for element in root.iter():
        name = local_name(element.tag)
        if name == "div" and attr(element, "subtype") == "diplomatic-page":
            current_page = attr(element, "n")
        if name == "ab" and attr(element, "type") == "pageZone":
            lang = element.get(f"{{{XML}}}lang") or element.get("xml:lang") or ""
            by_page_lang[(current_page, lang)] += count_non_note_lbs(element)

    for page in {page for page, _lang in by_page_lang}:
        grc = by_page_lang.get((page, "grc"), 0)
        la = by_page_lang.get((page, "la"), 0)
        if grc and la and abs(grc - la) > 8:
            warnings.append(f"LINE_POLICY_DIVERGENCE: page={page} grc={grc} la={la}")

    manifest_path = Path(args.manifest)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_page_xvii = next(
            (page for page in manifest.get("pages", []) if page.get("book_page") == "XVII"),
            None,
        )
        if manifest_page_xvii is None:
            issues.append("MANIFEST_PAGE_XVII_MISSING")
        else:
            if manifest_page_xvii.get("front_section") != "preface":
                issues.append("MANIFEST_PAGE_XVII_BAD_FRONT_SECTION")
            if manifest_page_xvii.get("front_subsection") != "preface-viii":
                issues.append("MANIFEST_PAGE_XVII_BAD_FRONT_SUBSECTION")
            if manifest_page_xvii.get("front_subsection_title") != "VIII. De codicibus manuscriptis.":
                issues.append("MANIFEST_PAGE_XVII_BAD_FRONT_SUBSECTION_TITLE")

    print(f"Footnote refs: {len(footnote_refs)}")
    print(f"Footnote notes: {len(notes_by_id)}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings[:20]:
        print(f"  warning: {warning}")
    if len(warnings) > 20:
        print(f"  ... {len(warnings) - 20} more warnings")

    if issues:
        print(f"\n{len(issues)} issues found")
        for issue in issues[:80]:
            print(f"  - {issue}")
        if len(issues) > 80:
            print(f"  ... {len(issues) - 80} more issues")
        return 1

    print("\nSprengel audit passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
