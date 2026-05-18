"""Extract per-edition lemma taxonomy files from migrated TEI editions.

For each edition, walks chapter `<head>` elements to build a `<taxonomy>` of
lemmas, one TEI file per (edition, language) pair.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

from lxml import etree

from pharmacopoeia.lemmas.slugs import slugify as _slugify
from pharmacopoeia.paths import edition_tei, edition_tei_relpath, lemma_file

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"
XLANG = f"{{{XML_NS}}}lang"


def _strip_text(elem: etree._Element) -> str:
    return "".join(elem.itertext()).strip()


def _extract_from_heads(
    root: etree._Element, edition: str,
) -> dict[str, dict[str, dict]]:
    by_lang: dict[str, dict[str, dict]] = defaultdict(dict)
    for ch in root.xpath(".//*[local-name()='div' and @subtype='chapter']"):
        ch_id = ch.get(XID)
        head = ch.find(TEI + "head")
        if head is None:
            continue

        for child in head.iter():
            corresp = child.get("corresp")
            if not corresp or not corresp.startswith("lemma:"):
                continue
            try:
                _, ed_lang, _slug = corresp.split(":", 2)
                ed, lang = ed_lang.rsplit("-", 1)
            except ValueError:
                continue
            if ed != edition:
                continue
            text = _strip_text(child)
            rec = by_lang[lang].get(corresp)
            if rec is None:
                by_lang[lang][corresp] = {
                    "id": corresp, "lang": lang, "form": text,
                    "headword": text,
                    "occurrences": [ch_id] if ch_id else [],
                }
            else:
                if ch_id and ch_id not in rec["occurrences"]:
                    rec["occurrences"].append(ch_id)

        if not head.xpath(".//@corresp"):
            lang = ch.get(XLANG)
            if lang:
                text = _strip_text(head)
                head_form = re.sub(r"^Περ[ὶί]\s+", "", text).strip()
                head_form = re.sub(r"^De\s+", "", head_form).strip()
                slug = _slugify(head_form)
                lemma_id = f"lemma:{edition}-{lang}:{slug}"
                rec = by_lang[lang].get(lemma_id)
                if rec is None:
                    by_lang[lang][lemma_id] = {
                        "id": lemma_id, "lang": lang, "form": text,
                        "headword": head_form,
                        "occurrences": [ch_id] if ch_id else [],
                    }
                    head.set("corresp", lemma_id)
                elif ch_id and ch_id not in rec["occurrences"]:
                    rec["occurrences"].append(ch_id)
                continue

            # Beck-style: head has bare English text + <foreign xml:lang="grc">.
            greek_forms: list[str] = []
            for foreign in head.findall(TEI + "foreign"):
                if foreign.get(XLANG) == "grc":
                    greek_forms.append(_strip_text(foreign).rstrip(",.;:"))
            english_parts: list[str] = []
            if head.text:
                english_parts.append(head.text)
            for child in head:
                if (child.tag == TEI + "foreign"
                        and child.get(XLANG) == "grc"):
                    if child.tail:
                        english_parts.append(child.tail)
                else:
                    english_parts.append("".join(child.itertext()))
                    if child.tail:
                        english_parts.append(child.tail)
            english_text = " ".join(english_parts).strip()
            english_text = re.sub(r"^[IVXLC]+,\s*\d+\s+", "", english_text)
            english_text = re.sub(r"^\d+\.\s+", "", english_text)
            english_text = english_text.strip().rstrip(",.;:")
            if english_text and edition == "beck2020":
                slug = _slugify(english_text)
                lemma_id = f"lemma:{edition}-en:{slug}"
                rec = by_lang["en"].get(lemma_id)
                if rec is None:
                    by_lang["en"][lemma_id] = {
                        "id": lemma_id, "lang": "en", "form": english_text,
                        "headword": english_text,
                        "occurrences": [ch_id] if ch_id else [],
                    }
                elif ch_id and ch_id not in rec["occurrences"]:
                    rec["occurrences"].append(ch_id)
            for gf in greek_forms:
                slug = _slugify(gf)
                lemma_id = f"lemma:{edition}-grc:{slug}"
                rec = by_lang["grc"].get(lemma_id)
                if rec is None:
                    by_lang["grc"][lemma_id] = {
                        "id": lemma_id, "lang": "grc", "form": gf,
                        "headword": gf,
                        "occurrences": [ch_id] if ch_id else [],
                    }
                elif ch_id and ch_id not in rec["occurrences"]:
                    rec["occurrences"].append(ch_id)
    return by_lang


def _write_taxonomy(
    edition: str, lang: str, records: dict[str, dict], tei_relpath: str,
) -> None:
    tei = etree.Element(TEI + "TEI", nsmap={None: TEI_NS})

    header = etree.SubElement(tei, TEI + "teiHeader")
    fd = etree.SubElement(header, TEI + "fileDesc")
    ts = etree.SubElement(fd, TEI + "titleStmt")
    title = etree.SubElement(ts, TEI + "title")
    title.text = f"Lemma taxonomy for {edition} ({lang})"
    ps = etree.SubElement(fd, TEI + "publicationStmt")
    p = etree.SubElement(ps, TEI + "p")
    p.text = (
        f"Generated by pharmacopoeia lemmas extract {edition} on "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}."
    )
    sd = etree.SubElement(fd, TEI + "sourceDesc")
    p2 = etree.SubElement(sd, TEI + "p")
    p2.text = f"Lemmas extracted from chapter heads of {tei_relpath}."

    text = etree.SubElement(tei, TEI + "text")
    body = etree.SubElement(text, TEI + "body")
    taxonomy = etree.SubElement(body, TEI + "taxonomy")
    taxonomy.set(XID, f"lemmas-{edition}-{lang}")

    for lemma_id in sorted(records.keys()):
        rec = records[lemma_id]
        cat = etree.SubElement(taxonomy, TEI + "category")
        # @n carries the URI-style identifier (xml:id would need NCName).
        cat.set("n", lemma_id)
        desc = etree.SubElement(cat, TEI + "catDesc")
        foreign = etree.SubElement(desc, TEI + "foreign")
        foreign.set(XLANG, lang)
        foreign.text = rec.get("form") or rec.get("headword") or lemma_id
        for occ in rec.get("occurrences", []):
            note = etree.SubElement(cat, TEI + "note")
            note.set("type", "occurrence")
            note.set("target", f"{tei_relpath}#{occ}")

    etree.indent(tei, space="  ")
    out = lemma_file(edition, lang)
    out.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(tei).write(
        str(out), pretty_print=True, xml_declaration=True, encoding="utf-8",
    )


def run(edition: str) -> None:
    src = edition_tei(edition)
    if not src.exists():
        raise FileNotFoundError(f"Migrated edition TEI not found: {src}")
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(src), parser)
    root = tree.getroot()

    records = _extract_from_heads(root, edition)
    tei_relpath = edition_tei_relpath(edition)
    tree.write(
        str(src), pretty_print=False, xml_declaration=True, encoding="utf-8",
    )

    for lang, rec in records.items():
        if not rec:
            continue
        _write_taxonomy(edition, lang, rec, tei_relpath)
        print(
            f"lemmas {edition}-{lang}: {len(rec)} entries -> {lemma_file(edition, lang)}"
        )
