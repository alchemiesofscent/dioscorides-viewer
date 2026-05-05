#!/usr/bin/env python3
"""Normalize TEI page furniture and footnote back-links in chunk XML files."""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path


PB_RE = re.compile(r"<pb\b[^>]*/>")
ERRANT_TOP_LB_RE = re.compile(
    r'^(?P<pb><pb\b[^>]*/>)(?P<ws1>\s*)'
    r'<lb\b(?=[^>]*\bn="1")[^>]*/>'
    r'(?P<ws2>\s*)(?=<fw\b(?=[^>]*\bplace="top[^"]*"))',
    re.DOTALL,
)
LB_RE = re.compile(r'<lb\b[^>]*\bn="(\d+)"[^>]*/>')
REF_START_RE = re.compile(r'<ref\b(?=[^>]*\btype="footnote-ref")[^>]*>')
NOTE_START_RE = re.compile(r'<note\b(?=[^>]*\btype="footnote")[^>]*>')
HEAD_TRANSLATION_RE = re.compile(
    r'(?P<head_open><head\b[^>]*>)(?P<head>.*?)(?P<head_close></head>)'
    r'(?P<between>\s*)'
    r'(?P<ab_open><ab\b(?=[^>]*\btype="translation")[^>]*>)',
    re.DOTALL,
)
SPLIT_TITLE_CONTINUATION_RE = re.compile(
    r'(?P<head_open><head\b[^>]*>)(?P<head>.*?)(?P<head_close></head>)'
    r'(?P<between>\s*)'
    r'(?P<ab_open><ab\b(?=[^>]*\btype="translation")[^>]*>)'
    r'(?P<prefix>\s*(?:<lb\b[^>]*/>\s*)*)'
    r'(?P<title_hi><hi\b(?=[^>]*\brend="[^"]*\bbold\b[^"]*")[^>]*>.*?</hi>)',
    re.DOTALL,
)
BODY_START_RE = re.compile(
    r'^\s*(?:'
    r'\[?Einige\b|Auch\b|Der\b|Die\b|Das\b|Den\b|Dem\b|Es\b|'
    r'Ein\b|Eine\b|Man\b|Wir\b|Nimm\b|Jede\b|Von\b|Wird\b|Fast\b|Als\b'
    r')'
)


def attr_value(tag: str, name: str) -> str:
    match = re.search(r'\b%s="([^"]*)"' % re.escape(name), tag)
    return match.group(1) if match else ""


def set_attr(tag: str, name: str, value: str) -> str:
    pattern = re.compile(r'\b%s="[^"]*"' % re.escape(name))
    replacement = '%s="%s"' % (name, value)
    if pattern.search(tag):
        return pattern.sub(replacement, tag, count=1)
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + " " + replacement + "/>"
    return tag[:-1].rstrip() + " " + replacement + ">"


def make_ref_id(target: str, total_for_target: int, occurrence: int) -> str:
    if total_for_target == 1:
        return "ref-" + target
    return "ref-%s-%02d" % (target, occurrence)


def page_n(pb_tag: str) -> str:
    return attr_value(pb_tag, "n") or "?"


def decrement_page_lbs(page_xml: str) -> tuple[str, int]:
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        tag = match.group(0)
        n = int(match.group(1))
        if n <= 1:
            return tag
        changed += 1
        return set_attr(tag, "n", str(n - 1))

    return LB_RE.sub(repl, page_xml), changed


def normalize_page_furniture(text: str) -> tuple[str, int, int, list[str]]:
    matches = list(PB_RE.finditer(text))
    if not matches:
        return text, 0, 0, []

    parts: list[str] = [text[: matches[0].start()]]
    removed_lbs = 0
    decremented_lbs = 0
    pages: list[str] = []

    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        page_xml = text[match.start() : end]
        errant = ERRANT_TOP_LB_RE.match(page_xml)
        if errant:
            removed_lbs += 1
            pages.append(page_n(errant.group("pb")))
            page_xml = (
                errant.group("pb")
                + errant.group("ws1")
                + errant.group("ws2")
                + page_xml[errant.end() :]
            )
            page_xml, line_count = decrement_page_lbs(page_xml)
            decremented_lbs += line_count
        parts.append(page_xml)

    return "".join(parts), removed_lbs, decremented_lbs, pages


def visible_text(xml: str) -> str:
    return re.sub(r"<[^>]+>", "", xml).strip()


def normalized_visible_text(xml: str) -> str:
    return re.sub(r"\s+", " ", visible_text(xml)).strip()


def last_greek_foreign_end(xml: str) -> int:
    matches = list(
        re.finditer(
            r'<foreign\b(?=[^>]*\b(?:xml:)?lang="grc")[^>]*>.*?</foreign>',
            xml,
            re.DOTALL,
        )
    )
    return matches[-1].end() if matches else -1


def short_title_text(title_xml: str) -> str:
    return raw_short_title_text(title_xml).rstrip(".")


def raw_short_title_text(title_xml: str) -> str:
    foreign_end = last_greek_foreign_end(title_xml)
    title_part = title_xml[foreign_end:] if foreign_end != -1 else title_xml
    return normalized_visible_text(title_part)


def likely_translation_start(moved: str, title_xml: str = "") -> bool:
    moved_text = normalized_visible_text(moved)
    title_text = short_title_text(title_xml)
    return bool(
        BODY_START_RE.match(moved_text)
        or (title_text and moved_text.startswith(title_text + " "))
    )


def existing_translation_starts_with(text: str, start: int, moved: str) -> bool:
    moved_text = normalized_visible_text(moved).rstrip("—- ").strip()
    if not moved_text:
        return False
    following_text = normalized_visible_text(text[start : start + 600])
    return following_text.startswith(moved_text)


def split_head_after_plain_title(head: str) -> tuple[str, str] | None:
    """Split Berendes heads after the short German title following the Greek head."""
    foreign_end = last_greek_foreign_end(head)
    if foreign_end == -1:
        return None

    cursor = foreign_end
    while cursor < len(head):
        if head[cursor] == "<":
            end = head.find(">", cursor)
            if end == -1:
                return None
            tag = head[cursor : end + 1]
            if re.match(r"</?(?:lb|ref|hi|foreign|note)\b", tag):
                cursor = end + 1
                continue
            cursor = end + 1
            continue
        if head[cursor].isspace():
            cursor += 1
            continue
        break

    title_start = cursor
    in_tag = False
    cursor = title_start
    while cursor < len(head):
        char = head[cursor]
        if char == "<":
            in_tag = True
        elif char == ">":
            in_tag = False
        elif char == "." and not in_tag:
            if re.search(r"<(?!/?(?:lb|ref)\b)", head[title_start : cursor + 1]):
                return None
            title = head[: cursor + 1].rstrip()
            if not re.search(r"[A-Za-zÄÖÜäöüß]", short_title_text(title)):
                return None
            moved = head[cursor + 1 :].strip()
            if (
                moved
                and not re.search(r"<(?:pb|fw|note)\b", moved)
                and likely_translation_start(moved, title)
            ):
                return title, moved
            return None
        cursor += 1
    return None


def normalize_chapter_head_translation_starts(text: str) -> tuple[str, int]:
    """Move translation starts that were accidentally captured inside chapter heads."""
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        head = match.group("head")
        split = split_head_after_plain_title(head)
        if split:
            title, moved = split
        else:
            split_index = head.rfind("</hi>")
            if split_index == -1:
                return match.group(0)

            split_index += len("</hi>")
            title = head[:split_index].rstrip()
            trailing = head[split_index:]
            moved = trailing.strip()

        if not moved:
            return match.group(0)
        if re.search(r"<(?:pb|fw|note)\b", moved):
            return match.group(0)
        if not likely_translation_start(moved, title):
            return match.group(0)
        if existing_translation_starts_with(text, match.end(), moved):
            return match.group(0)

        changed += 1
        spacer = "" if moved.endswith("-") else " "
        return (
            match.group("head_open")
            + title
            + match.group("head_close")
            + match.group("between")
            + match.group("ab_open")
            + moved
            + spacer
        )

    return HEAD_TRANSLATION_RE.sub(repl, text), changed


def normalize_split_title_continuations(text: str) -> tuple[str, int]:
    """Move leading bold translation text into the chapter head when it completes the title."""
    changed = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        head = match.group("head")
        title_text = raw_short_title_text(head)
        continuation = normalized_visible_text(match.group("title_hi"))
        if not title_text or title_text.endswith((".", "。")):
            return match.group(0)
        if not continuation.endswith((".", "。")):
            return match.group(0)
        if re.search(r"<(?:pb|fw|note)\b", match.group("prefix")):
            return match.group(0)

        changed += 1
        spacer = "" if head.endswith((" ", "\n", "\t")) else " "
        return (
            match.group("head_open")
            + head.rstrip()
            + spacer
            + match.group("prefix")
            + match.group("title_hi")
            + match.group("head_close")
            + match.group("between")
            + match.group("ab_open")
        )

    return SPLIT_TITLE_CONTINUATION_RE.sub(repl, text), changed


def collect_ref_targets(paths: list[Path]) -> tuple[Counter[str], dict[str, list[str]], list[str]]:
    target_counts: Counter[str] = Counter()
    target_ref_ids: dict[str, list[str]] = defaultdict(list)
    missing_targets: list[str] = []

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in REF_START_RE.finditer(text):
            tag = match.group(0)
            target = attr_value(tag, "target").lstrip("#")
            if not target:
                missing_targets.append(str(path))
                continue
            target_counts[target] += 1

    seen: Counter[str] = Counter()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in REF_START_RE.finditer(text):
            tag = match.group(0)
            target = attr_value(tag, "target").lstrip("#")
            if not target:
                continue
            seen[target] += 1
            ref_id = attr_value(tag, "xml:id") or make_ref_id(target, target_counts[target], seen[target])
            target_ref_ids[target].append(ref_id)

    return target_counts, target_ref_ids, missing_targets


def normalize_footnotes(
    text: str,
    target_counts: Counter[str],
    target_ref_ids: dict[str, list[str]],
    ref_seen: Counter[str],
    path: Path,
) -> tuple[str, int, int, list[str], list[str]]:
    ref_ids_added = 0
    notes_updated = 0
    missing_n: list[str] = []
    unreferenced: list[str] = []

    def ref_repl(match: re.Match[str]) -> str:
        nonlocal ref_ids_added
        tag = match.group(0)
        target = attr_value(tag, "target").lstrip("#")
        if not target or attr_value(tag, "xml:id"):
            return tag
        ref_seen[target] += 1
        ref_id = make_ref_id(target, target_counts[target], ref_seen[target])
        ref_ids_added += 1
        return set_attr(tag, "xml:id", ref_id)

    text = REF_START_RE.sub(ref_repl, text)

    def note_repl(match: re.Match[str]) -> str:
        nonlocal notes_updated
        tag = match.group(0)
        note_id = attr_value(tag, "xml:id")
        note_n = attr_value(tag, "n")
        if not note_id or note_id not in target_ref_ids:
            unreferenced.append("%s:%s" % (path, note_id or "missing-xml-id"))
            return tag
        if not note_n:
            missing_n.append("%s:%s" % (path, note_id))
        corresp = " ".join("#" + ref_id for ref_id in target_ref_ids[note_id])
        updated = set_attr(tag, "corresp", corresp)
        updated = set_attr(updated, "place", "bottom")
        if updated != tag:
            notes_updated += 1
        return updated

    text = NOTE_START_RE.sub(note_repl, text)
    return text, ref_ids_added, notes_updated, missing_n, unreferenced


def normalize_chunks(chunks_dir: Path, dry_run: bool = False) -> int:
    paths = sorted(chunks_dir.glob("**/*.xml"))
    target_counts, target_ref_ids, refs_without_targets = collect_ref_targets(paths)
    ref_seen: Counter[str] = Counter()

    changed_files = 0
    total_removed_lbs = 0
    total_decremented_lbs = 0
    total_ref_ids_added = 0
    total_notes_updated = 0
    total_heads_split = 0
    total_title_continuations = 0
    normalized_pages: list[str] = []
    missing_note_n: list[str] = []
    unreferenced_notes: list[str] = []

    for path in paths:
        original = path.read_text(encoding="utf-8")
        updated, removed_lbs, decremented_lbs, pages = normalize_page_furniture(original)
        updated, title_continuations = normalize_split_title_continuations(updated)
        updated, heads_split = normalize_chapter_head_translation_starts(updated)
        updated, ref_ids_added, notes_updated, missing_n, unreferenced = normalize_footnotes(
            updated, target_counts, target_ref_ids, ref_seen, path
        )

        if updated != original:
            changed_files += 1
            if not dry_run:
                path.write_text(updated, encoding="utf-8")

        total_removed_lbs += removed_lbs
        total_decremented_lbs += decremented_lbs
        total_ref_ids_added += ref_ids_added
        total_notes_updated += notes_updated
        total_heads_split += heads_split
        total_title_continuations += title_continuations
        normalized_pages.extend("%s:%s" % (path, page) for page in pages)
        missing_note_n.extend(missing_n)
        unreferenced_notes.extend(unreferenced)

    action = "Would update" if dry_run else "Updated"
    print("%s %d chunk files" % (action, changed_files))
    print("  Removed top-header lb n=1: %d" % total_removed_lbs)
    print("  Decremented page lb values: %d" % total_decremented_lbs)
    print("  Moved split title continuations into chapter heads: %d" % total_title_continuations)
    print("  Moved translation starts out of chapter heads: %d" % total_heads_split)
    print("  Added footnote ref xml:id values: %d" % total_ref_ids_added)
    print("  Added/refreshed targeted footnote note corresp/place: %d" % total_notes_updated)

    if refs_without_targets:
        print("  Refs without target: %d" % len(refs_without_targets))
    if missing_note_n:
        print("  Targeted footnotes missing @n: %d" % len(missing_note_n))
        for item in missing_note_n:
            print("    - " + item)
    if unreferenced_notes:
        print("  Unreferenced footnote notes left unchanged: %d" % len(unreferenced_notes))
        for item in unreferenced_notes:
            print("    - " + item)
    if normalized_pages:
        print("  Normalized printed pages: %s" % ", ".join(normalized_pages))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize TEI chunk page headers, line numbers, and footnote links."
    )
    parser.add_argument("--chunks-dir", default="chunks", help="Chunk directory to update")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    chunks_dir = Path(args.chunks_dir)
    if not chunks_dir.exists():
        raise SystemExit("Missing chunks directory: %s" % chunks_dir)
    return normalize_chunks(chunks_dir, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
