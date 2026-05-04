#!/usr/bin/env python3
"""
Shared page-mapping utilities for the Berendes 1902 TEI pipeline.

PDF structure (594 pages total):
  PDF 1       = Heidelberg library logo
  PDF 2-5     = blanks / half-title
  PDF 6       = title page (scan 0005)
  PDF 7-8     = blank / verso
  PDF 9       = blank
  PDF 10-13   = Vorwort (book pages v–viii)
  PDF 14      = book page 1 (Einleitung)
  PDF 14+N    = book page 1+N
  ...
  PDF 570     = book page 557 (last text page)
  PDF 571-594 = blanks / end matter

Offset: book_page_arabic = pdf_page - 13  (for pdf_page >= 14)

Heidelberg facs URL patterns:
  Roman pages:  https://digi.ub.uni-heidelberg.de/diglitData/image/berendes1902/1/00_ROEM_{N}.jpg
  Arabic pages: https://digi.ub.uni-heidelberg.de/diglitData/image/berendes1902/3/0_{NNN}.jpg
"""

import re

# Constants
PDF_TOTAL_PAGES = 594
BOOK_START_PDF = 14        # PDF page where book page 1 begins
ROMAN_START_PDF = 10       # PDF page where roman-numeral pages begin
ROMAN_END_PDF = 13         # PDF page where roman-numeral pages end
LAST_TEXT_PDF = 570        # PDF page of last text page (book page 557)
FACS_BASE = "https://digi.ub.uni-heidelberg.de/diglitData/image/berendes1902"

ROMAN_MAP = {10: "v", 11: "vi", 12: "vii", 13: "viii"}
ROMAN_INV = {v: k for k, v in ROMAN_MAP.items()}

# Section boundaries (by book page number, arabic)
SECTIONS = {
    "vorwort":       {"type": "front", "pages_roman": ["v", "vi", "vii", "viii"]},
    "einleitung":    {"type": "front", "page_start": 1,   "page_end": 17},
    "maasse":        {"type": "front", "page_start": 18,  "page_end": 18},
    "abkuerzungen":  {"type": "front", "page_start": 19,  "page_end": 19},
    "vorrede":       {"type": "front", "page_start": 20,  "page_end": 22},
    "book1":         {"type": "body",  "page_start": 23,  "page_end": 131},
    "book2":         {"type": "body",  "page_start": 132, "page_end": 231},
    "book3":         {"type": "body",  "page_start": 232, "page_end": 340},
    "book4":         {"type": "body",  "page_start": 341, "page_end": 449},
    "book5":         {"type": "body",  "page_start": 450, "page_end": 557},
}


def pdf_to_book_page(pdf_page: int) -> str | None:
    """Convert PDF page number to book page string. Returns None for non-text pages."""
    if pdf_page in ROMAN_MAP:
        return ROMAN_MAP[pdf_page]
    if BOOK_START_PDF <= pdf_page <= LAST_TEXT_PDF:
        return str(pdf_page - BOOK_START_PDF + 1)
    return None


def book_page_to_pdf(book_page: str) -> int | None:
    """Convert book page string to PDF page number."""
    if book_page in ROMAN_INV:
        return ROMAN_INV[book_page]
    try:
        n = int(book_page)
        pdf = n + BOOK_START_PDF - 1
        if BOOK_START_PDF <= pdf <= LAST_TEXT_PDF:
            return pdf
        return None
    except ValueError:
        return None


def book_page_to_facs(book_page: str) -> str:
    """Generate Heidelberg facs URL for a book page."""
    if book_page in ROMAN_INV:
        n = ROMAN_INV[book_page] - ROMAN_START_PDF + 5  # v=5, vi=6, ...
        return f"{FACS_BASE}/1/00_ROEM_{n}.jpg"
    else:
        n = int(book_page)
        return f"{FACS_BASE}/3/0_{n:03d}.jpg"


def pdf_to_scan_index(pdf_page: int) -> int:
    """PDF page number to Heidelberg 0-based scan index."""
    return pdf_page - 1


def get_section(book_page: str) -> str | None:
    """Return section name for a book page."""
    for name, sec in SECTIONS.items():
        if "pages_roman" in sec and book_page in sec["pages_roman"]:
            return name
        if "page_start" in sec:
            try:
                n = int(book_page)
                if sec["page_start"] <= n <= sec["page_end"]:
                    return name
            except ValueError:
                continue
    return None


def image_filename(pdf_page: int) -> str:
    """Standard image filename for a PDF page."""
    return f"pg_{pdf_page:04d}.jpg"


def all_text_pages() -> list[dict]:
    """Return list of all text pages with their metadata."""
    pages = []
    # Roman pages
    for pdf_p in range(ROMAN_START_PDF, ROMAN_END_PDF + 1):
        bp = pdf_to_book_page(pdf_p)
        pages.append({
            "pdf_page": pdf_p,
            "book_page": bp,
            "section": get_section(bp),
            "facs": book_page_to_facs(bp),
            "image": image_filename(pdf_p),
        })
    # Arabic pages
    for pdf_p in range(BOOK_START_PDF, LAST_TEXT_PDF + 1):
        bp = pdf_to_book_page(pdf_p)
        pages.append({
            "pdf_page": pdf_p,
            "book_page": bp,
            "section": get_section(bp),
            "facs": book_page_to_facs(bp),
            "image": image_filename(pdf_p),
        })
    return pages


if __name__ == "__main__":
    pages = all_text_pages()
    print(f"Total text pages: {len(pages)}")
    print(f"First: {pages[0]}")
    print(f"Last:  {pages[-1]}")

    # Verify against known mappings
    assert pdf_to_book_page(10) == "v"
    assert pdf_to_book_page(40) == "27"
    assert pdf_to_book_page(18) == "5"
    assert book_page_to_pdf("v") == 10
    assert book_page_to_pdf("27") == 40
    print("All assertions passed.")
