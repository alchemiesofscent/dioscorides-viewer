"""Sprengel 1830 Commentarius migration: light normalization.

The source `editions/sprengel1830-comm/tei/edition.xml` was rebuilt by an
upstream process and already has clean TEI shape (657 chapter divs, 691
heads, 328 pbs, no MediaWiki residue). If that legacy source is absent, the
current corpus TEI is normalized in place. This migration only:

- enforces the canonical `<lb/>` standard (strip bloat attrs);
- removes `<lb/>` milestones from `<fw>` page furniture;
- moves recurring bottom signatures out of body paragraphs into `<fw>`;
- inserts missing body-line `<lb/>` milestones at the start of body
  paragraphs/headings, removes empty body-line milestones, then renumbers
  main body lines page-by-page;
- rewrites `<pb @facs>` JP2 URLs to IIIF JPEG derivatives so the viewer can
  render them (browsers cannot render JPEG 2000).
- serializes with conventional EpiDoc-style hierarchy indentation and keeps
  `<lb/>` markers line-initial at their parent depth.
"""
from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    lb_not_line_initial_count,
    promote_plain_id_to_xml_id,
    serialize_with_epidoc_indentation,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "sprengel1830-comm"
NEW_ID = "sprengel1830-comm"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"
MAIN_START_TAGS = {TEI + "p", TEI + "head"}
IGNORED_LINE_CONTEXTS = {TEI + "fw", TEI + "note"}
LINE_BOUNDARY_TAGS = {
    TEI + "lb",
    TEI + "pb",
    TEI + "fw",
    TEI + "note",
    TEI + "p",
    TEI + "head",
    TEI + "div",
    TEI + "cb",
}
LINE_CONTAINER_TAGS = {TEI + "p", TEI + "head", TEI + "fw", TEI + "note"}
SIGNATURE_RE = re.compile(r"^DIOSCORIDES\s+II\.\s+[A-Za-z ]{1,3}$")


def _source_path(out_path: Path) -> tuple[Path, bool]:
    legacy_path = legacy_edition_tei(LEGACY_ID)
    if legacy_path.exists():
        return legacy_path, False
    if out_path.exists():
        return out_path, True
    raise FileNotFoundError(
        f"Source Sprengel-comm TEI not found: {legacy_path} or {out_path}"
    )


def _pb_key(pb: etree._Element) -> tuple[str, str, str]:
    return (pb.get(XID) or "", pb.get("n") or "", pb.get("facs") or "")


def _preserve_pb_sources(root: etree._Element) -> dict[tuple[str, str, str], str]:
    sources: dict[tuple[str, str, str], str] = {}
    for pb in root.iter(TEI + "pb"):
        source = pb.get("source")
        if source:
            sources[_pb_key(pb)] = source
    return sources


def _restore_pb_sources(
    root: etree._Element,
    sources: dict[tuple[str, str, str], str],
) -> int:
    restored = 0
    for pb in root.iter(TEI + "pb"):
        if pb.get("source"):
            continue
        source = sources.get(_pb_key(pb))
        if source:
            pb.set("source", source)
            restored += 1
    return restored


def _inside(elem: etree._Element, tags: set[str]) -> bool:
    parent = elem.getparent()
    while parent is not None:
        if parent.tag in tags:
            return True
        parent = parent.getparent()
    return False


def _inside_body(elem: etree._Element) -> bool:
    return _inside(elem, {TEI + "body"})


def _new_lb() -> etree._Element:
    return etree.Element(TEI + "lb")


def _remove_lb_preserving_text(lb: etree._Element) -> None:
    parent = lb.getparent()
    if parent is None:
        return
    replacement = (lb.text or "") + (lb.tail or "")
    prev = lb.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + replacement
    else:
        parent.text = (parent.text or "") + replacement
    parent.remove(lb)


def _unwrap_fw_lbs(root: etree._Element) -> int:
    removed = 0
    for fw in root.iter(TEI + "fw"):
        for lb in list(fw.iter(TEI + "lb")):
            _remove_lb_preserving_text(lb)
            removed += 1
    return removed


def _normalized_text(elem: etree._Element) -> str:
    return " ".join("".join(elem.itertext()).split())


def _move_signature_paragraphs_to_fw(root: etree._Element) -> int:
    moved = 0
    for p in list(root.iter(TEI + "p")):
        if not _inside_body(p) or _inside(p, IGNORED_LINE_CONTEXTS):
            continue
        text = _normalized_text(p)
        if not SIGNATURE_RE.match(text):
            continue
        parent = p.getparent()
        if parent is None:
            continue
        fw = etree.Element(TEI + "fw")
        fw.set("type", "sig")
        fw.set("place", "bottom")
        fw.text = text
        fw.tail = p.tail
        parent[parent.index(p)] = fw
        moved += 1
    return moved


def _insert_lb_after_child(
    elem: etree._Element,
    child: etree._Element,
    index: int,
) -> bool:
    tail = child.tail or ""
    if not tail.strip():
        return False
    lb = _new_lb()
    lb.tail = tail
    child.tail = None
    elem.insert(index + 1, lb)
    return True


def _insert_missing_leading_lb(elem: etree._Element) -> bool:
    if elem.tag not in MAIN_START_TAGS:
        return False
    if not _inside_body(elem) or _inside(elem, IGNORED_LINE_CONTEXTS):
        return False

    if elem.text and elem.text.strip():
        lb = _new_lb()
        lb.tail = elem.text
        elem.text = None
        elem.insert(0, lb)
        return True

    for index, child in enumerate(list(elem)):
        if not isinstance(child.tag, str):
            continue
        if child.tag == TEI + "lb":
            return False
        if child.tag in IGNORED_LINE_CONTEXTS or child.tag == TEI + "pb":
            if _insert_lb_after_child(elem, child, index):
                return True
            continue
        lb = _new_lb()
        elem.insert(index, lb)
        return True
    return False


def _insert_missing_leading_lbs(root: etree._Element) -> int:
    inserted = 0
    for elem in root.iter():
        if _insert_missing_leading_lb(elem):
            inserted += 1
    return inserted


def _line_text_from_element(elem: etree._Element) -> tuple[str, bool]:
    if elem.tag in LINE_BOUNDARY_TAGS:
        return "", True

    parts = [elem.text or ""]
    for child in elem:
        child_text, stopped = _line_text_from_element(child)
        parts.append(child_text)
        if stopped:
            return "".join(parts), True
        parts.append(child.tail or "")
    return "".join(parts), False


def _line_text_after_lb(lb: etree._Element) -> str:
    parts = [lb.tail or ""]
    current = lb
    while True:
        for sibling in current.itersiblings():
            if not isinstance(sibling.tag, str):
                parts.append(sibling.tail or "")
                continue
            text, stopped = _line_text_from_element(sibling)
            parts.append(text)
            if stopped:
                return "".join(parts)
            parts.append(sibling.tail or "")

        parent = current.getparent()
        if parent is None or parent.tag in LINE_CONTAINER_TAGS:
            return "".join(parts)
        parts.append(parent.tail or "")
        current = parent


def _remove_empty_main_lbs(root: etree._Element) -> int:
    removed = 0
    for lb in list(root.iter(TEI + "lb")):
        if _inside(lb, IGNORED_LINE_CONTEXTS):
            continue
        if _line_text_after_lb(lb).strip():
            continue
        _remove_lb_preserving_text(lb)
        removed += 1
    return removed


def _renumber_main_lbs_by_page(root: etree._Element) -> int:
    changed = 0
    next_n: int | None = None
    for elem in root.iter():
        if elem.tag == TEI + "pb":
            next_n = 1
            continue
        if elem.tag != TEI + "lb" or next_n is None:
            continue
        if _inside(elem, IGNORED_LINE_CONTEXTS):
            continue
        new_n = str(next_n)
        if elem.get("n") != new_n:
            changed += 1
        elem.set("n", new_n)
        next_n += 1
    return changed


def normalize_page_line_numbering(root: etree._Element) -> dict[str, int]:
    """Normalize Sprengel commentary body line numbering page-by-page.

    `<fw>` and `<note>` are outside the body-line stream. Notes keep their
    internal `<lb/>` values as encoded visual breaks.
    """
    signature_paragraphs_moved = _move_signature_paragraphs_to_fw(root)
    fw_lbs_removed = _unwrap_fw_lbs(root)
    leading_lbs_inserted = _insert_missing_leading_lbs(root)
    empty_main_lbs_removed = _remove_empty_main_lbs(root)
    main_lbs_renumbered = _renumber_main_lbs_by_page(root)
    return {
        "signature_paragraphs_moved": signature_paragraphs_moved,
        "fw_lbs_removed": fw_lbs_removed,
        "leading_lbs_inserted": leading_lbs_inserted,
        "empty_main_lbs_removed": empty_main_lbs_removed,
        "main_lbs_renumbered": main_lbs_renumbered,
    }


def run() -> None:
    out_path = edition_tei(NEW_ID)
    src_path, used_corpus_source = _source_path(out_path)

    parser = etree.XMLParser(remove_blank_text=False)
    in_text = src_path.read_text(encoding="utf-8")
    in_lines = in_text.count("\n")
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    preserved_sources = _preserve_pb_sources(root) if used_corpus_source else {}
    promote_plain_id_to_xml_id(root)
    strip_bloat_attrs(root)
    line_stats = normalize_page_line_numbering(root)
    facs_rewritten = rewrite_pb_facs(root)
    sources_restored = _restore_pb_sources(root, preserved_sources)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    xml_text, indent_stats = serialize_with_epidoc_indentation(tree)
    out_path.write_text(xml_text, encoding="utf-8")

    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    remaining_midline_lbs = lb_not_line_initial_count(xml_text)
    output_state = "changed" if in_text != xml_text else "unchanged"
    print(
        f"sprengel1830-comm: {in_lines} -> {out_lines} lines, "
        f"output {output_state}, "
        f"{line_stats['signature_paragraphs_moved']} signature paragraphs moved to <fw>, "
        f"{line_stats['fw_lbs_removed']} <fw> <lb> tags unwrapped, "
        f"{line_stats['leading_lbs_inserted']} leading body <lb> tags inserted, "
        f"{line_stats['empty_main_lbs_removed']} empty main body <lb> tags removed, "
        f"{line_stats['main_lbs_renumbered']} main body <lb> tags renumbered, "
        f"{facs_rewritten} JP2 facs URLs rewritten to IIIF JPEG, "
        f"{sources_restored} pb @source attrs restored, "
        f"{indent_stats['line_start_moved']} <lb> tags moved to line starts, "
        f"{indent_stats['tail_lines_joined']} <lb> tail lines joined, "
        f"{indent_stats['lb_lines_indented']} <lb> lines reindented, "
        f"{indent_stats['trailing_ws_stripped']} trailing line spaces stripped, "
        f"{remaining_midline_lbs} mid-line <lb> tags remain  ({out_path})"
    )
