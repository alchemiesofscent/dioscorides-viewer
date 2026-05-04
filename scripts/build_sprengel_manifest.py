#!/usr/bin/env python3
"""Build a lightweight viewer manifest from the imported Sprengel TEI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def section_label(stack: list[ET.Element]) -> str:
    for element in reversed(stack):
        if local_name(element.tag) != "div":
            continue
        subtype = element.get("subtype") or element.get("type") or ""
        n = element.get("n") or ""
        if subtype == "chapter" and n:
            return f"chapter {n}"
        if subtype == "book" and n:
            return f"book {n}"
        if subtype:
            return subtype
    return "front"


def image_name(facs: str, fallback_index: int) -> str:
    if facs:
        return Path(facs).name
    return f"page-{fallback_index:04d}.png"


def build_manifest(tei_path: Path) -> dict:
    pages = []
    seen_facs = set()
    stack: list[ET.Element] = []

    for event, element in ET.iterparse(tei_path, events=("start", "end")):
        name = local_name(element.tag)
        if event == "start":
            if name in {"front", "body", "div", "titlePage"}:
                stack.append(element)
            if name == "pb":
                facs = element.get("facs") or ""
                if facs and facs in seen_facs:
                    continue
                if facs:
                    seen_facs.add(facs)
                leaf = len(pages) + 1
                page_n = element.get("n") or ""
                pages.append(
                    {
                        "pdf_page": leaf,
                        "book_page": "" if page_n == "None" else page_n,
                        "section": section_label(stack),
                        "tei_facs": facs,
                        "facs": f"editions/sprengel1829/{facs}" if facs else "",
                        "image": image_name(facs, leaf),
                        "xml_id": element.get(XML_ID) or "",
                    }
                )
        elif event == "end" and name in {"front", "body", "div", "titlePage"}:
            if stack and stack[-1] is element:
                stack.pop()
            else:
                stack = [item for item in stack if item is not element]
            element.clear()

    return {
        "total_pages": len(pages),
        "source": "Sprengel 1829/1830 diplomatic TEI import",
        "source_url": "https://wellcomecollection.org/works/ncazpf6u",
        "image_root": "editions/sprengel1829/page_images/",
        "pages": pages,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tei", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    manifest = build_manifest(args.tei)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
