"""Sprengel 1830 Commentarius migration: light normalization.

The source `editions/sprengel1830-comm/tei/edition.xml` was rebuilt by an
upstream process and already has clean TEI shape (657 chapter divs, 691
heads, 328 pbs, no MediaWiki residue). If that legacy source is absent, the
current corpus TEI is normalized in place. This migration only:

- enforces the canonical `<lb/>` standard (strip bloat attrs);
- rewrites `<pb @facs>` JP2 URLs to IIIF JPEG derivatives so the viewer can
  render them (browsers cannot render JPEG 2000).
- serializes with conventional EpiDoc-style hierarchy indentation and keeps
  `<lb/>` markers line-initial at their parent depth.
"""
from __future__ import annotations

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
        f"{facs_rewritten} JP2 facs URLs rewritten to IIIF JPEG, "
        f"{sources_restored} pb @source attrs restored, "
        f"{indent_stats['line_start_moved']} <lb> tags moved to line starts, "
        f"{indent_stats['tail_lines_joined']} <lb> tail lines joined, "
        f"{indent_stats['lb_lines_indented']} <lb> lines reindented, "
        f"{indent_stats['trailing_ws_stripped']} trailing line spaces stripped, "
        f"{remaining_midline_lbs} mid-line <lb> tags remain  ({out_path})"
    )
