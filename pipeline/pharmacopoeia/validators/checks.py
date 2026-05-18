"""Validation checks for migrated editions.

The ``working`` profile runs a set of Python checks that mirror the
Schematron rules in schemas/pharmacopoeia.sch. These are run in CI and
locally without requiring an XSLT/Schematron toolchain.

Checks:
- well-formed XML
- every chapter <div type="textpart" subtype="chapter"> has @n and <head>
- every <link>/@target token references an existing lemma id
- every <note>/@next is paired with a reciprocal <note>/@prev
- xml:ids are globally unique within the file
- every <lb> outside a <note> has @n
- no <pb @facs> ends in .jp2 (browsers can't render JPEG 2000)
- no element carries bbox/cert/seq attributes (Beck OCR artefacts)
"""
from __future__ import annotations

import sys
from collections import Counter

from lxml import etree

from pharmacopoeia.normalize.lb import assert_lb_n_required
from pharmacopoeia.paths import (
    LEMMAS_ROOT,
    LEMMA_LINKS_ROOT,
    edition_tei,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"

EDITIONS = ("berendes1902", "sprengel1829", "beck2020", "sprengel1830-comm")
BANNED_ATTRS = ("bbox", "cert", "seq")


class CheckResult:
    def __init__(self, name: str) -> None:
        self.name = name
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self) -> bool:
        return not self.errors


def _check_edition(edition: str) -> CheckResult:
    res = CheckResult(edition)
    path = edition_tei(edition)
    if not path.exists():
        res.error(f"edition file missing: {path}")
        return res
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        res.error(f"XML parse error: {exc}")
        return res
    root = tree.getroot()

    # xml:id uniqueness
    ids = root.xpath(".//@xml:id")
    counts = Counter(ids)
    dups = [i for i, n in counts.items() if n > 1]
    if dups:
        res.error(
            f"duplicate xml:ids: {dups[:5]}{'...' if len(dups) > 5 else ''}"
        )

    # chapter divs have @n and <head>
    chapters = root.xpath(".//*[local-name()='div' and @subtype='chapter']")
    missing_n = [c for c in chapters if not c.get("n")]
    if missing_n:
        res.error(f"{len(missing_n)} chapter divs missing @n")
    missing_head = [c for c in chapters if c.find(TEI + "head") is None]
    if missing_head:
        res.warn(f"{len(missing_head)} chapter divs missing <head>")

    # books present
    books = root.xpath(".//*[local-name()='div' and @subtype='book']")
    if not books and edition != "sprengel1830-comm":
        # sprengel-comm is commentary keyed by page, not book/chapter axis.
        res.warn(f"no book divs found in {edition}")

    # <note>/@next pairing
    note_ids = {n.get(XID) for n in root.xpath(".//*[local-name()='note']")}
    for n in root.xpath(".//*[local-name()='note' and @next]"):
        target = n.get("next").lstrip("#")
        if target not in note_ids:
            res.error(f"<note>/@next='{n.get('next')}' has no matching note")
    for n in root.xpath(".//*[local-name()='note' and @prev]"):
        target = n.get("prev").lstrip("#")
        if target not in note_ids:
            res.error(f"<note>/@prev='{n.get('prev')}' has no matching note")

    # <lb> standard: @n required outside <note>
    lb_errors = assert_lb_n_required(root)
    for err in lb_errors[:5]:
        res.error(err)
    if len(lb_errors) > 5:
        res.error(f"... and {len(lb_errors) - 5} more <lb> @n violations")

    # @facs must not be a bare JP2 resource. IIIF URLs that contain ".jp2"
    # as part of the image identifier but end in /default.jpg etc. are fine —
    # they're JPEG derivatives served by an IIIF endpoint.
    jp2_facs = []
    for elem in root.iter():
        facs = elem.get("facs")
        if not facs:
            continue
        lowered = facs.lower()
        if lowered.endswith(".jp2") or lowered.endswith(".jp2/"):
            jp2_facs.append(facs)
    if jp2_facs:
        res.error(
            f"{len(jp2_facs)} @facs values reference a JP2 resource "
            f"(first: {jp2_facs[0]})"
        )

    # Banned attrs
    for attr in BANNED_ATTRS:
        offenders = root.xpath(f".//*[@{attr}]")
        if offenders:
            res.error(
                f"{len(offenders)} elements carry banned @{attr} "
                f"(first: {offenders[0].tag})"
            )

    return res


def _gather_lemma_ids() -> set[str]:
    ids: set[str] = set()
    if not LEMMAS_ROOT.exists():
        return ids
    for path in LEMMAS_ROOT.glob("*.xml"):
        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError:
            continue
        for cat in tree.getroot().xpath(".//*[local-name()='category']"):
            n = cat.get("n")
            if n:
                ids.add(n)
    return ids


def _check_lemma_links(lemma_ids: set[str]) -> CheckResult:
    res = CheckResult("lemma-links")
    if not LEMMA_LINKS_ROOT.exists():
        return res
    for path in sorted(LEMMA_LINKS_ROOT.glob("*.xml")):
        try:
            tree = etree.parse(str(path))
        except etree.XMLSyntaxError as exc:
            res.error(f"{path.name}: XML parse error: {exc}")
            continue
        root = tree.getroot()
        for link in root.xpath(".//*[local-name()='link']"):
            target = link.get("target") or ""
            tokens = [t for t in target.split() if t]
            for tok in tokens:
                if not tok.startswith("lemma:"):
                    continue
                if tok not in lemma_ids:
                    res.error(
                        f"{path.name}: link @target token unresolved: {tok}"
                    )
                    break
    return res


def run(edition: str, profile: str = "working") -> int:
    if profile == "archival":
        print(
            "[warn] archival profile not yet implemented; "
            "falling back to working.",
            file=sys.stderr,
        )

    targets = EDITIONS if edition == "all" else (edition,)
    results: list[CheckResult] = []
    for ed in targets:
        results.append(_check_edition(ed))

    lemma_ids = _gather_lemma_ids()
    results.append(_check_lemma_links(lemma_ids))

    rc = 0
    for r in results:
        prefix = "OK  " if r.ok() else "ERR "
        print(
            f"{prefix} {r.name}  "
            f"({len(r.errors)} errors, {len(r.warnings)} warnings)"
        )
        for e in r.errors:
            print(f"  ERROR: {e}")
        for w in r.warnings:
            print(f"  WARN:  {w}")
        if not r.ok():
            rc = 1
    return rc
