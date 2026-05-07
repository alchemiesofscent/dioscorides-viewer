#!/usr/bin/env python3
"""Build a Berendes heading reconciliation ledger.

This is an audit-only adapter. It treats the merged EpiDoc as the review
surface, links chapter rows back to chunk files when possible, and writes
ledger/summary/decision artifacts for heading reconciliation.
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


TEI_NS = "{http://www.tei-c.org/ns/1.0}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"
XML_ID = XML_NS + "id"
XML_LANG = XML_NS + "lang"

LEDGER_FIELDS = [
    "book",
    "source_order",
    "page_n",
    "facs",
    "line_n",
    "source_chunk_path",
    "source_xml_id",
    "generated_n",
    "generated_xml_id",
    "printed_cap",
    "printed_alternate",
    "greek_title",
    "german_title",
    "source_heading_text",
    "visible_chapter_title",
    "nav_label",
    "extra_head_count",
    "issue_codes",
    "image_url",
]

DECISION_FIELDS = LEDGER_FIELDS + [
    "canonical_n",
    "display_label",
    "source_label_policy",
    "decision_note",
]

CAP_RE = re.compile(r"\bCap\.\s*([0-9]+)(?:\s*\(([^)]+)\))?", re.IGNORECASE)
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
HEADING_COLLAPSE_RE = re.compile(
    r"\b([A-ZÄÖÜ][^.!?]{1,90}\.)\s+"
    r"(?=\[?Einige\b|Auch\b|Der\b|Die\b|Das\b|Den\b|Dem\b|Ein\b|Eine\b|Es\b|"
    r"Man\b|Wir\b|Nimm\b|Jede\b|Von\b|Wird\b|Fast\b|Als\b)"
)
CHUNK_DIV_RE = re.compile(r"<div\b(?=[^>]*\bsubtype=\"chapter\")[^>]*>", re.DOTALL)
ATTR_RE = re.compile(r"\b([A-Za-z_:][\w:.-]*)=\"([^\"]*)\"")


@dataclass
class ChapterRow:
    book: str
    source_order: int
    page_n: str = ""
    facs: str = ""
    line_n: str = ""
    source_chunk_path: str = ""
    source_xml_id: str = ""
    generated_n: str = ""
    generated_xml_id: str = ""
    printed_cap: str = ""
    printed_alternate: str = ""
    greek_title: str = ""
    german_title: str = ""
    source_heading_text: str = ""
    visible_chapter_title: str = ""
    nav_label: str = ""
    extra_head_count: int = 0
    issue_codes: set[str] = field(default_factory=set)
    image_url: str = ""


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def attr(element: ET.Element, name: str) -> str:
    if name == "xml:id":
        return element.get(XML_ID) or element.get("xml:id") or ""
    if name == "xml:lang":
        return element.get(XML_LANG) or element.get("xml:lang") or ""
    return element.get(name) or ""


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def text_content(element: ET.Element) -> str:
    return normalize_text("".join(element.itertext()))


def direct_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in list(element):
        if local_name(child) == name:
            return child
    return None


def child_text_after_xml(head: ET.Element, child: ET.Element) -> str:
    parts: list[str] = []
    collecting = False
    for candidate in list(head):
        if candidate is child:
            collecting = True
            parts = [candidate.tail or ""]
            continue
        if not collecting:
            continue
        if local_name(candidate) != "ref":
            parts.append(text_content(candidate))
        parts.append(candidate.tail or "")
    return normalize_text(" ".join(parts))


def direct_head(div: ET.Element) -> ET.Element | None:
    return direct_child(div, "head")


def direct_heads(div: ET.Element) -> list[ET.Element]:
    return [child for child in list(div) if local_name(child) == "head"]


def all_heads(element: ET.Element) -> list[ET.Element]:
    return [child for child in element.iter() if local_name(child) == "head"]


def first_pb(element: ET.Element) -> ET.Element | None:
    for child in element.iter():
        if local_name(child) == "pb":
            return child
    return None


def first_lb(element: ET.Element) -> ET.Element | None:
    for child in element.iter():
        if local_name(child) == "lb":
            return child
    return None


def first_greek_foreign(head: ET.Element | None) -> str:
    if head is None:
        return ""
    for foreign in head.iter():
        if local_name(foreign) == "foreign" and attr(foreign, "xml:lang") == "grc":
            return text_content(foreign).rstrip(".")
    return ""


def german_title(head: ET.Element | None) -> str:
    if head is None:
        return ""
    foreign = None
    for candidate in head.iter():
        if local_name(candidate) == "foreign" and attr(candidate, "xml:lang") == "grc":
            foreign = candidate
    if foreign is not None:
        after_greek = re.sub(r"^[\s.:-]+", "", child_text_after_xml(head, foreign))
        collapsed = HEADING_COLLAPSE_RE.search(after_greek)
        if collapsed:
            return collapsed.group(1).rstrip(".")
        if after_greek:
            return after_greek.rstrip(".")
    bold_parts = [
        text_content(hi)
        for hi in head.iter()
        if local_name(hi) == "hi" and "bold" in (hi.get("rend") or "").lower().split()
    ]
    if bold_parts:
        return normalize_text(" ".join(bold_parts)).rstrip(".")
    return re.sub(r"^Cap\.\s*\d+(?:\s*\([^)]+\))?\.?\s*", "", text_content(head), flags=re.I).rstrip(".")


def nav_label(head: ET.Element | None) -> str:
    value = german_title(head)
    return value.strip().rstrip(".")


def parse_printed_cap(head_text: str) -> tuple[str, str]:
    match = CAP_RE.search(head_text)
    if not match:
        return "", ""
    return match.group(1), (match.group(2) or "").strip()


def generated_chapter_number(n: str) -> tuple[str, str]:
    if "." not in n:
        return n, ""
    chapter = n.split(".", 1)[1]
    match = re.match(r"([0-9]+)(?:[A-Za-z]+)?(?:\(([^)]+)\))?$", chapter)
    if not match:
        return chapter, ""
    return match.group(1), match.group(2) or ""


def sort_key(n: str) -> tuple[int, int, str]:
    match = re.match(r"^(\d+)\.([0-9]+)", n or "")
    if not match:
        return (10**9, 10**9, n)
    return int(match.group(1)), int(match.group(2)), n


def chunk_sources(chunks_dir: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in sorted(chunks_dir.rglob("*.xml")):
        text = path.read_text(encoding="utf-8")
        for match in CHUNK_DIV_RE.finditer(text):
            attrs = dict(ATTR_RE.findall(match.group(0)))
            for key in (attrs.get("xml:id") or "", attrs.get("n") or ""):
                if key and key not in sources:
                    sources[key] = str(path)
    return sources


def div_line_numbers(xml_path: Path) -> dict[str, int]:
    line_numbers: dict[str, int] = {}
    for number, line in enumerate(xml_path.read_text(encoding="utf-8").splitlines(), start=1):
        if 'subtype="chapter"' not in line:
            continue
        attrs = dict(ATTR_RE.findall(line))
        xml_id = attrs.get("xml:id") or ""
        n = attrs.get("n") or ""
        if xml_id:
            line_numbers.setdefault(xml_id, number)
        if n:
            line_numbers.setdefault(n, number)
    return line_numbers


def leading_pb(element: ET.Element) -> ET.Element | None:
    for child in list(element):
        name = local_name(child)
        if name == "pb":
            return child
        if name not in {"fw", "lb"}:
            return None
    return None


def collect_rows(root: ET.Element, xml_path: Path, chunks_dir: Path) -> list[ChapterRow]:
    source_paths = chunk_sources(chunks_dir)
    line_numbers = div_line_numbers(xml_path)
    duplicate_counts: Counter[str] = Counter()
    rows: list[ChapterRow] = []

    def make_row(element: ET.Element, current_book: str, current_page: str, current_facs: str) -> None:
        generated_n_value = element.get("n") or ""
        generated_id = attr(element, "xml:id")
        duplicate_counts[generated_n_value] += 1
        head = direct_head(element)
        head_text = text_content(head) if head is not None else ""
        printed_cap, printed_alternate = parse_printed_cap(head_text)
        pb = leading_pb(element)
        lb = first_lb(head) if head is not None else first_lb(element)
        page_n = pb.get("n") if pb is not None else current_page
        facs = pb.get("facs") if pb is not None else current_facs
        source_chunk = source_paths.get(generated_id) or source_paths.get(generated_n_value) or ""
        direct_head_count = len(direct_heads(element))
        extra_heads = max(0, len(all_heads(element)) - direct_head_count)

        row = ChapterRow(
            book=current_book or generated_n_value.split(".", 1)[0],
            source_order=len(rows) + 1,
            page_n=page_n,
            facs=facs,
            line_n=lb.get("n") if lb is not None else "",
            source_chunk_path=source_chunk,
            source_xml_id=generated_id if source_chunk else "",
            generated_n=generated_n_value,
            generated_xml_id=generated_id,
            printed_cap=printed_cap,
            printed_alternate=printed_alternate,
            greek_title=first_greek_foreign(head),
            german_title=german_title(head),
            source_heading_text=head_text,
            visible_chapter_title=head_text,
            nav_label=nav_label(head),
            extra_head_count=extra_heads,
            image_url=facs,
        )

        if head is None:
            row.issue_codes.add("MISSING_HEAD")
        if not source_chunk:
            row.issue_codes.add("SOURCE_CHUNK_NOT_FOUND")
        if generated_n_value in line_numbers:
            pass
        if generated_n_value and "." in generated_n_value and row.book:
            generated_book = generated_n_value.split(".", 1)[0]
            if generated_book != row.book:
                row.issue_codes.add("CHAPTER_BOOK_MISMATCH")
        chapter_primary, chapter_alt = generated_chapter_number(generated_n_value)
        if printed_cap and chapter_primary and printed_cap != chapter_primary:
            row.issue_codes.add("PRINTED_CAP_MISMATCH")
        if printed_alternate and chapter_alt and printed_alternate != chapter_alt:
            row.issue_codes.add("PRINTED_ALT_MISMATCH")
        if not row.nav_label:
            row.issue_codes.add("MISSING_NAV_LABEL")
        elif re.search(r"\(\d+\)|\bCap\.", row.nav_label) or GREEK_RE.search(row.nav_label):
            row.issue_codes.add("POLLUTED_NAV_LABEL")
        if HEADING_COLLAPSE_RE.search(head_text):
            row.issue_codes.add("HEADING_COLLAPSE_CANDIDATE")
        if extra_heads:
            row.issue_codes.add("EMBEDDED_HEAD_IN_CHAPTER")
        rows.append(row)

    def walk(element: ET.Element, current_book: str = "", current_page: str = "", current_facs: str = "") -> tuple[str, str]:
        name = local_name(element)
        if name == "pb":
            return element.get("n") or current_page, element.get("facs") or current_facs
        if name == "div":
            subtype = element.get("subtype") or ""
            if subtype == "book":
                current_book = element.get("n") or current_book
            elif subtype == "chapter":
                make_row(element, current_book, current_page, current_facs)
        page = current_page
        facs = current_facs
        for child in list(element):
            page, facs = walk(child, current_book, page, facs)
        return page, facs

    text = root.find(".//" + TEI_NS + "text")
    walk(text if text is not None else root)

    for row in rows:
        if duplicate_counts[row.generated_n] > 1:
            row.issue_codes.add("DUPLICATE_GENERATED_N")

    previous_by_book: dict[str, int] = {}
    seen_primary_by_book: defaultdict[str, Counter[int]] = defaultdict(Counter)
    for row in rows:
        primary, _ = generated_chapter_number(row.generated_n)
        if not primary.isdigit():
            continue
        number = int(primary)
        seen_primary_by_book[row.book][number] += 1
        previous = previous_by_book.get(row.book)
        if previous is not None and number < previous:
            row.issue_codes.add("BACKWARD_NUMBER_JUMP")
        previous_by_book[row.book] = number

    for row in rows:
        primary, _ = generated_chapter_number(row.generated_n)
        if primary.isdigit() and seen_primary_by_book[row.book][int(primary)] > 1:
            row.issue_codes.add("DUPLICATE_PRIMARY_NUMBER")

    return rows


def row_dict(row: ChapterRow) -> dict[str, str]:
    return {
        "book": row.book,
        "source_order": str(row.source_order),
        "page_n": row.page_n,
        "facs": row.facs,
        "line_n": row.line_n,
        "source_chunk_path": row.source_chunk_path,
        "source_xml_id": row.source_xml_id,
        "generated_n": row.generated_n,
        "generated_xml_id": row.generated_xml_id,
        "printed_cap": row.printed_cap,
        "printed_alternate": row.printed_alternate,
        "greek_title": row.greek_title,
        "german_title": row.german_title,
        "source_heading_text": row.source_heading_text,
        "visible_chapter_title": row.visible_chapter_title,
        "nav_label": row.nav_label,
        "extra_head_count": str(row.extra_head_count),
        "issue_codes": ";".join(sorted(row.issue_codes)),
        "image_url": row.image_url,
    }


def decision_note(row: ChapterRow) -> str:
    if "DUPLICATE_GENERATED_N" in row.issue_codes:
        return "Needs duplicate @n adjudication against printed page and chapter sequence before TEI repair."
    if "BACKWARD_NUMBER_JUMP" in row.issue_codes:
        return "Review sequence with adjacent headings and page image before changing canonical numbering."
    if "DUPLICATE_PRIMARY_NUMBER" in row.issue_codes:
        return "Review whether suffix or printed alternate should be retained as display-only evidence."
    if row.issue_codes:
        return "Needs source and image review before repair."
    return ""


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_html(path: Path, rows: list[ChapterRow]) -> None:
    issue_rows = [row for row in rows if row.issue_codes]
    display_rows = issue_rows or rows[:200]
    lines = [
        "<!doctype html>",
        '<meta charset="utf-8">',
        "<title>Berendes Heading Audit</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:24px;line-height:1.4}",
        "table{border-collapse:collapse;width:100%;font-size:13px}",
        "th,td{border:1px solid #ddd;padding:6px;vertical-align:top}",
        "th{background:#f5f5f5;position:sticky;top:0}",
        ".issues{color:#9a3412;font-weight:600}",
        "</style>",
        "<h1>Berendes Heading Audit</h1>",
        f"<p>{len(rows)} chapter rows; {len(issue_rows)} rows with issue codes.</p>",
        "<table>",
        "<thead><tr>",
    ]
    columns = ["generated_n", "page_n", "line_n", "nav_label", "source_heading_text", "source_chunk_path", "issue_codes", "image_url"]
    lines.extend(f"<th>{html.escape(column)}</th>" for column in columns)
    lines.append("</tr></thead><tbody>")
    for row in display_rows:
        data = row_dict(row)
        lines.append("<tr>")
        for column in columns:
            value = data[column]
            cls = ' class="issues"' if column == "issue_codes" and value else ""
            if column == "image_url" and value:
                cell = f'<a href="{html.escape(value)}">image</a>'
            else:
                cell = html.escape(value)
            lines.append(f"<td{cls}>{cell}</td>")
        lines.append("</tr>")
    lines.append("</tbody></table>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary(path: Path, rows: list[ChapterRow], xml_path: Path, chunks_dir: Path) -> None:
    issue_counts = Counter(code for row in rows for code in row.issue_codes)
    by_book = Counter(row.book for row in rows)
    issue_rows = [row for row in rows if row.issue_codes]
    unique_generated = len({row.generated_n for row in rows})

    def severity(row: ChapterRow) -> tuple[int, str]:
        issue_order = {
            "DUPLICATE_GENERATED_N": 0,
            "BACKWARD_NUMBER_JUMP": 1,
            "POLLUTED_NAV_LABEL": 2,
            "DUPLICATE_PRIMARY_NUMBER": 3,
        }
        rank = min((issue_order.get(code, 9) for code in row.issue_codes), default=9)
        return rank, row.generated_n

    lines = [
        "# Berendes Heading Audit Summary",
        "",
        f"- XML: `{xml_path}`",
        f"- Chunk evidence: `{chunks_dir}`",
        f"- Chapter rows: {len(rows)}",
        f"- Unique generated `@n` values: {unique_generated}",
        f"- Rows with issue codes: {len(issue_rows)}",
        "",
        "## Rows By Book",
        "",
    ]
    for book, count in sorted(by_book.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 999):
        lines.append(f"- Book {book}: {count}")
    lines.extend(["", "## Issue Counts", ""])
    if issue_counts:
        for code, count in issue_counts.most_common():
            lines.append(f"- {code}: {count}")
    else:
        lines.append("- No issue codes emitted.")
    lines.extend(["", "## Highest-Risk Rows", ""])
    if issue_rows:
        for row in sorted(issue_rows, key=severity)[:50]:
            lines.append(
                "- {n} page {page}: {issues} -- {title}".format(
                    n=row.generated_n,
                    page=row.page_n or "?",
                    issues=";".join(sorted(row.issue_codes)),
                    title=row.nav_label or row.source_heading_text,
                )
            )
    else:
        lines.append("- None from this audit pass.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file", nargs="?", default="output/berendes1902_epidoc.xml")
    parser.add_argument("--chunks-dir", default="chunks")
    parser.add_argument("--outdir", default="output/berendes_heading_audit")
    args = parser.parse_args()

    xml_path = Path(args.xml_file)
    chunks_dir = Path(args.chunks_dir)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    root = ET.parse(xml_path).getroot()
    rows = collect_rows(root, xml_path, chunks_dir)
    dict_rows = [row_dict(row) for row in rows]
    decision_rows = [
        {
            **row_dict(row),
            "canonical_n": "",
            "display_label": "",
            "source_label_policy": "",
            "decision_note": decision_note(row),
        }
        for row in rows
    ]

    write_csv(outdir / "heading_ledger.csv", LEDGER_FIELDS, dict_rows)
    write_csv(outdir / "heading_decisions.csv", DECISION_FIELDS, decision_rows)
    write_html(outdir / "heading_ledger.html", rows)
    write_summary(outdir / "heading_summary.md", rows, xml_path, chunks_dir)

    issue_rows = sum(1 for row in rows if row.issue_codes)
    print("Wrote %d rows to %s" % (len(rows), outdir / "heading_ledger.csv"))
    print("Rows with issue codes: %d" % issue_rows)
    for code, count in Counter(code for row in rows for code in row.issue_codes).most_common():
        print("  %s: %d" % (code, count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
