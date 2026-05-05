#!/usr/bin/env python3
"""Audit Berendes TEI headings and viewer-derived chapter navigation."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


TEI_NS = "{http://www.tei-c.org/ns/1.0}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"
BODY_START_RE = re.compile(
    r"\b(\[?Einige|Auch|Der|Die|Das|Den|Dem|Ein|Eine|Es|Man|Wir|Nimm|Jede|Von|Wird|Fast|Als)\b"
)
HEADING_COLLAPSE_RE = re.compile(
    r"\b([A-Z][^.!?]{1,90}\.)\s+"
    r"(?=\[?Einige\b|Auch\b|Der\b|Die\b|Das\b|Den\b|Dem\b|Ein\b|Eine\b|Es\b|"
    r"Man\b|Wir\b|Nimm\b|Jede\b|Von\b|Wird\b|Fast\b|Als\b)"
)
GREEK_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff]")
DEFAULT_EXPECTED = {
    "2.20",
    "2.21",
    "2.22",
    "2.95",
    "2.96",
    "3.118",
    "3.148",
    "3.149",
    "4.5",
    "4.6",
    "4.60",
    "4.129",
    "4.130",
    "4.132",
}


@dataclass
class Chapter:
    n: str
    xml_id: str
    title: str
    nav_title: str
    first_page: str | None = None


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def xml_id(element: ET.Element) -> str:
    return element.get(XML_NS + "id") or element.get("xml:id") or ""


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def text_content(element: ET.Element) -> str:
    return normalize_text("".join(element.itertext()))


def direct_head(div: ET.Element) -> ET.Element | None:
    for child in list(div):
        if local_name(child) == "head":
            return child
    return None


def starts_with_page_break(div: ET.Element) -> bool:
    for child in list(div):
        return local_name(child) == "pb"
    return False


def element_lang(element: ET.Element) -> str:
    return element.get(XML_NS + "lang") or element.get("xml:lang") or element.get("lang") or ""


def visible_text(xml: str) -> str:
    return normalize_text(re.sub(r"<[^>]+>", "", xml))


def text_after_last_greek_foreign(head: ET.Element) -> str:
    head_xml = ET.tostring(head, encoding="unicode")
    greek_foreign = list(
        re.finditer(
            r'<(?:\w+:)?foreign\b(?=[^>]*\bxml:lang="grc")[^>]*>.*?</(?:\w+:)?foreign>',
            head_xml,
            re.DOTALL,
        )
    )
    if not greek_foreign:
        return ""
    return visible_text(head_xml[greek_foreign[-1].end() :])


def short_title_from_head(head: ET.Element) -> str:
    after_greek = text_after_last_greek_foreign(head)
    if after_greek:
        after_greek = re.sub(r"^[\s.:-]+", "", after_greek)
        split = HEADING_COLLAPSE_RE.search(after_greek)
        if split:
            return split.group(1).rstrip(".")
        return after_greek.rstrip(".")

    for hi in head.iter(TEI_NS + "hi"):
        if "bold" in (hi.get("rend") or "").lower().split():
            return text_content(hi).rstrip(".")
    return re.sub(r"^Cap\.\s*\d+(?:\s*\(\d+\))?\.?\s*", "", text_content(head)).rstrip(".")


def chapter_title(div: ET.Element) -> tuple[str, str]:
    head = direct_head(div)
    if head is None:
        return "", ""
    title = text_content(head)
    return title, short_title_from_head(head)


def heading_collapses(chapters: dict[str, Chapter], chapter_heads: dict[str, ET.Element]) -> list[str]:
    findings = []
    for n, head in chapter_heads.items():
        after_greek = text_after_last_greek_foreign(head)
        if after_greek and HEADING_COLLAPSE_RE.search(after_greek):
            findings.append("%s: %s" % (n, chapters[n].title))
    return findings


def polluted_nav_labels(chapters: dict[str, Chapter]) -> list[str]:
    findings = []
    for chapter in chapters.values():
        nav = chapter.nav_title
        if not nav:
            findings.append("%s: missing nav title" % chapter.n)
        elif re.search(r"\(\d+\)", nav) or "Cap." in nav or GREEK_RE.search(nav):
            findings.append("%s: %s" % (chapter.n, nav))
        elif HEADING_COLLAPSE_RE.search(nav):
            findings.append("%s: %s" % (chapter.n, nav))
    return findings


def collect_viewer_navigation(root: ET.Element) -> tuple[dict[str, Chapter], dict[str, ET.Element], set[str]]:
    chapters: dict[str, Chapter] = {}
    chapter_heads: dict[str, ET.Element] = {}
    nav_chapters: set[str] = set()
    current_page: str | None = None

    def register_chapter(chapter_n: str) -> None:
        if not chapter_n or current_page is None:
            return
        nav_chapters.add(chapter_n)
        if chapters[chapter_n].first_page is None:
            chapters[chapter_n].first_page = current_page

    def walk(element: ET.Element, current_book: str = "", current_chapter: str = "") -> None:
        nonlocal current_page
        name = local_name(element)
        if name == "pb":
            current_page = element.get("n") or current_page
            register_chapter(current_chapter)
            return

        if name == "div":
            subtype = element.get("subtype") or ""
            if subtype == "book":
                current_book = element.get("n") or current_book
                current_chapter = ""
            elif subtype == "chapter":
                current_chapter = element.get("n") or ""
                title, nav_title = chapter_title(element)
                chapters[current_chapter] = Chapter(
                    n=current_chapter,
                    xml_id=xml_id(element),
                    title=title,
                    nav_title=nav_title,
                )
                head = direct_head(element)
                if head is not None:
                    chapter_heads[current_chapter] = head
                if not starts_with_page_break(element):
                    register_chapter(current_chapter)
            elif subtype == "continuation":
                current_chapter = current_chapter

        for child in list(element):
            walk(child, current_book, current_chapter)

    text = root.find(".//" + TEI_NS + "text")
    walk(text if text is not None else root)
    return chapters, chapter_heads, nav_chapters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xml_file", nargs="?", default="output/berendes1902_epidoc.xml")
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        help="Chapter n that must be present in viewer-derived navigation; may be repeated.",
    )
    args = parser.parse_args()

    root = ET.parse(Path(args.xml_file)).getroot()
    chapters, chapter_heads, nav_chapters = collect_viewer_navigation(root)
    expected = set(args.expect) if args.expect else DEFAULT_EXPECTED
    missing_nav = sorted(set(chapters) - nav_chapters)
    expected_missing = sorted(expected - nav_chapters)
    collapsed = heading_collapses(chapters, chapter_heads)
    polluted = polluted_nav_labels(chapters)

    print("Chapters in TEI: %d" % len(chapters))
    print("Chapters in viewer-derived navigation: %d" % len(nav_chapters))
    print("Heading-collapse candidates: %d" % len(collapsed))
    print("Polluted nav-label candidates: %d" % len(polluted))
    print("Expected chapters absent from navigation: %d" % len(expected_missing))

    for label, items in (
        ("MISSING_NAV", missing_nav),
        ("EXPECTED_MISSING_NAV", expected_missing),
        ("HEADING_COLLAPSE", collapsed),
        ("POLLUTED_NAV_LABEL", polluted),
    ):
        for item in items:
            print("  %s: %s" % (label, item))

    return 1 if missing_nav or expected_missing or collapsed or polluted else 0


if __name__ == "__main__":
    sys.exit(main())
