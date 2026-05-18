"""Beck 2020 migration: collapse <w> elements and clean per-word bbox attrs.

The existing editions/beck2020_fresh_diplomatic/tei/edition.xml has full
chapter axis (`<div type="textpart" subtype="chapter" n="1.1">`) but 181 987
`<w bbox="...">` word elements bloat the file to 272 913 lines. This migration
collapses words to plain text inside their parent `<ab>`/`<head>`/`<fw>`,
applies the canonical <lb> + <pb @facs> standards, and removes per-word
xml:ids.
"""
from __future__ import annotations

import re

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    drop_unnumbered_lb_outside_notes,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "beck2020_fresh_diplomatic"
NEW_ID = "beck2020"

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
W = f"{{{TEI_NS}}}w"
LB = f"{{{TEI_NS}}}lb"
PB = f"{{{TEI_NS}}}pb"
DIV = f"{{{TEI_NS}}}div"
XID = f"{{{XML_NS}}}id"

PER_WORD_ID_RE = re.compile(r"^beck-fresh-(?:diplomatic-)?p\d+-l\d+(?:-w\d+)?$")

_MULTI_SPACE = re.compile(r" +")
_SPACE_BEFORE_PUNCT = re.compile(r" ([,;.:!?\)\]\}])")
_SPACE_AFTER_OPEN = re.compile(r"([\(\[\{]) ")


def _normalize_whitespace(text: str) -> str:
    t = _MULTI_SPACE.sub(" ", text)
    t = _SPACE_BEFORE_PUNCT.sub(r"\1", t)
    t = _SPACE_AFTER_OPEN.sub(r"\1", t)
    return t.strip()


def _strip_per_word_ids(root: etree._Element) -> int:
    n = 0
    for elem in root.iter():
        xid = elem.get(XID)
        if xid and PER_WORD_ID_RE.match(xid):
            del elem.attrib[XID]
            n += 1
    return n


def _collapse_words_in(parent: etree._Element) -> None:
    """Replace direct <w> children with their concatenated text content.

    Text is placed after the last <lb/> child if any (so the line marker is
    preserved). Per-word elements are then removed.
    """
    words = parent.findall(W)
    if not words:
        return
    text_parts = ["".join(w.itertext()) for w in words]
    joined = _normalize_whitespace(" ".join(text_parts))
    lbs = [c for c in parent if c.tag == LB]
    for w in words:
        parent.remove(w)
    if lbs:
        lbs[-1].tail = joined
    else:
        parent.text = joined


def collapse_tree(root: etree._Element) -> None:
    parents_with_w: list[etree._Element] = []
    seen: set[int] = set()
    for w in root.iter(W):
        parent = w.getparent()
        if parent is None or id(parent) in seen:
            continue
        seen.add(id(parent))
        parents_with_w.append(parent)
    for parent in parents_with_w:
        _collapse_words_in(parent)


def rewrite_local_facs(root: etree._Element) -> None:
    """Rewrite Beck's local image paths to use the local: prefix recognized by
    the viewer and Schematron.
    """
    for pb in root.iter(PB):
        facs = pb.get("facs")
        if facs and facs.startswith("ocr/beck2020_fresh/images/"):
            pb.set(
                "facs",
                facs.replace("ocr/beck2020_fresh/images/", "local:beck2020/images/"),
            )


def normalize_div_ids(root: etree._Element) -> None:
    """Replace verbose book/chapter ids with stable ``beck-book-N`` / ``beck-ch-B-C``."""
    for div in root.iter(DIV):
        subtype = div.get("subtype")
        n = div.get("n")
        old = div.get(XID)
        if not (subtype and n and old):
            continue
        if subtype == "book" and "book" in old:
            div.set(XID, f"beck-book-{n}")
        elif subtype == "chapter" and "chapter" in old:
            div.set(XID, f"beck-ch-{n.replace('.', '-')}")
        # Section ids reuse @n across chapters (1.2.1 appears under 1.1 and 1.2);
        # the source xml:id carries an arbitrary disambiguator. Leave as-is.
    for pb in root.iter(PB):
        xid = pb.get(XID)
        if xid and xid.startswith("beck-fresh-diplomatic-p"):
            pb.set(XID, xid.replace("beck-fresh-diplomatic-p", "beck-p"))


def run() -> None:
    src_path = legacy_edition_tei(LEGACY_ID)
    if not src_path.exists():
        raise FileNotFoundError(f"Source Beck TEI not found: {src_path}")

    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    strip_bloat_attrs(root)
    _strip_per_word_ids(root)
    collapse_tree(root)
    rewrite_local_facs(root)
    normalize_div_ids(root)
    # Beck local image facs are not .jp2; no IIIF rewrite to do.
    # Defensive: still call rewrite_pb_facs for any future case.
    rewrite_pb_facs(root)
    drop_unnumbered_lb_outside_notes(root)

    etree.indent(root, space="  ")
    out_path = edition_tei(NEW_ID)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(out_path), pretty_print=True, xml_declaration=True, encoding="utf-8",
    )

    in_lines = src_path.read_text(encoding="utf-8").count("\n")
    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    print(f"beck2020: {in_lines} -> {out_lines} lines  ({out_path})")
