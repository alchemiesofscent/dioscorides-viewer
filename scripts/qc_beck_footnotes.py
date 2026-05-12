#!/usr/bin/env python3
"""QC Beck footnote links and write the manual review queue."""

from __future__ import annotations

import argparse
import csv
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"tei": TEI}


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_ws(text: str) -> str:
    return " ".join(text.split())


def source_note_ids(source: Path) -> list[str]:
    root = ET.parse(source).getroot()
    ids: list[str] = []
    counter = 0
    for element in root.iter():
        if local_name(element.tag) == "note":
            counter += 1
            ids.append(element.get("id") or f"note-{counter}")
    return ids


def read_audit_rows(audit_dir: Path) -> list[dict[str, str]]:
    path = audit_dir / "footnotes.csv"
    if not path.exists():
        raise SystemExit(f"Missing footnote audit CSV: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def page_body_text_without_footnotes(root: ET.Element, page: str) -> str:
    pieces: list[str] = []
    state = {"in_page": False, "stop": False}

    def walk(element: ET.Element, excluded: bool = False) -> None:
        if state["stop"]:
            return
        tag = local_name(element.tag)
        if tag == "pb":
            if state["in_page"] and element.get("n") != page:
                state["stop"] = True
                return
            state["in_page"] = element.get("n") == page
            return

        excluded_here = excluded or tag == "fw" or (tag == "note" and element.get("type") == "footnote")
        if state["in_page"] and not excluded_here and element.text and element.text.strip():
            pieces.append(element.text)
        for child in list(element):
            walk(child, excluded_here)
            if state["stop"]:
                return
            if state["in_page"] and not excluded_here and child.tail and child.tail.strip():
                pieces.append(child.tail)

    walk(root)
    return normalize_ws(" ".join(pieces))


def footnote_pages(root: ET.Element) -> dict[str, str]:
    current_page = ""
    pages: dict[str, str] = {}
    for element in root.iter():
        tag = local_name(element.tag)
        if tag == "pb":
            current_page = element.get("n") or current_page
        elif tag == "note" and element.get("type") == "footnote":
            note_id = element.get(XML_ID) or ""
            if note_id:
                pages[note_id] = current_page
    return pages


def check_tei(tei: Path) -> tuple[list[str], dict[str, ET.Element], list[tuple[str, str]]]:
    issues: list[str] = []
    tree = ET.parse(tei)
    root = tree.getroot()

    bad_note_segs = [
        element
        for element in root.iter()
        if local_name(element.tag) == "seg" and element.get("subtype") == "note"
    ]
    if bad_note_segs:
        issues.append(f"SEG_SUBTYPE_NOTE: {len(bad_note_segs)} generated note segs remain")

    xml_ids = [element.get(XML_ID) for element in root.iter() if element.get(XML_ID)]
    duplicate_ids = [xml_id for xml_id, count in Counter(xml_ids).items() if count > 1]
    if duplicate_ids:
        issues.append(f"DUPLICATE_XML_ID: {len(duplicate_ids)} duplicate xml:id values")

    footnote_notes: dict[str, ET.Element] = {}
    footnote_refs: list[tuple[str, str]] = []
    refs_missing_id = 0
    empty_footnotes = []
    missing_body_placeholders = []
    for element in root.iter():
        name = local_name(element.tag)
        if name == "note" and element.get("type") == "footnote":
            note_id = element.get(XML_ID) or ""
            if note_id:
                footnote_notes[note_id] = element
            if element.get("subtype") == "missing-source-note-body":
                missing_body_placeholders.append(note_id or element.get("n") or "(no id)")
            if not normalize_ws("".join(element.itertext())):
                empty_footnotes.append(note_id or element.get("n") or "(no id)")
        elif name == "ref" and element.get("type") == "footnote-ref":
            ref_id = element.get(XML_ID) or ""
            target = (element.get("target") or "").lstrip("#")
            if not ref_id:
                refs_missing_id += 1
            if target:
                footnote_refs.append((target, ref_id))

    if refs_missing_id:
        issues.append(f"FOOTNOTE_REF_NO_XML_ID: {refs_missing_id} refs lack xml:id")
    if empty_footnotes:
        issues.append(f"FOOTNOTE_NOTE_EMPTY: {len(empty_footnotes)} generated footnote notes are empty")
    if missing_body_placeholders:
        issues.append(
            f"MISSING_SOURCE_NOTE_BODY_IN_TEI: {len(missing_body_placeholders)} placeholder footnote notes remain"
        )

    refs_by_target: dict[str, list[str]] = {}
    for target, ref_id in footnote_refs:
        refs_by_target.setdefault(target, []).append(ref_id)

    missing_targets = [target for target in refs_by_target if target not in footnote_notes]
    if missing_targets:
        issues.append(f"FOOTNOTE_TARGET_NO_NOTE: {len(missing_targets)} footnote targets lack note")

    incomplete = []
    bad_corresp = []
    for target, ref_ids in refs_by_target.items():
        note = footnote_notes.get(target)
        if note is None:
            continue
        if not (note.get(XML_ID) and note.get("n") and note.get("place") == "bottom" and note.get("corresp")):
            incomplete.append(target)
        expected = {f"#{ref_id}" for ref_id in ref_ids if ref_id}
        actual = set((note.get("corresp") or "").split())
        if expected and actual != expected:
            bad_corresp.append(target)

    if incomplete:
        issues.append(f"FOOTNOTE_NOTE_INCOMPLETE: {len(incomplete)} targeted notes missing required metadata")
    if bad_corresp:
        issues.append(f"FOOTNOTE_CORRESP_MISMATCH: {len(bad_corresp)} targeted notes have bad corresp")

    note_pages = footnote_pages(root)
    body_text_cache: dict[str, str] = {}
    body_leaks = []
    for note_id, note in footnote_notes.items():
        note_text = normalize_ws("".join(note.itertext()))
        page = note_pages.get(note_id, "")
        if not page or len(note_text) < 30:
            continue
        body_text = body_text_cache.setdefault(page, page_body_text_without_footnotes(root, page))
        if note_text in body_text:
            body_leaks.append(note_id)
    if body_leaks:
        issues.append(f"FOOTNOTE_BODY_SELECTION_LEAK: {len(body_leaks)} footnote bodies appear in page body text")

    return issues, footnote_notes, footnote_refs


def write_review_queue(audit_dir: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    review_rows = [
        row
        for row in rows
        if (row.get("status") or "").startswith("unresolved") or row.get("status") == "missing-source-note-body"
    ]
    review_csv = audit_dir / "review_queue.csv"
    fieldnames = [
        "source_id",
        "n",
        "page",
        "status",
        "evidence_status",
        "candidate_count",
        "source_parent",
        "source_parent_id",
        "note_xml_id",
        "ref_xml_id",
        "anchor_token_id",
        "candidate_summary",
        "note_excerpt",
    ]
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(review_rows)

    lines = [
        "# Beck Footnote Review Queue",
        "",
        f"- Manual cases: {len(review_rows)}",
        "",
    ]
    for row in review_rows:
        label = row.get("n") or row.get("source_id") or ""
        evidence = row.get("candidate_summary") or row.get("evidence_status") or "no evidence recorded"
        excerpt = row.get("note_excerpt") or "(empty source note)"
        lines.extend(
            [
                f"## {row.get('source_id')} page {row.get('page')} n={label}",
                "",
                f"- Status: `{row.get('status')}`",
                f"- Evidence: {evidence}",
                f"- Note: {excerpt}",
                "",
            ]
        )
    (audit_dir / "review_queue.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return review_rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Input Beck OCR/XML source")
    parser.add_argument("--tei", required=True, help="Generated Beck EpiDoc XML")
    parser.add_argument("--audit", required=True, help="Beck footnote audit directory")
    args = parser.parse_args()

    source = Path(args.source)
    tei = Path(args.tei)
    audit_dir = Path(args.audit)
    audit_dir.mkdir(parents=True, exist_ok=True)

    issues: list[str] = []
    source_ids = source_note_ids(source)
    rows = read_audit_rows(audit_dir)
    review_rows = write_review_queue(audit_dir, rows)
    row_by_source = {row.get("source_id", ""): row for row in rows}

    missing_audit = [source_id for source_id in source_ids if source_id not in row_by_source]
    if missing_audit:
        issues.append(f"SOURCE_NOTE_NOT_AUDITED: {len(missing_audit)} source notes lack audit rows")
    if len(source_ids) != 131:
        issues.append(f"SOURCE_NOTE_COUNT: expected 131, found {len(source_ids)}")

    tei_issues, footnote_notes, footnote_refs = check_tei(tei)
    issues.extend(tei_issues)

    generated_note_ids = set(footnote_notes)
    generated_ref_ids = {ref_id for _target, ref_id in footnote_refs if ref_id}
    review_source_ids = {row.get("source_id", "") for row in review_rows}
    uncovered = []
    for source_id in source_ids:
        row = row_by_source.get(source_id, {})
        note_id = row.get("note_xml_id", "")
        ref_id = row.get("ref_xml_id", "")
        if (
            note_id not in generated_note_ids
            and ref_id not in generated_ref_ids
            and source_id not in review_source_ids
        ):
            uncovered.append(source_id)
    if uncovered:
        issues.append(f"SOURCE_NOTE_NOT_GENERATED_OR_QUEUED: {len(uncovered)} source notes uncovered")

    unresolved_without_evidence = []
    for row in rows:
        if not (row.get("status") or "").startswith("unresolved"):
            continue
        evidence = row.get("evidence_status") or ""
        candidate_summary = row.get("candidate_summary") or ""
        if evidence == "no-candidate-found":
            continue
        if evidence == "candidate-set" and candidate_summary:
            continue
        unresolved_without_evidence.append(row.get("source_id") or "")
    if unresolved_without_evidence:
        issues.append(f"UNRESOLVED_WITHOUT_EVIDENCE: {len(unresolved_without_evidence)} unresolved notes lack candidate/no-candidate evidence")

    review_by_source = {row.get("source_id", ""): row for row in review_rows}
    unqueued_unresolved = []
    review_rows_missing_fields = []
    for row in rows:
        status = row.get("status") or ""
        if not (status.startswith("unresolved") or status == "missing-source-note-body"):
            continue
        source_id = row.get("source_id") or ""
        queued = review_by_source.get(source_id)
        if not queued:
            unqueued_unresolved.append(source_id)
            continue
        evidence = queued.get("candidate_summary") or queued.get("evidence_status") or queued.get("note_excerpt") or ""
        if not (queued.get("page") and queued.get("source_id") and evidence):
            review_rows_missing_fields.append(source_id)
    if unqueued_unresolved:
        issues.append(f"UNRESOLVED_NOT_IN_REVIEW_QUEUE: {len(unqueued_unresolved)} unresolved notes missing review rows")
    if review_rows_missing_fields:
        issues.append(f"REVIEW_QUEUE_ROW_INCOMPLETE: {len(review_rows_missing_fields)} review rows lack page/source/evidence")

    print(f"Source notes: {len(source_ids)}")
    print(f"Audit rows: {len(rows)}")
    print(f"Footnote refs: {len(footnote_refs)}")
    print(f"Footnote notes: {len(footnote_notes)}")
    print(f"Review queue: {len(review_rows)}")
    print(f"Wrote {audit_dir / 'review_queue.csv'}")
    print(f"Wrote {audit_dir / 'review_queue.md'}")
    if issues:
        print(f"\n{len(issues)} QC issues found")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("\nBeck footnote QC passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
