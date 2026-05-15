#!/usr/bin/env python3
"""Create diplomatic Beck fresh structure and review ledgers."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from beck_fresh_diplomatic import (
    DEFAULT_AUDIT_SUMMARY,
    DEFAULT_BACK_MATTER_TRIAGE_LEDGER,
    DEFAULT_FRESH_DIR,
    DEFAULT_FRESH_MANIFEST,
    DEFAULT_SOURCE_XML,
    DEFAULT_STRUCTURE_LEDGER,
    DEFAULT_TEXT_CORRECTION_LEDGER,
    EXPECTED_CHAPTERS,
    chapter_counts,
    ensure_back_matter_triage_ledger,
    ensure_text_correction_ledger,
    read_csv_rows,
    repo_display_path,
    write_structure_ledger,
)


def count_files(path: Path, pattern: str) -> int:
    return len(list(path.glob(pattern))) if path.exists() else 0


def footnote_status_counts(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not path.exists():
        return counts
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[row.get("status") or ""] += 1
    return counts


def low_confidence_counts(path: Path) -> tuple[int, int]:
    if not path.exists():
        return (0, 0)
    total = 0
    greek = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            total += 1
            text = row.get("text") or ""
            if any("\u0370" <= char <= "\u03ff" or "\u1f00" <= char <= "\u1fff" for char in text):
                greek += 1
    return total, greek


def write_summary(
    path: Path,
    structure_rows: list[dict[str, str]],
    triage_rows: list[dict[str, str]],
    fresh_dir: Path,
    manifest_path: Path,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    chapter_counter = chapter_counts(structure_rows)
    issue_counts = Counter(row.get("issue_code") or "none" for row in structure_rows)
    source_type_counts = Counter(row.get("source_type") or "unknown" for row in structure_rows)
    footnote_counts = footnote_status_counts(fresh_dir / "qa" / "footnote_links.csv")
    low_total, low_greek = low_confidence_counts(fresh_dir / "qa" / "low_confidence_regions.csv")
    accepted_links = len(read_csv_rows(fresh_dir / "review" / "accepted_footnote_links.csv"))
    accepted_transcriptions = len(read_csv_rows(fresh_dir / "review" / "accepted_footnote_transcriptions.csv"))

    lines = [
        "# Beck Fresh Diplomatic Structure Audit",
        "",
        "This audit bootstraps the private, image-first diplomatic EpiDoc workflow. The page image remains the authority; `beck.xml` supplies structural alignment evidence only.",
        "",
        "## Source Counts",
        "",
        f"- Fresh manifest pages: {manifest.get('total_pages', 'unknown')}",
        f"- Fresh PDF pages: {manifest.get('pdf_total_pages', 'unknown')}",
        f"- Fresh images: {count_files(fresh_dir / 'images', 'beck-*.png')}",
        f"- Fresh hOCR files: {count_files(fresh_dir / 'hocr', 'beck-*.hocr')}",
        f"- Fresh TXT files: {count_files(fresh_dir / 'txt', 'beck-*.txt')}",
        "",
        "## Structure Ledger",
        "",
        f"- Ledger rows: {len(structure_rows)}",
    ]
    for source_type, count in sorted(source_type_counts.items()):
        lines.append(f"- `{source_type}` rows: {count}")
    lines.extend(["", "## Chapter Counts", ""])
    for book, expected in EXPECTED_CHAPTERS.items():
        observed = chapter_counter.get(book, 0)
        status = "ok" if observed == expected else "mismatch"
        lines.append(f"- Book {book}: {observed}/{expected} chapters ({status})")
    lines.extend(["", "## Structure Issue Codes", ""])
    for issue, count in sorted(issue_counts.items()):
        lines.append(f"- `{issue}`: {count}")
    lines.extend(
        [
            "",
            "## Footnote Review State",
            "",
            f"- Accepted link rows: {accepted_links}",
            f"- Accepted transcription rows: {accepted_transcriptions}",
        ]
    )
    for status, count in sorted(footnote_counts.items()):
        lines.append(f"- `{status}` QA rows: {count}")
    lines.extend(
        [
            "",
            "## Text Correction State",
            "",
            f"- Low-confidence rows: {low_total}",
            f"- Low-confidence Greek-script rows: {low_greek}",
            f"- Text correction ledger: `{repo_display_path(DEFAULT_TEXT_CORRECTION_LEDGER)}`",
            "",
            "## Back Matter Triage",
            "",
            f"- Triage rows: {len(triage_rows)}",
        ]
    )
    triage_counts = Counter(row.get("classification") or "unknown" for row in triage_rows)
    for classification, count in sorted(triage_counts.items()):
        lines.append(f"- `{classification}`: {count}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Structure ledger: `{repo_display_path(DEFAULT_STRUCTURE_LEDGER)}`",
            f"- Text correction ledger: `{repo_display_path(DEFAULT_TEXT_CORRECTION_LEDGER)}`",
            f"- Back-matter triage ledger: `{repo_display_path(DEFAULT_BACK_MATTER_TRIAGE_LEDGER)}`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-xml", default=DEFAULT_SOURCE_XML)
    parser.add_argument("--fresh-dir", default=DEFAULT_FRESH_DIR)
    parser.add_argument("--manifest", default=DEFAULT_FRESH_MANIFEST)
    parser.add_argument("--structure-ledger", default=DEFAULT_STRUCTURE_LEDGER)
    parser.add_argument("--text-correction-ledger", default=DEFAULT_TEXT_CORRECTION_LEDGER)
    parser.add_argument("--back-matter-triage-ledger", default=DEFAULT_BACK_MATTER_TRIAGE_LEDGER)
    parser.add_argument("--summary", default=DEFAULT_AUDIT_SUMMARY)
    args = parser.parse_args()

    source_xml = Path(args.source_xml)
    fresh_dir = Path(args.fresh_dir)
    manifest_path = Path(args.manifest)
    if not source_xml.exists():
        print(f"ERROR: missing source XML {source_xml}", file=sys.stderr)
        return 1
    if not manifest_path.exists():
        print(f"ERROR: missing fresh manifest {manifest_path}", file=sys.stderr)
        return 1

    structure_rows = write_structure_ledger(Path(args.structure_ledger), source_xml, fresh_dir)
    ensure_text_correction_ledger(Path(args.text_correction_ledger))
    triage_rows = ensure_back_matter_triage_ledger(
        Path(args.back_matter_triage_ledger),
        structure_rows,
        manifest_path,
    )
    write_summary(Path(args.summary), structure_rows, triage_rows, fresh_dir, manifest_path)

    counts = chapter_counts(structure_rows)
    print(f"Wrote {args.structure_ledger} ({len(structure_rows)} rows)")
    print(f"Wrote {args.text_correction_ledger}")
    print(f"Wrote {args.back_matter_triage_ledger} ({len(triage_rows)} rows)")
    print(f"Wrote {args.summary}")
    print("Chapter counts:", ", ".join(f"{book}={counts.get(book, 0)}" for book in sorted(EXPECTED_CHAPTERS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
