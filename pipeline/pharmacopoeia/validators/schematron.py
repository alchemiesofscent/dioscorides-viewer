"""Schematron driver via lxml's isoschematron support.

This is a thin wrapper. The default ``working`` profile runs the rules in
``schemas/pharmacopoeia.sch`` against each migrated edition.

Note: lxml.isoschematron supports the XSLT 1.0 binding via libxslt. Our
schema uses queryBinding="xslt2" — fall back to "xslt" if isoschematron
rejects it.
"""
from __future__ import annotations

from lxml import etree, isoschematron

from pharmacopoeia.paths import SCHEMAS_ROOT, edition_tei


def _load_sch(name: str) -> isoschematron.Schematron:
    path = SCHEMAS_ROOT / name
    sch_doc = etree.parse(str(path))
    root = sch_doc.getroot()
    if root.get("queryBinding") == "xslt2":
        root.set("queryBinding", "xslt")
    return isoschematron.Schematron(sch_doc, store_report=True)


def validate_edition(
    edition: str, schema: str = "pharmacopoeia.sch",
) -> tuple[bool, list[str]]:
    path = edition_tei(edition)
    if not path.exists():
        return False, [f"edition file missing: {path}"]
    doc = etree.parse(str(path))
    schematron = _load_sch(schema)
    ok = schematron.validate(doc)
    report = schematron.validation_report
    msgs = []
    if report is not None:
        svrl = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
        for failed in report.xpath(".//svrl:failed-assert", namespaces=svrl):
            text = failed.findtext("svrl:text", namespaces=svrl)
            location = failed.get("location") or ""
            msgs.append(
                f"{location}: "
                f"{text.strip() if text else 'assertion failed'}"
            )
    return ok, msgs
