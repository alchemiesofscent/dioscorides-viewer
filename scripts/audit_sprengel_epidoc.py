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
BOOK_1_GREEK_TITLE = "ΠΕΔΑΝΙΟΥ ΔΙΟΣΚΟΡΙΔΟΥ ΑΝΑΖΑΡΒΕΩΣ ΠΕΡΙ ΥΛΗΣ ΙΑΤΡΙΚΗΣ ΒΙΒΛΙΟΝ Α."
BOOK_1_LATIN_TITLE = "PEDANII DIOSCORIDIS ANAZARBEI DE MATERIA MEDICA LIBER I. PRAEFATIO."
BOOK_1_PROEM_TITLE = "ΠΡΟΟΙΜΙΟΝ."


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


def page_by_facs(root: ET.Element, facs: str) -> ET.Element | None:
    return next(
        (
            element
            for element in root.iter()
            if local_name(element.tag) == "div"
            and attr(element, "subtype") == "diplomatic-page"
            and attr(element, "facs") == facs
        ),
        None,
    )


def check_text_order(issues: list[str], text: str, label: str, needles: tuple[str, ...]) -> None:
    positions = []
    for needle in needles:
        position = text.find(needle)
        if position == -1:
            issues.append(f"{label}_TEXT_MISSING: {needle}")
            return
        positions.append(position)
    if positions != sorted(positions):
        issues.append(f"{label}_TEXT_ORDER")


def check_chapter_title_line_break(
    issues: list[str],
    parents: dict[ET.Element, ET.Element],
    page: ET.Element | None,
    title: str,
    continuation: str,
    label: str,
) -> None:
    if page is None:
        issues.append(f"{label}_PAGE_MISSING")
        return
    title_seg = next(
        (
            element
            for element in page.iter()
            if local_name(element.tag) == "seg"
            and attr(element, "type") == "chapterTitle"
            and text_content(element) == title
        ),
        None,
    )
    if title_seg is None:
        issues.append(f"{label}_TITLE_MISSING")
        return
    if title_seg.tail and title_seg.tail.strip():
        issues.append(f"{label}_TITLE_HAS_INLINE_TAIL")
    parent = parents.get(title_seg)
    siblings = list(parent) if parent is not None else []
    try:
        index = siblings.index(title_seg)
    except ValueError:
        issues.append(f"{label}_TITLE_PARENT_MISSING")
        return
    next_sibling = siblings[index + 1] if index + 1 < len(siblings) else None
    if next_sibling is None or local_name(next_sibling.tag) != "lb":
        issues.append(f"{label}_CONTINUATION_LB_MISSING")
    elif continuation not in (next_sibling.tail or ""):
        issues.append(f"{label}_CONTINUATION_TEXT_MISSING")


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
        }
        missing_front_ids = sorted(expected_front_ids - front_ids)
        if missing_front_ids:
            issues.append(f"FRONT_TOP_SECTION_MISSING: {missing_front_ids}")
        if "spr-front-sigla" in front_ids:
            issues.append("FRONT_SIGLA_SHOULD_NOT_BE_NAV_SECTION")
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
                "VIII. De codicibus manuscriptis.",
                "IX. De editionibus.",
                "X. De aliis adminiculis.",
                "XI. De hujus editionis ratione.",
            }
            missing_titles = sorted(expected_titles - subsection_titles)
            if missing_titles:
                issues.append(f"FRONT_PREFACE_SUBSECTION_MISSING: {missing_titles}")
            if "C. De synonymis plantarum barbaris." in subsection_titles:
                issues.append("FRONT_PREFACE_SUBSECTION_C_SHOULD_BE_INLINE")
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
            page_xvii_text = text_content(page_xvii)
            if "φαρ- μακοποιὸν ἔθνος" not in page_xvii_text:
                issues.append("FRONT_PAGE_XVII_AESCHYLUS_READING_MISSING")
            if "φαρ- μακοποιῶν ἔθνος" in page_xvii_text:
                issues.append("FRONT_PAGE_XVII_AESCHYLUS_BAD_READING")

        page_0010 = page_by_facs(root, "page_images/page-0010.png")
        if page_0010 is None:
            issues.append("FRONT_BLANK_PAGE_0010_MISSING")
        elif text_content(page_0010):
            issues.append("FRONT_BLANK_PAGE_0010_HAS_TEXT")

        page_0011 = page_by_facs(root, "page_images/page-0011.png")
        if page_0011 is None:
            issues.append("FRONT_PAGE_0011_MISSING")
        else:
            page_0011_text = text_content(page_0011)
            if attr(page_0011, "n") != "VII":
                issues.append("FRONT_PAGE_0011_BAD_N")
            if "I. De nomine auctoris." not in page_0011_text:
                issues.append("FRONT_PAGE_0011_SUBSECTION_TITLE_MISSING")
            if "Praefatio ad Dioscoridem" in page_0011_text:
                issues.append("FRONT_PAGE_0011_HAS_ABSTRACT_PREFACE_TITLE")

        page_0018 = page_by_facs(root, "page_images/page-0018.png")
        if page_0018 is None:
            issues.append("FRONT_PAGE_0018_MISSING")
        else:
            page_0018_text = text_content(page_0018)
            if "στρύχνον μανικὸν ὅ δορύκνιον" not in page_0018_text:
                issues.append("FRONT_PAGE_0018_DORYKNION_READING_MISSING")
            if "στρύχνον μανικὸν ἢ δορύκνιον" in page_0018_text:
                issues.append("FRONT_PAGE_0018_DORYKNION_BAD_READING")

        page_0019 = page_by_facs(root, "page_images/page-0019.png")
        if page_0019 is None:
            issues.append("FRONT_PAGE_0019_MISSING")
        else:
            page_0019_text = text_content(page_0019)
            if "ἐμφαρυγξάμενος" not in page_0019_text:
                issues.append("FRONT_PAGE_0019_EMPHARYNXAMENOS_READING_MISSING")
            if "ἐμφαρυγγιζόμενος" in page_0019_text:
                issues.append("FRONT_PAGE_0019_EMPHARYNGIZOMENOS_BAD_READING")
            if "ἔξαγίου ponderis" not in page_0019_text:
                issues.append("FRONT_PAGE_0019_EXAGIO_READING_MISSING")
            if "ξαγίον ponderis" in page_0019_text:
                issues.append("FRONT_PAGE_0019_EXAGIO_BAD_READING")

        page_0020 = page_by_facs(root, "page_images/page-0020.png")
        if page_0020 is None:
            issues.append("FRONT_PAGE_0020_MISSING")
        else:
            page_0020_text = text_content(page_0020)
            for expected in (
                "φασκίωσον",
                "loco τρυγός",
                "νηστικός loco νῆστις",
                "σεσέλιδος loco σεσέλεως",
                "πτέρεως loco πτέριδος",
                "βαρβαροφωνεῖν",
                "πλῆθος ὀνομάτων",
                "ἐφ' ἑκάστῃ βοτάνῃ μάτην προστιθέντα",
                "Oribasius etiam et Aëtius",
                "Comm. de bibl. Vindob. lib. 2. p. 593.",
                "Aristid. orat. vol. 3. p. 553.",
            ):
                if expected not in page_0020_text:
                    issues.append(f"FRONT_PAGE_0020_CORRECTION_MISSING: {expected}")
            for rejected in (
                "φασκώλιον",
                "loco τεῦτλον",
                "ψωρικός loco ψώρας",
                "ὀσφέλος loco ὀσφέλεος",
                "πιπέρεως loco πιπέριος",
                "βαρβαρόφωνον",
                "πάσης ὀνομασίαν",
                "εἰς ἑκάστην βοτάνην μάτην προστεθέντα",
                "Oribasius etiam et Aetius",
                "Comm. de bibl. Vindob. lib. 2. p. 598.",
                "Aristid. orat. vol. 3. p. 558.",
            ):
                if rejected in page_0020_text:
                    issues.append(f"FRONT_PAGE_0020_REJECTED_READING_PRESENT: {rejected}")

        page_0031 = page_by_facs(root, "page_images/page-0031.png")
        if page_0031 is None:
            issues.append("FRONT_PAGE_0031_MISSING")
        else:
            page_0031_text = text_content(page_0031)
            for expected in (
                "κελύφῳ et κελύφοις",
                "κελύφει et κελύφεσι",
                "Βουπρήστου",
                "Βουπρήστεως",
                "ὄξει loco ὄξῳ",
                "Ἀφροί falso",
                "P. 10. 12. 20. γλῶτταν",
                "ραῗτις: p. 283. μυῗτις",
                "νυκτερῖτις, ἀερῖτις, αἰγῖτις",
                "πελαγῖτις",
                "ἰχώρ",
                "Ἰβηρίς",
            ):
                if expected not in page_0031_text:
                    issues.append(f"FRONT_PAGE_0031_CORRECTION_MISSING: {expected}")
            for rejected in (
                "κέλυφη et κελύφας",
                "κελύφη et κελύφεσι",
                "Βουπρήστιον",
                "Βουπρήστιος",
                "ἔξω loco ἔξω",
                "ἄῤῥοι falso",
                "P. 10. 19. 20. γλῶτταν",
                "μύϊτις",
                "πυκτερίτις",
                "ἀρζίτις",
                "ἰξός",
                "Ἴφρυοϊς",
            ):
                if rejected in page_0031_text:
                    issues.append(f"FRONT_PAGE_0031_REJECTED_READING_PRESENT: {rejected}")

        front_heading_order_checks = {
            "0013": (
                "FRONT_PAGE_0013_HEADING_ORDER",
                (
                    "que non raro confudit",
                    "III. De aetate Dioscoridis.",
                    "Cum Erotianus",
                ),
            ),
            "0014": (
                "FRONT_PAGE_0014_HEADING_ORDER",
                (
                    "nostrae computationi",
                    "IV. De vitae genere.",
                    "Medicum fuisse doctum",
                ),
            ),
            "0015": (
                "FRONT_PAGE_0015_HEADING_ORDER",
                (
                    "nationes, ad Taciti usque aetatem",
                    "V. De secta, cui nomen dederit.",
                    "Aetate Dioscoridis",
                ),
            ),
            "0016": (
                "FRONT_PAGE_0016_HEADING_ORDER",
                (
                    "fabulis anilibus",
                    "VI. De dictionis genere.",
                    "Si quis Strabonem",
                ),
            ),
            "0020": (
                "FRONT_PAGE_0020_HEADING_ORDER",
                (
                    "jam βαρβαροφωνεῖν coeperat",
                    "C. De synonymis plantarum barbaris.",
                    "Multum diuque",
                ),
            ),
            "0021": (
                "FRONT_PAGE_0021_HEADING_ORDER",
                (
                    "mendose scripta fuerunt",
                    "VIII. De codicibus manuscriptis.",
                    "Celebratissimi sunt",
                ),
            ),
            "0024": (
                "FRONT_PAGE_0024_HEADING_ORDER",
                (
                    "pendendas accepi",
                    "IX. De editionibus.",
                    "Editionum princeps",
                ),
            ),
            "0025": (
                "FRONT_PAGE_0025_HEADING_ORDER",
                (
                    "monumentis Dioscoridem excipientibus",
                    "X. De aliis adminiculis.",
                    "E veteribus autem",
                ),
            ),
            "0029": (
                "FRONT_PAGE_0029_HEADING_ORDER",
                (
                    "de homonymis hyles iatricae",
                    "XI. De hujus editionis ratione.",
                    "Omnibus iis praesidiis",
                ),
            ),
        }
        for page_suffix, (label, needles) in front_heading_order_checks.items():
            page = page_by_facs(root, f"page_images/page-{page_suffix}.png")
            if page is None:
                issues.append(f"{label}_PAGE_MISSING")
                continue
            page_text = text_content(page)
            check_text_order(issues, page_text, label, needles)
            heading = needles[1]
            if page_text.count(heading) != 1:
                issues.append(f"{label}_HEADING_COUNT: {page_text.count(heading)}")

    page_0033 = page_by_facs(root, "page_images/page-0033.png")
    if page_0033 is None:
        issues.append("BODY_PAGE_0033_MISSING")
    else:
        page_0033_text = text_content(page_0033)
        if attr(page_0033, "n") != "1":
            issues.append("BODY_PAGE_0033_BAD_N")
        for expected, issue in (
            (BOOK_1_GREEK_TITLE, "BODY_PAGE_0033_GREEK_TITLE_MISSING"),
            (BOOK_1_PROEM_TITLE, "BODY_PAGE_0033_PROEM_TITLE_MISSING"),
            ("Codices et Editiones", "BODY_PAGE_0033_COMMENTARY_TITLE_MISSING"),
            (BOOK_1_LATIN_TITLE, "BODY_PAGE_0033_LATIN_TITLE_MISSING"),
        ):
            if expected not in page_0033_text:
                issues.append(issue)
        nearest = nearest_non_page_div(page_0033, parents)
        if nearest is None or attr(nearest, "xml:id") != "spr-book-1-prooimion":
            issues.append(
                "BODY_PAGE_0033_BAD_PROEM_SECTION: %s"
                % (attr(nearest, "xml:id") if nearest is not None else "")
            )

    check_chapter_title_line_break(
        issues,
        parents,
        page_by_facs(root, "page_images/page-0100.png"),
        "Κεφ. ξε΄. [Περὶ κυπρίνου στύψεως καὶ σκευασίας ἐλαίου.]",
        "Ἐλαίου ὀμφακίνου",
        "BODY_PAGE_0100_GRC_CHAPTER_65_TITLE_BREAK",
    )

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
