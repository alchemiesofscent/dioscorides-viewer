#!/usr/bin/env python3
"""
Normalize generated chunk identifiers before merging final TEI.

The Codex page chunks use many local IDs such as fn-1, and a few book-boundary
chunks also label chapters with the next book number before the next book div
has opened. This script fixes those chunk-level issues deterministically so the
merged XML has unique xml:id values and resolvable footnote refs.
"""

import argparse
import json
import os
import re
from collections import Counter


XML_ID = "xml:id"


def load_manifest(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["chunks"]


def chunk_path(chunks_dir, chunk):
    return os.path.join(chunks_dir, chunk["section"], "%s.xml" % chunk["id"])


def attr_value(tag, name):
    m = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
    return m.group(1) if m else None


def set_attr(tag, name, value):
    if re.search(r'\b%s="' % re.escape(name), tag):
        return re.sub(r'\b%s="[^"]*"' % re.escape(name), '%s="%s"' % (name, value), tag, count=1)
    return tag[:-1] + ' %s="%s">' % (name, value)


def sanitize_id(value):
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", value)
    value = value.strip("-")
    if not value or not re.match(r"[A-Za-z_]", value):
        value = "id-" + value
    return value


def normalize_structural_divs(text, chunk, state):
    section_type = chunk["section_type"]
    section = chunk["section"]
    chunk_id = chunk["id"]
    front_div_count = [0]

    def repl(m):
        tag = m.group(0)
        subtype = attr_value(tag, "subtype")
        n = attr_value(tag, "n")

        if subtype == "book" and n:
            state["current_book"] = n
            return set_attr(tag, XML_ID, "book_%s" % sanitize_id(n))

        if subtype == "chapter" and n:
            cm = re.match(r"(\d+)\.(\d+)$", n)
            if cm:
                book, chapter = cm.groups()
                actual_book = state.get("current_book") or book
                new_n = "%s.%s" % (actual_book, chapter)
                tag = set_attr(tag, "n", new_n)
                tag = set_attr(tag, XML_ID, "ch_%s_%s" % (actual_book, chapter))
            return tag

        if section_type == "front":
            front_div_count[0] += 1
            base = "front_%s" % sanitize_id(section)
            if front_div_count[0] > 1:
                base = "%s_%02d" % (base, front_div_count[0])
            if chunk_id != section:
                base = "%s_%s" % (base, sanitize_id(chunk_id.split("_")[-1]))
            return set_attr(tag, XML_ID, base)

        return tag

    return re.sub(r"<div\b[^>]*>", repl, text)


def split_chapter_segments(text):
    starts = [m.start() for m in re.finditer(r'<div\b(?=[^>]*subtype="chapter")[^>]*>', text)]
    if not starts:
        return [(0, len(text))]
    bounds = [0] + starts + [len(text)]
    segments = []
    for i in range(len(bounds) - 1):
        if bounds[i] != bounds[i + 1]:
            segments.append((bounds[i], bounds[i + 1]))
    return segments


def normalize_footnotes_in_segment(segment, chunk_id, segment_index):
    note_pattern = re.compile(r'<note\b(?=[^>]*type="footnote")[^>]*>')
    notes = list(note_pattern.finditer(segment))
    if not notes:
        return segment

    old_to_new = {}
    replacements = []
    for note_index, m in enumerate(notes, 1):
        tag = m.group(0)
        old_id = attr_value(tag, XML_ID)
        note_n = attr_value(tag, "n")
        if not old_id and note_n:
            old_id = "fn-%s" % note_n
        new_id = "fn-%s-s%03d-n%02d" % (sanitize_id(chunk_id).replace("_", "-"), segment_index, note_index)
        old_to_new.setdefault(old_id, []).append(new_id)
        replacements.append((m.start(), m.end(), set_attr(tag, XML_ID, new_id)))

    rebuilt = []
    last = 0
    for start, end, replacement in replacements:
        rebuilt.append(segment[last:start])
        rebuilt.append(replacement)
        last = end
    rebuilt.append(segment[last:])
    segment = "".join(rebuilt)

    ref_counts = Counter()

    def ref_repl(m):
        old_id = m.group(1)
        candidates = old_to_new.get(old_id)
        if not candidates:
            return m.group(0)
        idx = min(ref_counts[old_id], len(candidates) - 1)
        ref_counts[old_id] += 1
        return 'target="#%s"' % candidates[idx]

    return re.sub(r'target="#([^"]+)"', ref_repl, segment)


def normalize_footnotes(text, chunk_id):
    pieces = []
    last = 0
    for segment_index, (start, end) in enumerate(split_chapter_segments(text), 1):
        pieces.append(text[last:start])
        pieces.append(normalize_footnotes_in_segment(text[start:end], chunk_id, segment_index))
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def normalize_bare_greek_letters(text):
    replacements = {
        "mit einem Τ, Julius aber mit ΟΥ": 'mit einem <foreign xml:lang="grc">Τ</foreign>, Julius aber mit <foreign xml:lang="grc">ΟΥ</foreign>',
        "das Λ (L) in der Handschrift konnte leicht mit dem Α (A)": 'das <foreign xml:lang="grc">Λ</foreign> (L) in der Handschrift konnte leicht mit dem <foreign xml:lang="grc">Α</foreign> (A)',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def collect_ids(paths):
    ids = []
    positions = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r'xml:id="([^"]+)"', text):
            ids.append(m.group(1))
            positions.append((path, m.start(), m.group(1)))
    return ids, positions


def uniquify_remaining_ids(paths):
    ids, positions = collect_ids(paths)
    totals = Counter(ids)
    seen = Counter()
    changes_by_path = {}

    for path, pos, old_id in positions:
        if totals[old_id] == 1:
            continue
        seen[old_id] += 1
        if seen[old_id] == 1:
            continue
        new_id = "%s_%02d" % (old_id, seen[old_id])
        changes_by_path.setdefault(path, []).append((old_id, new_id))

    for path, changes in changes_by_path.items():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for old_id, new_id in changes:
            text = re.sub(r'xml:id="%s"' % re.escape(old_id), 'xml:id="%s"' % new_id, text, count=1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    return sum(len(v) for v in changes_by_path.values())


def normalize(chunks_dir, manifest_path):
    chunks = load_manifest(manifest_path)
    state = {"current_book": None}
    paths = []
    changed_files = 0

    for chunk in chunks:
        path = chunk_path(chunks_dir, chunk)
        if not os.path.exists(path):
            continue
        paths.append(path)
        with open(path, encoding="utf-8") as f:
            original = f.read()
        text = normalize_structural_divs(original, chunk, state)
        text = normalize_footnotes(text, chunk["id"])
        text = normalize_bare_greek_letters(text)
        if text != original:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            changed_files += 1

    remaining_id_changes = uniquify_remaining_ids(paths)
    return changed_files, remaining_id_changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks-dir", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    changed_files, remaining_id_changes = normalize(args.chunks_dir, args.manifest)
    print("Standardized IDs in %d chunk files" % changed_files)
    print("Resolved %d remaining duplicate structural IDs" % remaining_id_changes)


if __name__ == "__main__":
    main()
