#!/usr/bin/env python3
"""QC Beck body-text clarity after OCR cleanup sidecars are applied."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
NS = {"tei": TEI}
FURNITURE_ROLES = {"header", "pageNum", "omit"}
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
GREEKISH_LATIN_RE = re.compile(
    r"(?:opOoKVOia|KSpCtTlOV|Oeppog|6\(3oX|8r/23|doOpa|Suojtvoia|pTyv|aurri)"
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_line_roles(audit: Path) -> dict[str, dict[str, str]]:
    rows = read_csv(audit / "line_roles.csv")
    return {
        row.get("source_line_id", ""): row
        for row in rows
        if row.get("source_line_id") and row.get("role") in FURNITURE_ROLES
    }


def read_corrections(audit: Path) -> set[str]:
    accepted = {"accepted", "approved", "auto", "auto-accepted"}
    return {
        row.get("source_token_id", "")
        for row in read_csv(audit / "token_corrections.csv")
        if row.get("source_token_id") and row.get("status") in accepted and row.get("corrected_text")
    }


def read_reviewed(audit: Path) -> set[str]:
    accepted = {"accepted", "approved", "auto", "auto-accepted", "reviewed", "manual-accepted"}
    reviewed: set[str] = set()
    for filename in ("review_acceptance.csv", "review_queue.csv"):
        for row in read_csv(audit / filename):
            status = row.get("status") or ""
            if status in accepted or (filename == "review_queue.csv" and row.get("evidence_note")):
                reviewed.add(row.get("source_token_id", ""))
    return reviewed


def source_body_token_ids(source: Path, line_roles: dict[str, dict[str, str]]) -> tuple[list[str], dict[str, str]]:
    root = ET.parse(source).getroot()
    current_line_id = ""
    body_ids: list[str] = []
    token_text: dict[str, str] = {}
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            current_line_id = ""
        elif tag == "lb":
            current_line_id = element.get("id") or ""
        elif tag == "tok":
            token_id = element.get("id") or ""
            text = normalize_ws("".join(element.itertext()))
            if not token_id or not text:
                continue
            token_text[token_id] = text
            role = (line_roles.get(current_line_id) or {}).get("role", "body")
            if role not in FURNITURE_ROLES:
                body_ids.append(token_id)
    return body_ids, token_text


def page_text(root: ET.Element, page: str) -> str:
    pieces: list[str] = []
    in_page = False
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            if in_page:
                break
            in_page = element.get("n") == page
            continue
        if in_page and tag not in {"fw", "note"}:
            text = element.text or ""
            if text.strip():
                pieces.append(text)
            tail = element.tail or ""
            if tail.strip():
                pieces.append(tail)
    return normalize_ws(" ".join(pieces))


def fw_texts(root: ET.Element, page: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    in_page = False
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            if in_page:
                break
            in_page = element.get("n") == page
            continue
        if in_page and tag == "fw":
            values.append((element.get("type") or "", normalize_ws("".join(element.itertext()))))
    return values


def token_in_tei(root: ET.Element, source_token_id: str) -> ET.Element | None:
    xml_id = "beck-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", source_token_id).strip("-")
    for element in root.iter():
        if element.get(XML_ID) == xml_id:
            return element
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Input Beck OCR/XML source")
    parser.add_argument("--tei", required=True, help="Generated Beck EpiDoc XML")
    parser.add_argument("--audit", required=True, help="Beck text-cleaning audit directory")
    args = parser.parse_args()

    source = Path(args.source)
    tei = Path(args.tei)
    audit = Path(args.audit)
    line_roles = read_line_roles(audit)
    corrected = read_corrections(audit)
    reviewed = read_reviewed(audit)
    token_audit = read_csv(audit / "token_audit.csv")
    body_ids, source_text = source_body_token_ids(source, line_roles)
    body_set = set(body_ids)

    issues: list[str] = []
    suspect_counts: Counter[str] = Counter()
    unresolved: list[dict[str, str]] = []
    for row in token_audit:
        token_id = row.get("source_token_id") or ""
        if token_id not in body_set:
            continue
        category = row.get("suspect_category") or ""
        if not category:
            continue
        suspect_counts[category] += 1
        if token_id in corrected or token_id in reviewed:
            continue
        unresolved.append(row)

    for token_id in body_ids:
        text = source_text.get(token_id, "")
        if token_id in corrected or token_id in reviewed:
            continue
        if GREEKISH_LATIN_RE.search(text) and not GREEK_RE.search(text):
            if not any(row.get("source_token_id") == token_id for row in unresolved):
                unresolved.append(
                    {
                        "source_token_id": token_id,
                        "source_text": text,
                        "suspect_category": "mixed-script-confusable",
                        "evidence": "source regex fallback",
                    }
                )

    unresolved_limit = max(1, int(len(body_ids) * 0.001))
    if len(unresolved) > unresolved_limit:
        issues.append(
            f"CLARITY_GATE: unresolved suspect body tokens {len(unresolved)} exceed 0.1% limit {unresolved_limit}"
        )

    tree = ET.parse(tei)
    root = tree.getroot()

    p14_fw = fw_texts(root, "14")
    if ("pageNum", "X") not in p14_fw:
        issues.append("PAGE_14_PAGENUM: expected X as fw type=pageNum")
    if " X " in f" {page_text(root, '14')} ":
        issues.append("PAGE_14_BODY_LEAK: page number X remains in body text")

    p15_fw = fw_texts(root, "15")
    if ("header", "Abbreviations and Signs") not in p15_fw:
        issues.append("PAGE_15_HEADER: expected Abbreviations and Signs as fw type=header")
    if page_text(root, "15").startswith("Abbreviations and Signs"):
        issues.append("PAGE_15_BODY_LEAK: running header remains as first body text")

    w5802 = token_in_tei(root, "w-5802")
    if w5802 is None or normalize_ws("".join(w5802.itertext())) != "ὀρθόπνοια" or local_name(w5802.tag) != "foreign":
        issues.append("PAGE_30_GREEK_CORRECTION: w-5802 was not corrected as Greek foreign text")

    for token_id in ("w-11626",):
        if token_id in corrected:
            issues.append(f"BOTANICAL_OVER_NORMALIZATION: unexpected correction recorded for {token_id}")

    print(f"Body tokens: {len(body_ids)}")
    print(f"Suspect tokens from audit: {sum(suspect_counts.values())}")
    for category, count in sorted(suspect_counts.items()):
        print(f"  - {category}: {count}")
    print(f"Corrected tokens: {len(corrected)}")
    print(f"Reviewed tokens: {len(reviewed)}")
    print(f"Unresolved suspect body tokens: {len(unresolved)}")
    print(f"Clarity accepted: {(len(body_ids) - len(unresolved)) / max(1, len(body_ids)):.5%}")
    if issues:
        print(f"\n{len(issues)} QC issues found")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("\nBeck text clarity QC passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
