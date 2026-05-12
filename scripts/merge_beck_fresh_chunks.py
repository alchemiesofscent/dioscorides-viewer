#!/usr/bin/env python3
"""Merge Beck fresh model-correction fragments into a private TEI document."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)


def strip_fences(text: str) -> str:
    text = re.sub(r"<\?xml[^?]*\?>", "", text.strip())
    if "```xml" in text:
        start = text.index("```xml") + len("```xml")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + len("```")
        end = text.index("```", start)
        text = text[start:end].strip()
    return text.replace("ϑ", "θ")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def load_fragment(path: Path) -> list[ET.Element]:
    content = strip_fences(path.read_text(encoding="utf-8"))
    if not content:
        return []
    if re.match(r"^\s*<TEI\b", content):
        root = ET.fromstring(content)
    else:
        wrapper = f'<wrapper xmlns="{TEI}" xmlns:xml="{XML}">{content}</wrapper>'
        root = ET.fromstring(wrapper)

    if local_name(root.tag) == "TEI":
        text = root.find(f".//{NS}text")
        body = text.find(f"{NS}body") if text is not None else None
        return list(body) if body is not None else []
    if local_name(root.tag) == "wrapper":
        return list(root)
    return [root]


def make_header(title: str, manifest_path: Path) -> ET.Element:
    header = ET.Element(NS + "teiHeader")
    file_desc = ET.SubElement(header, NS + "fileDesc")
    title_stmt = ET.SubElement(file_desc, NS + "titleStmt")
    ET.SubElement(title_stmt, NS + "title").text = title
    pub_stmt = ET.SubElement(file_desc, NS + "publicationStmt")
    ET.SubElement(pub_stmt, NS + "p").text = "Private local model-corrected Beck fresh-OCR review stream."
    source_desc = ET.SubElement(file_desc, NS + "sourceDesc")
    ET.SubElement(source_desc, NS + "p").text = "Generated from local Beck PDF page images and fresh OCR evidence."
    encoding_desc = ET.SubElement(header, NS + "encodingDesc")
    ET.SubElement(encoding_desc, NS + "p").text = (
        f"Merged from Beck fresh correction chunks using viewer manifest {manifest_path.as_posix()}."
    )
    return header


def merge(chunks_dir: Path, manifest_path: Path, output_path: Path, title: str, edition_id: str) -> int:
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_paths = sorted(path for path in chunks_dir.glob("*.xml") if not path.name.endswith("_prompt.xml"))
    if not chunk_paths:
        raise FileNotFoundError(f"No XML correction chunks found in {chunks_dir}")

    root = ET.Element(NS + "TEI")
    root.set(XML_ID, edition_id)
    root.append(make_header(title, manifest_path))
    text = ET.SubElement(root, NS + "text")
    body = ET.SubElement(text, NS + "body")

    added = 0
    for path in chunk_paths:
        for element in load_fragment(path):
            body.append(element)
            added += 1

    root.set("source", manifest.get("source", "Beck 2020 fresh OCR"))
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(f"Merged {len(chunk_paths)} chunks / {added} top-level nodes into {output_path}")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks-dir", default="ocr/beck2020_fresh/correction/chunks")
    parser.add_argument("--manifest", default="editions/beck2020_fresh/manifest.json")
    parser.add_argument("--output", default="output/beck2020_fresh_epidoc.xml")
    parser.add_argument("--title", default="Beck 2020 fresh OCR model-corrected TEI")
    parser.add_argument("--edition-id", default="beck2020_fresh")
    args = parser.parse_args()

    try:
        merge(Path(args.chunks_dir), Path(args.manifest), Path(args.output), args.title, args.edition_id)
    except (FileNotFoundError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
