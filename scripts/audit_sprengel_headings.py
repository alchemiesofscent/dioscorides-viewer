#!/usr/bin/env python3
"""Build a line-by-line Sprengel heading audit ledger.

The script treats the diplomatic XML and generated EpiDoc as evidence. It does
not apply repairs; it only extracts, aligns, and classifies heading mismatches.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html import escape
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"

LEDGER_FIELDS = [
    "book",
    "lang",
    "source_order",
    "page_n",
    "facs",
    "line_id",
    "source_div_n",
    "source_xml_id",
    "printed_primary",
    "printed_alternate",
    "heading_label",
    "source_heading_text",
    "generated_n",
    "generated_label",
    "generated_source_label",
    "visible_chapter_title",
    "paired_generated_n",
    "issue_codes",
    "image_url",
]
DECISION_FIELDS = LEDGER_FIELDS + [
    "canonical_n",
    "display_label",
    "source_label_policy",
    "decision_note",
]

GREEK_HEAD_MARKER_RE = re.compile(r"Κε[φπ]\.", re.IGNORECASE)
LATIN_HEAD_MARKER_RE = re.compile(r"\[?\s*Cap\.", re.IGNORECASE)
GREEK_PRIMARY_RE = re.compile(r"Κε[φπ]\.\s*([^\s.\(\[]+)")
LATIN_PRIMARY_RE = re.compile(r"Cap\.\s*([IVXLCDM]+)", re.IGNORECASE)
PAREN_RE = re.compile(r"\(([^)]+)\)")
BRACKET_RE = re.compile(r"\[([^\]]+)\]")
NOTE_LEAK_RE = re.compile(r"\[\d+[a-z]?\]", re.IGNORECASE)
# Match generator-side suppressed markers so the ledger aligns reviewed
# milestones against the title-bearing source rows.
BOOK_3_SUPPRESSED_GREEK_SOURCE_HEADS = {
    "spr-ch-3.38",
    "spr-ch-3.39",
    "spr-ch-3.42",
    "spr-ch-3.48",
}
BOOK_3_SUPPRESSED_LATIN_SOURCE_LABELS = {"De Meliloto."}
BOOK_3_REVIEWED_UNHEADED_GENERATED_N = {f"3.{number}" for number in range(54, 62)}

GREEK_NUMERAL_VALUES = {
    "α": 1,
    "β": 2,
    "γ": 3,
    "δ": 4,
    "ε": 5,
    "ϛ": 6,
    "ς": 6,
    "ζ": 7,
    "η": 8,
    "θ": 9,
    "ι": 10,
    "κ": 20,
    "λ": 30,
    "μ": 40,
    "ν": 50,
    "ξ": 60,
    "ο": 70,
    "π": 80,
    "ϟ": 90,
    "ϙ": 90,
    "ρ": 100,
    "σ": 200,
    "τ": 300,
    "υ": 400,
    "φ": 500,
    "χ": 600,
    "ψ": 700,
    "ω": 800,
    "ϡ": 900,
}


@dataclass
class SourceHeading:
    book: str
    lang: str
    source_order: int
    page_n: str
    facs: str
    line_id: str
    source_div_n: str
    source_xml_id: str
    printed_primary: str
    printed_alternate: str
    heading_label: str
    source_heading_text: str
    is_inline: bool
    page_order: int = 0


@dataclass
class GeneratedHeading:
    book: str
    lang: str
    generated_order: int
    page_n: str
    facs: str
    line_id: str
    generated_n: str
    generated_label: str
    generated_source_label: str
    visible_chapter_title: str
    issues: set[str] = field(default_factory=set)
    page_order: int = 0


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def attr(element: ET.Element, name: str) -> str:
    if name == "xml:id":
        return element.get(XML_ID) or element.get("xml:id") or ""
    if name == "xml:lang":
        return element.get(XML_LANG) or element.get("xml:lang") or ""
    return element.get(name) or ""


def normalized_text(text: str) -> str:
    return " ".join(text.split())


def text_content(element: ET.Element) -> str:
    return normalized_text("".join(element.itertext()))


def marker_index(text: str, lang: str) -> int:
    marker = GREEK_HEAD_MARKER_RE if lang == "grc" else LATIN_HEAD_MARKER_RE
    match = marker.search(text)
    return match.start() if match else -1


def roman_to_int(value: str) -> int | None:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(value.upper().strip()):
        number = values.get(char)
        if number is None:
            return None
        if number < previous:
            total -= number
        else:
            total += number
            previous = number
    return total


def parse_greek_numeral(value: str) -> int | None:
    cleaned = re.sub(r"[^\wϛϟϡ]+", "", value.lower())
    total = 0
    for char in cleaned:
        number = GREEK_NUMERAL_VALUES.get(char)
        if number is None:
            return None
        total += number
    return total or None


def numeric_heading_value(value: str, lang: str) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return parse_greek_numeral(value) if lang == "grc" else roman_to_int(value)


def chapter_from_xml_id(value: str) -> str:
    match = re.search(r"spr-ch-\d+\.([0-9A-Za-z]+)$", value)
    return match.group(1) if match else ""


def chapter_number(value: str) -> int | None:
    match = re.match(r"^\d+\.([0-9]+)$", value or "")
    return int(match.group(1)) if match else None


def parse_heading_parts(text: str, lang: str) -> tuple[str, str, str]:
    primary_match = (GREEK_PRIMARY_RE if lang == "grc" else LATIN_PRIMARY_RE).search(text)
    printed_primary = primary_match.group(1).strip(" .΄ʹ") if primary_match else ""
    alternate = ""
    alt_match = PAREN_RE.search(text[primary_match.end() :] if primary_match else text)
    if alt_match:
        alternate = alt_match.group(1).strip(" .")
    label = ""
    label_match = BRACKET_RE.search(text)
    if label_match:
        label = normalized_text(label_match.group(1))
    elif lang == "la":
        bracketed = re.search(r"\[\s*Cap\.\s+[IVXLCDM]+\.?\s*(?:\([^)]+\)\.?\s*)?([^\]]+)\]", text, re.IGNORECASE)
        if bracketed:
            label = normalized_text(bracketed.group(1).strip(" ."))
    return printed_primary, alternate, label


def suppress_source_heading(
    book: str,
    lang: str,
    page_n: str,
    source_xml_id: str,
    printed_primary: str,
    label: str,
) -> bool:
    if book != "3":
        return False
    if lang == "grc":
        return source_xml_id in BOOK_3_SUPPRESSED_GREEK_SOURCE_HEADS
    return (
        label in BOOK_3_SUPPRESSED_LATIN_SOURCE_LABELS
        or (page_n == "383" and printed_primary == "XLII" and not label)
    )


def line_segments(element: ET.Element) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    current = {"line_id": "", "line_n": "", "text": ""}

    def append_text(value: str | None) -> None:
        if value:
            current["text"] += value

    def flush() -> None:
        if current["text"].strip():
            lines.append(
                {
                    "line_id": current["line_id"],
                    "line_n": current["line_n"],
                    "text": normalized_text(current["text"]),
                }
            )

    def walk(node: ET.Element) -> None:
        nonlocal current
        append_text(node.text)
        for child in list(node):
            if local_name(child.tag) == "lb":
                flush()
                current = {
                    "line_id": attr(child, "xml:id"),
                    "line_n": attr(child, "n"),
                    "text": child.tail or "",
                }
            else:
                walk(child)
                append_text(child.tail)

    walk(element)
    flush()
    return lines


def heading_snippet(lines: list[dict[str, str]], index: int, lang: str) -> str:
    text = lines[index]["text"]
    start = marker_index(text, lang)
    if start >= 0:
        text = text[start:]
    pieces = [text]
    lookahead = index + 1
    while "[" in " ".join(pieces) and "]" not in " ".join(pieces) and lookahead < len(lines) and lookahead <= index + 2:
        pieces.append(lines[lookahead]["text"])
        lookahead += 1
    return normalized_text(" ".join(pieces))


def manifest_image_lookup(manifest_path: Path) -> dict[str, dict[str, str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pages = manifest.get("pages", [])
    lookup: dict[str, dict[str, str]] = {}
    for page in pages:
        facs = page.get("tei_facs") or page.get("facs") or ""
        if facs:
            lookup[facs] = {
                "image_url": page.get("remoteImage") or page.get("facs") or "",
                "facs_url": page.get("facs") or "",
                "book_page": str(page.get("book_page") or ""),
            }
    return lookup


def extract_source_headings(source_path: Path) -> list[SourceHeading]:
    root = ET.parse(source_path).getroot()
    headings: list[SourceHeading] = []
    page_counts: Counter[tuple[str, str, str]] = Counter()

    state = {
        "book": "",
        "lang": "",
        "page_n": "",
        "facs": "",
        "source_div_n": "",
        "source_xml_id": "",
    }

    def add_heading(text: str, line_id: str, is_inline: bool) -> None:
        lang = state["lang"]
        if lang not in {"grc", "la"}:
            return
        if not state["book"]:
            return
        if marker_index(text, lang) < 0:
            return
        printed_primary, printed_alternate, label = parse_heading_parts(text, lang)
        if suppress_source_heading(
            state["book"],
            lang,
            state["page_n"],
            state["source_xml_id"],
            printed_primary,
            label,
        ):
            return
        key = (state["book"], lang, state["facs"])
        page_counts[key] += 1
        headings.append(
            SourceHeading(
                book=state["book"],
                lang=lang,
                source_order=len(headings) + 1,
                page_n=state["page_n"],
                facs=state["facs"],
                line_id=line_id,
                source_div_n=state["source_div_n"],
                source_xml_id=state["source_xml_id"],
                printed_primary=printed_primary,
                printed_alternate=printed_alternate,
                heading_label=label,
                source_heading_text=text,
                is_inline=is_inline,
                page_order=page_counts[key],
            )
        )

    def walk(node: ET.Element) -> None:
        previous = state.copy()
        name = local_name(node.tag)
        node_lang = attr(node, "xml:lang")
        if node_lang in {"grc", "la"}:
            state["lang"] = node_lang
        if name == "div":
            subtype = attr(node, "subtype")
            div_type = attr(node, "type")
            if div_type == "edition":
                state["lang"] = "grc"
            elif div_type == "translation":
                state["lang"] = "la"
            if subtype == "book":
                state["book"] = attr(node, "n")
                state["source_div_n"] = ""
                state["source_xml_id"] = ""
            elif subtype == "chapter":
                state["source_div_n"] = attr(node, "n")
                state["source_xml_id"] = attr(node, "xml:id")
        elif name == "pb":
            state["page_n"] = attr(node, "n")
            state["facs"] = attr(node, "facs")

        if name == "head" and state["lang"] == "grc":
            text = text_content(node)
            if marker_index(text, "grc") >= 0:
                add_heading(text, "", False)
        elif name == "p" and state["lang"] in {"grc", "la"}:
            lines = line_segments(node)
            for index, line in enumerate(lines):
                if marker_index(line["text"], state["lang"]) >= 0:
                    add_heading(heading_snippet(lines, index, state["lang"]), line["line_id"], True)

        for child in list(node):
            walk(child)
        if name == "div" or node_lang in {"grc", "la"}:
            for key in ("book", "lang", "source_div_n", "source_xml_id"):
                state[key] = previous[key]

    walk(root)
    return headings


def flattened_elements(element: ET.Element) -> list[ET.Element]:
    items: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        items.append(node)
        for child in list(node):
            walk(child)

    walk(element)
    return items


def first_following_text(items: list[ET.Element], start: int, tag_name: str, type_value: str = "") -> str:
    for item in items[start + 1 :]:
        if local_name(item.tag) == "milestone" and attr(item, "unit") == "chapter":
            return ""
        if local_name(item.tag) != tag_name:
            continue
        if type_value and attr(item, "type") != type_value:
            continue
        return text_content(item)
    return ""


def first_following_lb(items: list[ET.Element], start: int) -> str:
    for item in items[start + 1 :]:
        if local_name(item.tag) == "lb":
            return attr(item, "xml:id")
        if local_name(item.tag) == "milestone" and attr(item, "unit") == "chapter":
            return ""
    return ""


def extract_generated_headings(output_path: Path) -> list[GeneratedHeading]:
    root = ET.parse(output_path).getroot()
    generated: list[GeneratedHeading] = []
    page_counts: Counter[tuple[str, str, str]] = Counter()

    for page in root.iter():
        if local_name(page.tag) != "div" or attr(page, "subtype") != "diplomatic-page":
            continue
        facs = attr(page, "facs")
        page_n = attr(page, "n")
        for zone in list(page):
            if local_name(zone.tag) != "ab":
                continue
            lang = attr(zone, "xml:lang")
            if lang not in {"grc", "la"}:
                continue
            items = flattened_elements(zone)
            for index, item in enumerate(items):
                if local_name(item.tag) != "milestone" or attr(item, "unit") != "chapter":
                    continue
                generated_n = attr(item, "n")
                book = generated_n.split(".", 1)[0] if "." in generated_n else ""
                key = (book, lang, facs)
                page_counts[key] += 1
                generated.append(
                    GeneratedHeading(
                        book=book,
                        lang=lang,
                        generated_order=len(generated) + 1,
                        page_n=page_n,
                        facs=facs,
                        line_id=first_following_lb(items, index),
                        generated_n=generated_n,
                        generated_label=attr(item, "label"),
                        generated_source_label=attr(item, "sourceLabel"),
                        visible_chapter_title=first_following_text(items, index, "seg", "chapterTitle"),
                        page_order=page_counts[key],
                    )
                )
    return generated


def classify_generated(generated: list[GeneratedHeading]) -> None:
    by_lang_n = Counter((item.book, item.lang, item.generated_n) for item in generated)
    langs_by_n: dict[tuple[str, str], set[str]] = defaultdict(set)
    by_stream: dict[tuple[str, str], list[GeneratedHeading]] = defaultdict(list)
    for item in generated:
        langs_by_n[(item.book, item.generated_n)].add(item.lang)
        by_stream[(item.book, item.lang)].append(item)

    for item in generated:
        if by_lang_n[(item.book, item.lang, item.generated_n)] > 1:
            item.issues.add("DUPLICATE_GENERATED_N")
        langs = langs_by_n[(item.book, item.generated_n)]
        if "grc" not in langs:
            item.issues.add("PAIR_MISSING_GRC")
        if "la" not in langs:
            item.issues.add("PAIR_MISSING_LA")
        if item.visible_chapter_title and normalized_text(item.generated_source_label) != normalized_text(item.visible_chapter_title):
            item.issues.add("SOURCE_VISIBLE_MISMATCH")
        for text in (item.generated_label, item.generated_source_label, item.visible_chapter_title):
            if NOTE_LEAK_RE.search(text):
                item.issues.add("LABEL_HAS_NOTE_LEAK")

    for stream in by_stream.values():
        previous: GeneratedHeading | None = None
        for item in stream:
            current_number = chapter_number(item.generated_n)
            previous_number = chapter_number(previous.generated_n) if previous else None
            if current_number is not None and previous_number is not None and current_number < previous_number:
                item.issues.add("BACKWARD_JUMP")
            previous = item


def source_conflicts(source: SourceHeading) -> bool:
    values: dict[str, int] = {}
    printed = numeric_heading_value(source.printed_primary, source.lang)
    alternate = numeric_heading_value(source.printed_alternate, source.lang)
    div_n = numeric_heading_value(source.source_div_n, "la")
    xml_n = numeric_heading_value(chapter_from_xml_id(source.source_xml_id), "la")
    if printed is not None:
        values["printed_primary"] = printed
    if alternate is not None:
        values["printed_alternate"] = alternate
    if div_n is not None:
        values["source_div_n"] = div_n
    if xml_n is not None:
        values["source_xml_id"] = xml_n
    return len(set(values.values())) > 1


def pair_n(item: GeneratedHeading | None, generated: list[GeneratedHeading]) -> str:
    if item is None or not item.generated_n:
        return ""
    other = "la" if item.lang == "grc" else "grc"
    return item.generated_n if any(
        candidate.book == item.book and candidate.lang == other and candidate.generated_n == item.generated_n
        for candidate in generated
    ) else ""


def build_ledger(
    source_headings: list[SourceHeading],
    generated_headings: list[GeneratedHeading],
    image_lookup: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    classify_generated(generated_headings)
    source_groups: dict[tuple[str, str, str], list[SourceHeading]] = defaultdict(list)
    generated_groups: dict[tuple[str, str, str], list[GeneratedHeading]] = defaultdict(list)
    for source in source_headings:
        source_groups[(source.book, source.lang, source.facs)].append(source)
    for generated in generated_headings:
        generated_groups[(generated.book, generated.lang, generated.facs)].append(generated)

    rows: list[dict[str, str]] = []
    keys = sorted(
        set(source_groups) | set(generated_groups),
        key=lambda key: (int(key[0]) if key[0].isdigit() else 0, key[2], key[1]),
    )
    for key in keys:
        sources = sorted(source_groups.get(key, []), key=lambda item: item.page_order)
        generated = sorted(generated_groups.get(key, []), key=lambda item: item.page_order)
        max_rows = max(len(sources), len(generated))
        for index in range(max_rows):
            source = sources[index] if index < len(sources) else None
            gen = generated[index] if index < len(generated) else None
            facs = (source.facs if source else gen.facs) if gen or source else ""
            issues = set(gen.issues if gen else set())
            if source is not None:
                if source_conflicts(source):
                    issues.add("PRINTED_SOURCE_CONFLICT")
                for text in (source.heading_label, source.source_heading_text):
                    if NOTE_LEAK_RE.search(text):
                        issues.add("LABEL_HAS_NOTE_LEAK")
                if gen is None and source.is_inline:
                    issues.add("INLINE_HEAD_UNMODELED")
                elif gen is None:
                    issues.add("GENERATED_MISSING")
            if source is None and gen is not None:
                issues.add("GENERATED_WITHOUT_SOURCE")
            rows.append(
                {
                    "book": (source.book if source else gen.book) if gen or source else "",
                    "lang": (source.lang if source else gen.lang) if gen or source else "",
                    "source_order": str(source.source_order) if source else "",
                    "page_n": (source.page_n if source else gen.page_n) if gen or source else "",
                    "facs": facs,
                    "line_id": (source.line_id if source and source.line_id else gen.line_id if gen else ""),
                    "source_div_n": source.source_div_n if source else "",
                    "source_xml_id": source.source_xml_id if source else "",
                    "printed_primary": source.printed_primary if source else "",
                    "printed_alternate": source.printed_alternate if source else "",
                    "heading_label": source.heading_label if source else "",
                    "source_heading_text": source.source_heading_text if source else "",
                    "generated_n": gen.generated_n if gen else "",
                    "generated_label": gen.generated_label if gen else "",
                    "generated_source_label": gen.generated_source_label if gen else "",
                    "visible_chapter_title": gen.visible_chapter_title if gen else "",
                    "paired_generated_n": pair_n(gen, generated_headings),
                    "issue_codes": ";".join(sorted(issues)),
                    "image_url": image_lookup.get(facs, {}).get("image_url", ""),
                }
            )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def decision_preserve_keys(row: dict[str, str]) -> list[tuple[str, ...]]:
    source_key = (
        row.get("book", ""),
        row.get("lang", ""),
        row.get("facs", ""),
        row.get("line_id", ""),
        row.get("source_xml_id", ""),
        row.get("source_heading_text", ""),
    )
    generated_key = source_key + (
        row.get("generated_n", ""),
        row.get("generated_source_label", ""),
    )
    return [source_key, generated_key]


def read_existing_decisions(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    preserved: dict[tuple[str, ...], dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if any(row.get(field, "") for field in ("canonical_n", "display_label", "source_label_policy", "decision_note")):
                for key in decision_preserve_keys(row):
                    preserved[key] = row
    return preserved


def write_decisions(path: Path, rows: list[dict[str, str]]) -> None:
    preserved = read_existing_decisions(path)
    decision_rows = []
    for row in rows:
        previous = next((preserved[key] for key in decision_preserve_keys(row) if key in preserved), {})
        if not row["issue_codes"] and not previous:
            continue
        decision = dict(row)
        decision.update(
            {
                "canonical_n": previous.get("canonical_n", ""),
                "display_label": previous.get("display_label", ""),
                "source_label_policy": previous.get("source_label_policy", ""),
                "decision_note": previous.get("decision_note", ""),
            }
        )
        decision_rows.append(decision)
    write_csv(path, decision_rows, DECISION_FIELDS)


def apply_reviewed_classifications(rows: list[dict[str, str]], decisions_path: Path) -> None:
    preserved = read_existing_decisions(decisions_path)
    for row in rows:
        previous = next((preserved[key] for key in decision_preserve_keys(row) if key in preserved), {})
        if (
            row.get("book") == "3"
            and previous.get("canonical_n")
            and previous.get("source_label_policy") == "reviewed_canonical_override"
        ):
            issues = set(filter(None, row.get("issue_codes", "").split(";")))
            if "PRINTED_SOURCE_CONFLICT" in issues:
                issues.remove("PRINTED_SOURCE_CONFLICT")
                issues.add("REVIEWED_ALTERNATE_NUMBER_CONFLICT")
            if (
                row.get("generated_n") in BOOK_3_REVIEWED_UNHEADED_GENERATED_N
                and "GENERATED_WITHOUT_SOURCE" in issues
                and "SOURCE_VISIBLE_MISMATCH" in issues
            ):
                issues.remove("SOURCE_VISIBLE_MISMATCH")
                issues.add("REVIEWED_GENERATED_TITLE_VISIBLE")
            row["issue_codes"] = ";".join(sorted(issues))


def write_html(path: Path, rows: list[dict[str, str]], image_lookup: dict[str, dict[str, str]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["book"], row["facs"])].append(row)
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Sprengel Heading Audit</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:24px;color:#1f2933;background:#fafafa}",
        "h1{font-size:24px;margin:0 0 16px} h2{font-size:18px;margin:28px 0 8px}",
        "table{border-collapse:collapse;width:100%;background:white;margin:0 0 18px}",
        "th,td{border:1px solid #d7dde3;padding:6px 8px;vertical-align:top;font-size:12px}",
        "th{background:#edf2f7;text-align:left;position:sticky;top:0}",
        "tr.flagged{background:#fff6e5} .issues{font-weight:600;color:#9a3412}",
        ".meta{font-size:12px;color:#52616f;margin:0 0 8px}.text{max-width:420px}",
        "a{color:#174ea6}",
        "</style>",
        "</head><body>",
        "<h1>Sprengel Heading Audit</h1>",
        f'<p class="meta">{len(rows)} ledger rows. Flagged rows are shaded.</p>',
    ]
    for (book, facs), group_rows in sorted(
        grouped.items(),
        key=lambda item: (int(item[0][0]) if item[0][0].isdigit() else 0, item[0][1]),
    ):
        info = image_lookup.get(facs, {})
        image_url = info.get("image_url", "")
        facs_url = info.get("facs_url", "")
        links = " ".join(
            [
                f'<a href="{escape(image_url)}" target="_blank" rel="noopener">image</a>' if image_url else "",
                f'<a href="{escape(facs_url)}" target="_blank" rel="noopener">archive</a>' if facs_url else "",
            ]
        ).strip()
        parts.append(f"<h2>Book {escape(book)} · {escape(facs or 'no facs')}</h2>")
        if links:
            parts.append(f'<p class="meta">{links}</p>')
        parts.append("<table>")
        parts.append(
            "<thead><tr><th>Lang</th><th>Page</th><th>Line</th><th>Source</th>"
            "<th>Generated</th><th>Visible title</th><th>Issues</th></tr></thead><tbody>"
        )
        for row in group_rows:
            row_class = ' class="flagged"' if row["issue_codes"] else ""
            source_bits = [
                row["source_div_n"],
                row["source_xml_id"],
                row["printed_primary"],
                row["printed_alternate"],
                row["heading_label"],
                row["source_heading_text"],
            ]
            generated_bits = [
                row["generated_n"],
                row["generated_label"],
                row["generated_source_label"],
                row["paired_generated_n"],
            ]
            parts.append(
                f"<tr{row_class}>"
                f"<td>{escape(row['lang'])}</td>"
                f"<td>{escape(row['page_n'])}</td>"
                f"<td>{escape(row['line_id'])}</td>"
                f"<td class=\"text\">{escape(' | '.join(bit for bit in source_bits if bit))}</td>"
                f"<td class=\"text\">{escape(' | '.join(bit for bit in generated_bits if bit))}</td>"
                f"<td class=\"text\">{escape(row['visible_chapter_title'])}</td>"
                f"<td class=\"issues\">{escape(row['issue_codes'])}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    parts.append("</body></html>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_summary(
    path: Path,
    rows: list[dict[str, str]],
    source_headings: list[SourceHeading],
    generated_headings: list[GeneratedHeading],
) -> None:
    issue_counts: Counter[str] = Counter()
    for row in rows:
        for issue in row["issue_codes"].split(";"):
            if issue:
                issue_counts[issue] += 1

    source_by_lang = Counter(item.lang for item in source_headings)
    generated_by_lang = Counter(item.lang for item in generated_headings)
    lines = [
        "# Sprengel Heading Audit Summary",
        "",
        "## Totals",
        "",
        f"- Source headings: {len(source_headings)}",
        f"- Source Greek headings: {source_by_lang.get('grc', 0)}",
        f"- Source Latin headings: {source_by_lang.get('la', 0)}",
        f"- Generated milestones: {len(generated_headings)}",
        f"- Generated Greek milestones: {generated_by_lang.get('grc', 0)}",
        f"- Generated Latin milestones: {generated_by_lang.get('la', 0)}",
        f"- Ledger rows: {len(rows)}",
        f"- Flagged rows: {sum(1 for row in rows if row['issue_codes'])}",
        "",
        "## Issue Counts",
        "",
    ]
    if issue_counts:
        for issue, count in sorted(issue_counts.items()):
            lines.append(f"- {issue}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## First Failing Ranges", ""])
    if issue_counts:
        for issue in sorted(issue_counts):
            examples = [row for row in rows if issue in row["issue_codes"].split(";")][:12]
            lines.append(f"### {issue}")
            for row in examples:
                ref = ".".join(part for part in [row["book"], row["generated_n"].split(".")[-1] if row["generated_n"] else ""] if part)
                heading = row["source_heading_text"] or row["generated_source_label"]
                lines.append(
                    f"- book={row['book']} lang={row['lang']} page={row['page_n']} "
                    f"line={row['line_id']} ref={ref}: {heading[:120]}"
                )
            lines.append("")
    else:
        lines.append("- No failing ranges detected.")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="editions/sprengel1829/sprengel_diplomatic.xml")
    parser.add_argument("--generated", default="output/sprengel1829_epidoc.xml")
    parser.add_argument("--manifest", default="editions/sprengel1829/manifest.json")
    parser.add_argument("--outdir", default="output/sprengel_heading_audit")
    args = parser.parse_args()

    source_path = Path(args.source)
    generated_path = Path(args.generated)
    manifest_path = Path(args.manifest)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    image_lookup = manifest_image_lookup(manifest_path)
    source_headings = extract_source_headings(source_path)
    generated_headings = extract_generated_headings(generated_path)
    rows = build_ledger(source_headings, generated_headings, image_lookup)
    apply_reviewed_classifications(rows, outdir / "heading_decisions.csv")

    write_csv(outdir / "heading_ledger.csv", rows, LEDGER_FIELDS)
    write_html(outdir / "heading_ledger.html", rows, image_lookup)
    write_summary(outdir / "heading_summary.md", rows, source_headings, generated_headings)
    write_decisions(outdir / "heading_decisions.csv", rows)

    print(f"Wrote {outdir / 'heading_ledger.csv'} ({len(rows)} rows)")
    print(f"Wrote {outdir / 'heading_ledger.html'}")
    print(f"Wrote {outdir / 'heading_summary.md'}")
    print(f"Wrote {outdir / 'heading_decisions.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
