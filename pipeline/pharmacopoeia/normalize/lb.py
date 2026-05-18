"""Canonical `<lb/>` enforcement, shared by all migrations.

See docs/TEI_STANDARD.md for the rules. Briefly:
- ``<lb n="N"/>`` is the canonical form. @n is required outside ``<note>`` bodies.
- @break="no" is the canonical hyphenation marker.
- Forbidden attrs on <lb> and <pb>: bbox, cert, source, seq, plain `id`.
- Self-closing without trailing space (handled by serializer, not by us).
"""
from __future__ import annotations

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"

# Attrs to strip from any element. Beck OCR adds bbox/cert/source/seq;
# legacy MediaWiki used plain `id` instead of `xml:id`.
STRIP_ATTRS = ("bbox", "cert", "source", "seq")


def strip_bloat_attrs(root: etree._Element) -> int:
    """Drop bbox/cert/source/seq from every element. Returns count stripped."""
    n = 0
    for elem in root.iter():
        for attr in STRIP_ATTRS:
            if attr in elem.attrib:
                del elem.attrib[attr]
                n += 1
    return n


def promote_plain_id_to_xml_id(root: etree._Element) -> int:
    """Rename ``id="x"`` -> ``xml:id="x"`` on every element. MediaWiki residue."""
    n = 0
    for elem in root.iter():
        if "id" in elem.attrib:
            value = elem.attrib.pop("id")
            elem.set(XID, value)
            n += 1
    return n


def is_inside_note(elem: etree._Element) -> bool:
    """True if elem is a descendant of a <note> element."""
    parent = elem.getparent()
    while parent is not None:
        if parent.tag == TEI + "note":
            return True
        parent = parent.getparent()
    return False


def assert_lb_n_required(root: etree._Element) -> list[str]:
    """Return a list of error messages for <lb> elements lacking @n outside notes."""
    errors: list[str] = []
    for lb in root.iter(TEI + "lb"):
        if lb.get("n"):
            continue
        if is_inside_note(lb):
            continue
        path = root.getroottree().getelementpath(lb) if root.getroottree() is not None else "<lb>"
        errors.append(f"<lb> without @n outside <note>: {path}")
    return errors


def drop_unnumbered_lb_outside_notes(root: etree._Element) -> int:
    """Last-resort cleanup: drop <lb/> elements that have no @n and live outside
    a <note>. Sprengel 1829 has some of these as stray formatting; the standard
    forbids them in the main text stream.
    """
    n = 0
    for lb in list(root.iter(TEI + "lb")):
        if lb.get("n"):
            continue
        if is_inside_note(lb):
            continue
        parent = lb.getparent()
        if parent is None:
            continue
        # Preserve tail text by transferring to previous sibling or parent.
        tail = lb.tail or ""
        prev = lb.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
        parent.remove(lb)
        n += 1
    return n
