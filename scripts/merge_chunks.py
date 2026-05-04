#!/usr/bin/env python3
"""
Phase 5: Merge all chunk XML fragments into a single TEI document.

Usage:
    python3 scripts/merge_chunks.py \
        --chunks-dir chunks/ \
        --manifest manifest.json \
        --header-template prompts/tei_header.xml \
        --output output/berendes1902_epidoc.xml
"""

import argparse
import json
import os
import re


def load_chunk(path):
    """Load a chunk XML file, stripping any XML declarations."""
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    # Remove XML declarations
    text = re.sub(r'<\?xml[^?]*\?>', '', text).strip()
    return text


def move_leading_page_furniture(content):
    """Move leading page furniture inside the following div for EpiDoc validity."""
    match = re.match(
        r'^((?:\s*(?:<pb\b[^>]*/>|<lb\b[^>]*/>|<fw\b[^>]*>(?:(?!</fw>).)*</fw>))+\s*)(<div\b[^>]*>)',
        content,
        re.DOTALL,
    )
    if not match:
        return content
    leading = match.group(1).strip()
    div_open = match.group(2)
    return "%s\n%s\n%s" % (div_open, leading, content[match.end():].lstrip())


def move_page_furniture_before_divs(content):
    """Move page furniture that sits immediately before a div inside that div."""
    page_furniture = r'(?:<pb\b[^>]*/>|<lb\b[^>]*/>|<fw\b[^>]*>(?:(?!</fw>).)*</fw>)'
    pattern = re.compile(r'(?s)((?:\s*%s)+\s*)(<div\b[^>]*>)' % page_furniture)

    def repl(match):
        leading = match.group(1).strip()
        div_open = match.group(2)
        return "%s\n%s\n" % (div_open, leading)

    return pattern.sub(repl, content)


def ensure_chunk_div(content, chunk_id, section_type):
    """Wrap continuation chunks that do not start with their own structural div."""
    if re.match(r'^\s*<div\b', content):
        return content
    # If a chunk closes a structural element before opening one of the same kind,
    # it is continuing markup from the previous chunk. Leave it unwrapped.
    for tag in ("ab", "note", "div"):
        first_close = content.find("</%s>" % tag)
        first_open = re.search(r"<%s\b" % tag, content)
        if first_close != -1 and (first_open is None or first_close < first_open.start()):
            return content
    # Some chunks continue an open ab/note/div from the previous chunk and close
    # it later. Wrapping those would cross element boundaries and break XML.
    if content.count("</ab>") != len(re.findall(r"<ab\b", content)):
        return content
    if content.count("</note>") != len(re.findall(r"<note\b", content)):
        return content
    if content.count("</div>") != len(re.findall(r"<div\b", content)):
        return content
    subtype = "front-continuation" if section_type == "front" else "continuation"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", chunk_id)
    return (
        '<div type="textpart" subtype="%s" n="%s" xml:id="cont_%s">\n'
        "%s\n"
        "</div>"
    ) % (subtype, chunk_id, safe_id, content)


def wrap_leading_continuation(content, chunk_id, section_type):
    """Wrap leading non-div content separately when a chunk later opens divs."""
    if re.match(r'^\s*<div\b', content):
        return content

    match = re.search(r'<div\b', content)
    if not match:
        return content

    first_close = content.find("</div>")
    if first_close != -1 and first_close < match.start():
        return content

    leading = content[:match.start()].strip()
    rest = content[match.start():].lstrip()
    if not leading:
        return content

    subtype = "front-continuation" if section_type == "front" else "continuation"
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", chunk_id)
    return (
        '<div type="textpart" subtype="%s" n="%s" xml:id="cont_%s_leading">\n'
        "%s\n"
        "</div>\n"
        "%s"
    ) % (subtype, chunk_id, safe_id, leading, rest)


def merge(chunks_dir, manifest_path, header_path, output_path):
    with open(manifest_path) as f:
        manifest = json.load(f)
    with open(header_path, "r", encoding="utf-8") as f:
        template = f.read()

    front_chunks = []
    body_chunks = []

    for chunk in manifest["chunks"]:
        chunk_id = chunk["id"]
        section = chunk["section"]
        chunk_path = os.path.join(chunks_dir, section, "%s.xml" % chunk_id)
        content = load_chunk(chunk_path)
        if not content:
            print("WARNING: missing chunk %s" % chunk_id)
            continue
        content = move_leading_page_furniture(content)
        content = wrap_leading_continuation(content, chunk_id, chunk["section_type"])
        content = ensure_chunk_div(content, chunk_id, chunk["section_type"])

        if chunk["section_type"] == "front":
            front_chunks.append(content)
        else:
            body_chunks.append(content)

    # Assemble
    front_xml = "\n".join(front_chunks)
    body_xml = "\n".join(body_chunks)

    # Inject into template
    output = template.replace("<!-- FRONT_MATTER_PLACEHOLDER -->", front_xml)
    output = output.replace("<!-- BODY_PLACEHOLDER -->", body_xml)
    output = move_page_furniture_before_divs(output)

    # Assign xml:ids to any divs missing them
    div_counter = [0]
    def add_id(m):
        div_counter[0] += 1
        tag = m.group(0)
        if 'xml:id=' not in tag:
            return tag[:-1] + ' xml:id="div_%04d">' % div_counter[0]
        return tag
    output = re.sub(r'<div\s[^>]*>', add_id, output)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    print("Merged %d front + %d body chunks into %s" % (
        len(front_chunks), len(body_chunks), output_path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--header-template", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    merge(args.chunks_dir, args.manifest, args.header_template, args.output)


if __name__ == "__main__":
    main()
