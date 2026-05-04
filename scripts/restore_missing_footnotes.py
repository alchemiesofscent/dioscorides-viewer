#!/usr/bin/env python3
"""
Restore footnote notes omitted from generated chunks using the source XML.

This is intentionally conservative: it only touches <ref type="footnote-ref">
elements that either have no @target or point at a missing ID. The visible marker
number is matched against the corresponding chapter's notes in berendes (1).xml.
"""

import argparse
import html
import json
import os
import re
import xml.etree.ElementTree as ET


def sanitize_id(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
    value = value.strip("-")
    if not value or not re.match(r"[A-Za-z_]", value):
        value = "id-" + value
    return value


def attr_value(tag, name):
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
    return m.group(1) if m else None


def set_attr(tag, name, value):
    if re.search(r'\b%s="' % re.escape(name), tag):
        return re.sub(r'\b%s="[^"]*"' % re.escape(name), '%s="%s"' % (name, value), tag, count=1)
    return tag[:-1] + ' %s="%s">' % (name, value)


def wrap_greek_text(text, in_foreign=False):
    text = text.replace("ϑ", "θ")
    escaped = html.escape(text, quote=False)
    if in_foreign:
        return escaped
    return re.sub(r"([ἀ-῿Α-Ω]+)", r'<foreign xml:lang="grc">\1</foreign>', escaped)


def render_node(node, in_foreign=False):
    tag = node.tag
    node_foreign = in_foreign or (tag == "span" and node.get("type") == "grk")

    parts = []
    if tag == "span" and node.get("type") == "grk":
        parts.append('<foreign xml:lang="grc">')
    elif tag == "i":
        parts.append('<hi rend="italic">')
    elif tag == "b":
        parts.append('<hi rend="bold">')
    elif tag == "sup":
        parts.append('<hi rend="sup">')
    elif tag == "sub":
        parts.append('<hi rend="sub">')

    if node.text:
        parts.append(wrap_greek_text(node.text, node_foreign))
    for child in list(node):
        parts.append(render_node(child, node_foreign))
    if tag == "span" and node.get("type") == "grk":
        parts.append("</foreign>")
    elif tag in {"i", "b", "sup", "sub"}:
        parts.append("</hi>")
    if node.tail:
        parts.append(wrap_greek_text(node.tail, in_foreign))
    return "".join(parts)


def render_children(node):
    parts = []
    if node.text:
        parts.append(wrap_greek_text(node.text))
    for child in list(node):
        parts.append(render_node(child))
    return "".join(parts).strip()


def source_notes_by_chapter(source_xml):
    root = ET.parse(source_xml).getroot()
    notes = {}

    for div in root.iter("div"):
        if div.get("type") != "chapter" or not div.get("n"):
            continue
        li_text = {}
        for li in div.iter("li"):
            li_id = li.get("id")
            if li_id:
                li_text[li_id] = render_children(li)
        chapter_notes = {}
        for note in div.iter("note"):
            n = note.get("n")
            corresp = (note.get("corresp") or "").lstrip("#")
            if n and corresp in li_text:
                chapter_notes[n] = li_text[corresp]
        if chapter_notes:
            notes[div.get("n")] = chapter_notes

    return notes


def render_xml_fragment(fragment):
    wrapper = ET.fromstring("<root>%s</root>" % fragment)
    return render_children(wrapper)


def merge_regex_source_notes(source_xml, notes):
    text = open(source_xml, encoding="utf-8").read()
    chapter_re = re.compile(r'<div type="chapter" n="([^"]+)"[\s\S]*?(?=<div type="chapter" n="|</text>|$)')
    li_re = re.compile(r'<li id="cite_note-(\d+)"><span class="reference-text">([\s\S]*?)</span></li>')

    for m in chapter_re.finditer(text):
        chapter = m.group(1)
        notes.setdefault(chapter, {})
        for n, body in li_re.findall(m.group(0)):
            if n not in notes[chapter]:
                notes[chapter][n] = render_xml_fragment(body)

    return notes


def source_vorrede_notes(source_xml):
    text = open(source_xml, encoding="utf-8").read()
    start = text.find("<h2>Vorrede</h2>")
    if start == -1:
        return {}
    end = text.find('<div type="chapter"', start + 1)
    block = text[start:end if end != -1 else len(text)]
    notes = {}
    for n, body in re.findall(r'<li id="cite_note-(\d+)"><span class="reference-text">([\s\S]*?)</span></li>', block):
        notes[n] = render_xml_fragment(body)
    return notes


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["chunks"]


def chunk_path(chunks_dir, chunk):
    return os.path.join(chunks_dir, chunk["section"], "%s.xml" % chunk["id"])


def current_ids(paths):
    ids = set()
    for path in paths:
        if os.path.exists(path):
            ids.update(re.findall(r'xml:id="([^"]+)"', open(path, encoding="utf-8").read()))
    return ids


def marker_number(ref_text):
    m = re.search(r"(\d+)", re.sub(r"<[^>]+>", "", ref_text))
    return m.group(1) if m else None


def insert_notes(segment, notes_xml):
    if not notes_xml:
        return segment
    insert_at = segment.rfind("</div>")
    if insert_at == -1:
        return segment.rstrip() + "\n" + "\n".join(notes_xml) + "\n"
    return segment[:insert_at].rstrip() + "\n" + "\n".join(notes_xml) + "\n" + segment[insert_at:]


def restore_in_segment(segment, chunk_id, context_key, source_notes, existing_ids, restored_counter):
    needed_notes = []
    restored_by_number = {}

    def repl(m):
        tag = m.group(1)
        body = m.group(2)
        target = attr_value(tag, "target")
        if target and target.startswith("#") and target[1:] in existing_ids:
            return m.group(0)

        n = marker_number(body)
        if not n:
            return m.group(0)
        note_text = source_notes.get(context_key, {}).get(n)
        if not note_text:
            return m.group(0)

        if n not in restored_by_number:
            restored_counter[0] += 1
            xml_id = "fn-%s-restored-%03d-n%s" % (sanitize_id(chunk_id), restored_counter[0], n.zfill(2))
            while xml_id in existing_ids:
                restored_counter[0] += 1
                xml_id = "fn-%s-restored-%03d-n%s" % (sanitize_id(chunk_id), restored_counter[0], n.zfill(2))
            restored_by_number[n] = xml_id
            existing_ids.add(xml_id)
            needed_notes.append('<note type="footnote" n="%s" xml:id="%s">%s</note>' % (n, xml_id, note_text))

        return set_attr(tag, "target", "#%s" % restored_by_number[n]) + body + "</ref>"

    restored = re.sub(r'(<ref\b(?=[^>]*type="footnote-ref")[^>]*>)(.*?)</ref>', repl, segment, flags=re.S)
    return insert_notes(restored, needed_notes), len(needed_notes)


def restore(chunks_dir, manifest_path, source_xml):
    manifest = load_manifest(manifest_path)
    paths = [chunk_path(chunks_dir, chunk) for chunk in manifest]
    existing_ids = current_ids(paths)
    source_notes = merge_regex_source_notes(source_xml, source_notes_by_chapter(source_xml))
    source_notes["front_vorrede"] = source_vorrede_notes(source_xml)

    current_chapter = None
    restored_counter = [0]
    changed_files = 0
    restored_notes = 0

    token_pattern = re.compile(r'<div\b(?=[^>]*subtype="chapter")[^>]*n="([^"]+)"[^>]*>')

    for chunk in manifest:
        path = chunk_path(chunks_dir, chunk)
        if not os.path.exists(path):
            continue
        original = open(path, encoding="utf-8").read()
        matches = list(token_pattern.finditer(original))
        bounds = [0] + [m.start() for m in matches] + [len(original)]
        pieces = []
        last = 0

        for idx in range(len(bounds) - 1):
            start, end = bounds[idx], bounds[idx + 1]
            if start != last:
                pieces.append(original[last:start])

            if idx > 0:
                current_chapter = matches[idx - 1].group(1)

            segment = original[start:end]
            context_key = current_chapter
            if context_key is None and chunk["section_type"] == "front":
                context_key = "front_vorrede"

            segment, count = restore_in_segment(
                segment, chunk["id"], context_key, source_notes, existing_ids, restored_counter
            )
            restored_notes += count
            pieces.append(segment)
            last = end

        pieces.append(original[last:])
        text = "".join(pieces)
        if text != original:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            changed_files += 1

    return changed_files, restored_notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-xml", required=True)
    args = parser.parse_args()

    changed_files, restored_notes = restore(args.chunks_dir, args.manifest, args.source_xml)
    print("Restored %d missing footnotes in %d chunk files" % (restored_notes, changed_files))


if __name__ == "__main__":
    main()
