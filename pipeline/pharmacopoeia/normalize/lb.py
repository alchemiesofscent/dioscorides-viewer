"""Canonical `<lb/>` enforcement, shared by all migrations.

See docs/TEI_STANDARD.md for the rules. Briefly:
- ``<lb n="N"/>`` is the canonical form. @n is required outside ``<note>`` bodies.
- @break="no" is the canonical hyphenation marker.
- Forbidden attrs on <lb> and <pb>: bbox, cert, source, seq, plain `id`.
- Self-closing without trailing space (handled by serializer, not by us).
"""
from __future__ import annotations

import re

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"

# Attrs to strip from any element. Beck OCR adds bbox/cert/source/seq;
# legacy MediaWiki used plain `id` instead of `xml:id`.
STRIP_ATTRS = ("bbox", "cert", "source", "seq")
LB_TAG_RE = re.compile(r"<lb\b")
TRAILING_LINE_WS_RE = re.compile(r"[ \t]+(?=\n)")
XML_TAG_RE = re.compile(r"<!--.*?-->|<\?.*?\?>|<![^>]*>|</?[^>]+?>")
LB_ONLY_RE = re.compile(r"^<lb\b[^>]*/>$")
START_TAG_RE = re.compile(r"^<([A-Za-z_][\w:.-]*)\b")
BLOCK_LINE_START_TAGS = {
    "TEI",
    "ab",
    "back",
    "bibl",
    "body",
    "div",
    "fileDesc",
    "front",
    "fw",
    "head",
    "item",
    "l",
    "lg",
    "list",
    "note",
    "p",
    "pb",
    "publicationStmt",
    "respStmt",
    "sourceDesc",
    "teiHeader",
    "text",
    "titleStmt",
}


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


def lb_not_line_initial_count(xml_text: str) -> int:
    """Count ``<lb>`` start tags preceded by non-whitespace on the same line."""
    count = 0
    for match in LB_TAG_RE.finditer(xml_text):
        line_start = xml_text.rfind("\n", 0, match.start()) + 1
        if xml_text[line_start:match.start()].strip():
            count += 1
    return count


def put_lbs_at_line_start(xml_text: str) -> tuple[str, int]:
    """Insert a physical newline before every mid-line ``<lb>`` start tag.

    The TEI already treats ``<lb/>`` as the semantic line-start marker. This
    function only makes the source file match that convention visually, while
    preserving the tag, attributes, and following tail text.
    """
    pieces: list[str] = []
    last = 0
    moved = 0
    for match in LB_TAG_RE.finditer(xml_text):
        line_start = xml_text.rfind("\n", 0, match.start()) + 1
        prefix = xml_text[line_start:match.start()]
        if not prefix.strip():
            if prefix:
                pieces.append(xml_text[last:line_start])
                last = match.start()
            continue
        pieces.append(xml_text[last:match.start()])
        pieces.append("\n")
        last = match.start()
        moved += 1
    if not pieces:
        return xml_text, 0
    pieces.append(xml_text[last:])
    return "".join(pieces), moved


def _depth_after_xml_line(line: str, depth: int) -> int:
    for match in XML_TAG_RE.finditer(line):
        tag = match.group(0)
        if tag.startswith(("<?", "<!", "<!--")):
            continue
        if tag.startswith("</"):
            depth = max(0, depth - 1)
            continue
        if tag.rstrip().endswith("/>"):
            continue
        depth += 1
    return depth


def _can_join_lb_tail(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("</"):
        return False
    if stripped.startswith("<"):
        match = START_TAG_RE.match(stripped)
        if not match:
            return False
        tag = match.group(1)
        return tag != "lb" and tag not in BLOCK_LINE_START_TAGS
    return True


def join_split_lb_tail_lines(xml_text: str) -> tuple[str, int]:
    """Join text or inline markup back onto a preceding standalone ``<lb/>`` line."""
    lines = xml_text.splitlines()
    out: list[str] = []
    joined = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            i + 1 < len(lines)
            and LB_ONLY_RE.match(line.strip())
            and _can_join_lb_tail(lines[i + 1])
        ):
            out.append(f"{line}{lines[i + 1].strip()}")
            joined += 1
            i += 2
            continue
        out.append(line)
        i += 1
    trailing_newline = "\n" if xml_text.endswith("\n") else ""
    return "\n".join(out) + trailing_newline, joined


def indent_lb_lines_to_parent_depth(
    xml_text: str,
    space: str = "  ",
) -> tuple[str, int]:
    """Indent source lines whose first element is ``<lb/>`` to parent depth."""
    lines = xml_text.splitlines()
    out: list[str] = []
    depth = 0
    changed = 0
    for line in lines:
        stripped = line.lstrip(" \t")
        if stripped.startswith("<lb"):
            line = f"{space * depth}{stripped}"
        out.append(line)
        depth = _depth_after_xml_line(stripped, depth)
    trailing_newline = "\n" if xml_text.endswith("\n") else ""
    for before, after in zip(lines, out):
        if before != after and before.lstrip(" \t").startswith("<lb"):
            changed += 1
    return "\n".join(out) + trailing_newline, changed


def serialize_with_epidoc_indentation(
    tree: etree._ElementTree,
    space: str = "  ",
) -> tuple[str, dict[str, int]]:
    """Serialize a TEI tree with conventional hierarchy and indented ``<lb/>``.

    ``lxml`` handles structural indentation and processing-instruction/root
    separation. The text pass then fixes mixed-content line-break milestones,
    where generic XML pretty-printing cannot infer the printed-line convention.
    """
    etree.indent(tree.getroot(), space=space)
    xml_text = etree.tostring(
        tree,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
    ).decode("utf-8")
    xml_text, line_start_moved = put_lbs_at_line_start(xml_text)
    xml_text, tail_lines_joined = join_split_lb_tail_lines(xml_text)
    xml_text, lb_lines_indented = indent_lb_lines_to_parent_depth(xml_text, space)
    xml_text, trailing_ws_stripped = strip_trailing_line_whitespace(xml_text)
    return xml_text, {
        "line_start_moved": line_start_moved,
        "tail_lines_joined": tail_lines_joined,
        "lb_lines_indented": lb_lines_indented,
        "trailing_ws_stripped": trailing_ws_stripped,
    }


def strip_trailing_line_whitespace(xml_text: str) -> tuple[str, int]:
    """Strip spaces/tabs before physical newlines in serialized XML."""
    return TRAILING_LINE_WS_RE.subn("", xml_text)
