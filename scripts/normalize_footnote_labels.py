#!/usr/bin/env python3
"""Normalize printed footnote labels inside generated footnote note bodies."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


NOTE_RE = re.compile(
    r'(<note\b(?=[^>]*\btype="footnote")[^>]*>)([\s\S]*?)(</note>)'
)
REF_RE = re.compile(
    r'<ref\b(?=[^>]*\btype="footnote-ref")[^>]*>([\s\S]*?)</ref>'
)
TAG_RE = re.compile(r"<[^>]+>")


def label_text(ref_body: str) -> str:
    return TAG_RE.sub("", ref_body)


def normalize_text(text: str) -> tuple[str, int]:
    changed = 0

    def normalize_note(match: re.Match[str]) -> str:
        nonlocal changed
        start, body, end = match.groups()

        def normalize_ref(ref_match: re.Match[str]) -> str:
            nonlocal changed
            changed += 1
            return label_text(ref_match.group(1))

        return start + REF_RE.sub(normalize_ref, body) + end

    return NOTE_RE.sub(normalize_note, text), changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert footnote-ref elements inside footnote notes to plain printed labels."
    )
    parser.add_argument("--chunks-dir", default="chunks", help="Chunk directory to update")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    chunks_dir = Path(args.chunks_dir)
    total = 0
    files = 0
    for path in sorted(chunks_dir.glob("**/*.xml")):
        text = path.read_text(encoding="utf-8")
        updated, count = normalize_text(text)
        if not count:
            continue
        total += count
        files += 1
        if not args.dry_run:
            path.write_text(updated, encoding="utf-8")

    action = "Would normalize" if args.dry_run else "Normalized"
    print(f"{action} {total} footnote labels in {files} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
