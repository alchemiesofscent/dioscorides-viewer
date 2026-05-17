#!/usr/bin/env python3
"""
Phase 6d: Compare new edition against existing XML for chapter coverage.

Usage:
    python3 scripts/diff_chapters.py "berendes (1).xml" editions/berendes1902/tei/edition.xml
"""

import argparse
import re
import sys


def extract_chapters(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        text = f.read()
    # Find all chapter n= values
    chapters = set()
    for m in re.finditer(r'(?:subtype="chapter"|type="chapter")\s+n="([^"]+)"', text):
        chapters.add(m.group(1))
    return chapters


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("old_xml")
    parser.add_argument("new_xml")
    args = parser.parse_args()

    old = extract_chapters(args.old_xml)
    new = extract_chapters(args.new_xml)

    missing = old - new
    extra = new - old
    common = old & new

    print("Old XML: %d chapters" % len(old))
    print("New XML: %d chapters" % len(new))
    print("Common:  %d" % len(common))

    if missing:
        print("\nMissing from new (%d):" % len(missing))
        for ch in sorted(missing):
            print("  %s" % ch)
    if extra:
        print("\nExtra in new (%d):" % len(extra))
        for ch in sorted(extra):
            print("  %s" % ch)

    if not missing and not extra:
        print("\nPerfect match!")

    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
