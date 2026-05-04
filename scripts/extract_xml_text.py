#!/usr/bin/env python3
"""
Phase 3a: Extract plain text per book-page from existing XML.

Usage:
    python3 scripts/extract_xml_text.py "berendes (1).xml" --output ocr/xml_baseline.json

Splits the existing XML at <pb> boundaries, strips tags, outputs JSON
keyed by book page number.
"""

import argparse
import json
import re


def strip_tags(s):
    return re.sub(r'<[^>]+>', '', s).strip() if s else ""


def extract_text_by_page(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        text = f.read()

    # Find all pb positions and their page numbers
    pb_pattern = re.compile(r'<pb[^>]*\bn="([^"]+)"[^>]*>')
    pbs = [(m.start(), m.group(1)) for m in pb_pattern.finditer(text)]

    if not pbs:
        return {}

    # Deduplicate: keep first occurrence of each page number
    seen = set()
    unique_pbs = []
    for pos, page in pbs:
        if page not in seen:
            seen.add(page)
            unique_pbs.append((pos, page))

    pages = {}
    for i, (pos, page) in enumerate(unique_pbs):
        if i + 1 < len(unique_pbs):
            end = unique_pbs[i + 1][0]
        else:
            end = len(text)
        raw = text[pos:end]
        clean = strip_tags(raw)
        # Collapse whitespace
        clean = re.sub(r'\s+', ' ', clean).strip()
        if clean:
            pages[page] = clean

    return pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("xml_file")
    parser.add_argument("--output", default="ocr/xml_baseline.json")
    args = parser.parse_args()

    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    pages = extract_text_by_page(args.xml_file)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(pages, f, indent=2, ensure_ascii=False)

    print("Extracted text for %d pages" % len(pages))
    # Show sample
    for key in list(pages.keys())[:3]:
        snippet = pages[key][:80]
        print("  page %s: %s..." % (key, snippet))


if __name__ == "__main__":
    main()
