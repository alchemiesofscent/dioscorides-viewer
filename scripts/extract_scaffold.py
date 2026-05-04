#!/usr/bin/env python3
"""
Phase 2b: Extract chapter structure from existing XML as reference scaffold.

Usage:
    python3 scripts/extract_scaffold.py "berendes (1).xml" --output scaffold.json
"""

import argparse
import json
import re


def strip_tags(s):
    """Remove HTML/XML tags from a string."""
    return re.sub(r'<[^>]+>', '', s).strip() if s else s


def extract_scaffold(xml_path):
    with open(xml_path, "r", encoding="utf-8") as f:
        text = f.read()

    chapters = []

    div_pattern = re.compile(r'<div\s+type="chapter"([^>]*)>', re.DOTALL)

    for m in div_pattern.finditer(text):
        attrs_str = m.group(1)
        pos = m.start()

        n = re.search(r'n="([^"]+)"', attrs_str)
        tuid = re.search(r'tuid="([^"]+)"', attrs_str)
        div_id = re.search(r'id="([^"]+)"', attrs_str)

        preceding_text = text[max(0, pos - 500):pos]
        pb_matches = list(re.finditer(r'<pb[^>]*n="([^"]+)"[^>]*/?\s*>', preceding_text))
        page = pb_matches[-1].group(1) if pb_matches else None

        after_text = text[pos:pos + 500]
        ms = re.search(r'<milestone[^>]*display="([^"]+)"[^>]*/?\s*>', after_text)
        display_name = ms.group(1) if ms else None

        grk = re.search(r'<span\s+type="grk">(.*?)</span>', after_text)
        greek_heading = grk.group(1).strip() if grk else None

        deu = re.search(r'<span\s+type="deu"><b>(.*?)</b></span>', after_text)
        if not deu:
            deu = re.search(r'<span\s+type="deu">(.*?)</span>', after_text)
        german_title = deu.group(1).strip() if deu else display_name

        cap = re.search(r'<span\s+type="num">(.*?)</span>', after_text)
        cap_label = cap.group(1).strip() if cap else None

        chapters.append({
            "n": n.group(1) if n else None,
            "tuid": tuid.group(1) if tuid else None,
            "id": div_id.group(1) if div_id else None,
            "page": page,
            "display_name": display_name,
            "greek_heading": strip_tags(greek_heading),
            "german_title": strip_tags(german_title),
            "cap_label": strip_tags(cap_label),
        })

    book_chapters = {}
    for ch in chapters:
        if ch["n"]:
            book_num = ch["n"].split(".")[0]
            book_chapters.setdefault(book_num, []).append(ch)

    return {
        "total_chapters": len(chapters),
        "books": {k: len(v) for k, v in book_chapters.items()},
        "chapters": chapters,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("xml_file")
    parser.add_argument("--output", default="scaffold.json")
    args = parser.parse_args()

    scaffold = extract_scaffold(args.xml_file)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(scaffold, f, indent=2, ensure_ascii=False)

    total = scaffold["total_chapters"]
    print("Extracted %d chapters" % total)
    for book, count in scaffold["books"].items():
        print("  Book %s: %d chapters" % (book, count))


if __name__ == "__main__":
    main()
