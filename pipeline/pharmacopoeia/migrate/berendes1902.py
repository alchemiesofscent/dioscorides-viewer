"""Berendes 1902 migration: flatten <continuation> divs into their owning chapter.

The existing edition uses a custom `<div type="textpart" subtype="continuation"
n="bookN_NNN" xml:id="cont_...">` wrapper to hold content that belongs to the
chapter just closed but appears on the next page. This migration merges each
continuation div's children back into the preceding chapter div, so a chapter
becomes a single `<div type="textpart" subtype="chapter">` that may contain
multiple `<pb/>` milestones.

It also adds `@corresp="lemma:..."` hooks on chapter `<head>` foreign/bold
elements so the lemma file can be cross-referenced.
"""
from __future__ import annotations

import re

from lxml import etree

from pharmacopoeia.lemmas.slugs import slugify as _slugify
from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    drop_unnumbered_lb_outside_notes,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "berendes1902"
NEW_ID = "berendes1902"

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"


def flatten_continuations(root: etree._Element) -> int:
    """Merge each continuation div's children into the preceding chapter div."""
    body = root.find(f"{TEI}text/{TEI}body")
    if body is None:
        return 0
    merged = 0
    for book_div in list(body.iter(f"{TEI}div")):
        children = list(book_div)
        if not any(c.get("subtype") == "continuation" for c in children):
            continue
        last_chapter: etree._Element | None = None
        i = 0
        while i < len(book_div):
            child = book_div[i]
            if child.get("subtype") == "chapter":
                last_chapter = child
                i += 1
                continue
            if child.get("subtype") == "continuation":
                if last_chapter is not None:
                    for cont_child in list(child):
                        last_chapter.append(cont_child)
                    book_div.remove(child)
                    merged += 1
                    continue
            i += 1
    return merged


def annotate_heads(root: etree._Element) -> int:
    """Add @corresp="lemma:..." hooks to chapter <head> foreign/bold spans."""
    n = 0
    for ch in root.xpath(".//*[local-name()='div' and @subtype='chapter']"):
        head = ch.find(TEI + "head")
        if head is None:
            continue
        for foreign in head.findall(TEI + "foreign"):
            if foreign.get(f"{{{XML_NS}}}lang") != "grc":
                continue
            text = "".join(foreign.itertext()).strip().rstrip(".:")
            head_word = re.sub(r"^Περ[ὶί]\s+", "", text)
            slug = _slugify(head_word)
            foreign.set("corresp", f"lemma:berendes1902-grc:{slug}")
            n += 1
        for hi in head.findall(TEI + "hi"):
            if hi.get("rend") != "bold":
                continue
            text = "".join(hi.itertext()).strip().rstrip(".:")
            slug = _slugify(text)
            hi.set("corresp", f"lemma:berendes1902-de:{slug}")
            n += 1
    return n


def normalize_chapter_ids(root: etree._Element) -> None:
    """Replace ``ch_2_189`` style ids with ``ber-ch-2-189``."""
    for ch in root.xpath(".//*[local-name()='div' and @subtype='chapter']"):
        old = ch.get(XID)
        if old and old.startswith("ch_"):
            ch.set(XID, "ber-" + old.replace("_", "-"))


def run() -> None:
    src_path = legacy_edition_tei(LEGACY_ID)
    if not src_path.exists():
        raise FileNotFoundError(f"Source Berendes TEI not found: {src_path}")
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    merged = flatten_continuations(root)
    normalize_chapter_ids(root)
    annotated = annotate_heads(root)
    strip_bloat_attrs(root)
    rewrite_pb_facs(root)
    # Berendes <lb> elements all have @n in the main text; safe to assert.

    out_path = edition_tei(NEW_ID)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(out_path), pretty_print=False, xml_declaration=True, encoding="utf-8",
    )
    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    print(
        f"berendes1902: merged {merged} continuation divs, "
        f"annotated {annotated} head lemmas, {out_lines} lines  ({out_path})"
    )
