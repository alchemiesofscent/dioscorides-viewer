"""Sprengel 1830 Commentarius migration: light normalization.

The source `editions/sprengel1830-comm/tei/edition.xml` was rebuilt by an
upstream process and already has clean TEI shape (657 chapter divs, 691
heads, 328 pbs, no MediaWiki residue). This migration only:

- enforces the canonical `<lb/>` standard (strip bloat attrs);
- rewrites `<pb @facs>` JP2 URLs to IIIF JPEG derivatives so the viewer can
  render them (browsers cannot render JPEG 2000).
"""
from __future__ import annotations

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    promote_plain_id_to_xml_id,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "sprengel1830-comm"
NEW_ID = "sprengel1830-comm"


def run() -> None:
    src_path = legacy_edition_tei(LEGACY_ID)
    if not src_path.exists():
        raise FileNotFoundError(
            f"Source Sprengel-comm TEI not found: {src_path}"
        )

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    promote_plain_id_to_xml_id(root)
    strip_bloat_attrs(root)
    facs_rewritten = rewrite_pb_facs(root)

    out_path = edition_tei(NEW_ID)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        str(out_path),
        pretty_print=False,
        xml_declaration=True,
        encoding="utf-8",
    )
    in_lines = src_path.read_text(encoding="utf-8").count("\n")
    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    print(
        f"sprengel1830-comm: {in_lines} -> {out_lines} lines, "
        f"{facs_rewritten} JP2 facs URLs rewritten to IIIF JPEG  ({out_path})"
    )
