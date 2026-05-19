"""Sprengel 1829 migration: preserve page-first diplomatic structure.

Sprengel's Greek text and Latin translation are printed as page zones: Greek
at the top of the page and Latin below it. The canonical TEI for this edition
must keep that page-first shape so the viewer can render the diplomatic page.
Chapter identity is carried by paired ``<milestone unit="chapter">`` markers
inside the page zones, not by rebracketing the body into per-language chapter
trees.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    drop_unnumbered_lb_outside_notes,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "sprengel1829"
NEW_ID = "sprengel1829"

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI_NS}
TEI = f"{{{TEI_NS}}}"
XLANG = f"{{{XML_NS}}}lang"


def is_page_first_diplomatic(root: etree._Element) -> bool:
    """Return true when the body keeps printed pages with page zones."""
    pages = root.xpath(".//t:body//t:div[@subtype='diplomatic-page']", namespaces=NS)
    if not pages:
        return False
    for page in pages:
        zones = page.xpath("./t:ab[@type='pageZone']", namespaces=NS)
        places = {zone.get("place") for zone in zones}
        if "top" in places and "bottom" in places:
            return True
    return False


def is_chapter_major_split(root: etree._Element) -> bool:
    """Detect the refactor-regression shape that split Greek and Latin streams."""
    editions = root.xpath(".//t:body/t:div[@subtype='edition']", namespaces=NS)
    langs = {elem.get(XLANG) for elem in editions}
    return "grc" in langs and "la" in langs


def paired_chapter_milestone_count(root: etree._Element) -> int:
    """Count chapter numbers that have both Greek and Latin milestones."""
    by_n: dict[str, set[str]] = {}
    milestones = root.xpath(
        ".//t:milestone[@unit='chapter' and @n and @xml:lang]",
        namespaces=NS,
    )
    for milestone in milestones:
        by_n.setdefault(milestone.get("n"), set()).add(milestone.get(XLANG))
    return sum(1 for langs in by_n.values() if {"grc", "la"} <= langs)


def normalize_page_first_root(root: etree._Element) -> dict[str, int]:
    """Apply safe normalizations without changing Sprengel's page-first model."""
    if is_chapter_major_split(root) and not is_page_first_diplomatic(root):
        raise ValueError(
            "Sprengel 1829 input is chapter-major, not page-first diplomatic. "
            "Restore the page-first TEI before running this migration."
        )
    if not is_page_first_diplomatic(root):
        raise ValueError(
            "Sprengel 1829 input lacks paired diplomatic page zones "
            "(`ab type='pageZone' place='top|bottom'`)."
        )

    return {
        "bloat_attrs": strip_bloat_attrs(root),
        "pb_facs_rewritten": rewrite_pb_facs(root),
        "unnumbered_lbs_dropped": drop_unnumbered_lb_outside_notes(root),
        "paired_chapters": paired_chapter_milestone_count(root),
    }


def _source_path() -> Path:
    legacy = legacy_edition_tei(LEGACY_ID)
    if legacy.exists():
        return legacy
    current = edition_tei(NEW_ID)
    if current.exists():
        return current
    raise FileNotFoundError(
        f"Sprengel 1829 TEI not found at {legacy} or {current}"
    )


def run() -> None:
    src_path = _source_path()
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    stats = normalize_page_first_root(root)

    out_path = edition_tei(NEW_ID)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    etree.indent(root, space="  ")
    etree.ElementTree(root).write(
        str(out_path), pretty_print=True, xml_declaration=True, encoding="utf-8",
    )

    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    print(
        "sprengel1829: page-first diplomatic TEI, "
        f"{stats['paired_chapters']} paired chapter milestones, "
        f"{out_lines} lines  ({out_path})"
    )
