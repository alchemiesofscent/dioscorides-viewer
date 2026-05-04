#!/usr/bin/env python3
"""
Phase 2a: Build page manifest with section assignments and chunk definitions.

Usage:
    python3 scripts/build_manifest.py --chunk-size 5 --output manifest.json

Outputs manifest.json with:
  - pages: list of all text pages with metadata
  - chunks: list of chunk definitions (groups of N pages) with section/id
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from page_map import all_text_pages, SECTIONS


def build_chunks(pages: list[dict], chunk_size: int) -> list[dict]:
    """Group pages into chunks, respecting section boundaries."""
    chunks = []
    # Group pages by section first
    section_pages = {}
    for p in pages:
        sec = p["section"] or "unknown"
        section_pages.setdefault(sec, []).append(p)

    for section_name in SECTIONS:
        sec_pages = section_pages.get(section_name, [])
        if not sec_pages:
            continue

        for i in range(0, len(sec_pages), chunk_size):
            batch = sec_pages[i:i + chunk_size]
            chunk_idx = i // chunk_size + 1
            chunk_id = f"{section_name}_{chunk_idx:03d}"
            chunks.append({
                "id": chunk_id,
                "section": section_name,
                "section_type": SECTIONS[section_name]["type"],
                "pages": [p["book_page"] for p in batch],
                "pdf_pages": [p["pdf_page"] for p in batch],
                "images": [p["image"] for p in batch],
                "facs": [p["facs"] for p in batch],
                "page_count": len(batch),
            })

    return chunks


def main():
    parser = argparse.ArgumentParser(description="Build page manifest and chunk definitions")
    parser.add_argument("--chunk-size", type=int, default=5, help="Pages per chunk (default: 5)")
    parser.add_argument("--output", default="manifest.json", help="Output file path")
    args = parser.parse_args()

    pages = all_text_pages()
    chunks = build_chunks(pages, args.chunk_size)

    manifest = {
        "total_pages": len(pages),
        "chunk_size": args.chunk_size,
        "total_chunks": len(chunks),
        "sections": {name: {
            "type": sec["type"],
            "page_count": len([p for p in pages if p["section"] == name]),
        } for name, sec in SECTIONS.items()},
        "pages": pages,
        "chunks": chunks,
    }

    with open(args.output, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"Manifest: {len(pages)} pages in {len(chunks)} chunks")
    for name, info in manifest["sections"].items():
        print(f"  {name}: {info['page_count']} pages ({info['type']})")


if __name__ == "__main__":
    main()
