#!/usr/bin/env python3
"""
Phase 1b: Extract images from PDF and rename to standard naming convention.

Usage:
    python3 scripts/rename_pages.py --pdf berendes1902__z3.pdf --output-dir images/raw

Extracts embedded JPEGs via pdfimages, renames to pg_NNNN.jpg (by PDF page number).
Also writes images/page_index.json mapping image filenames to book pages.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

# Allow importing sibling module
sys.path.insert(0, os.path.dirname(__file__))
from page_map import all_text_pages, pdf_to_book_page, image_filename, PDF_TOTAL_PAGES


def extract_and_rename(pdf_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = os.path.join(tmpdir, "pg")
        print(f"Extracting images from {pdf_path} ...")
        subprocess.run(
            ["pdfimages", "-j", pdf_path, prefix],
            check=True,
            capture_output=True,
        )

        # pdfimages names files as pg-NNN.jpg (0-indexed image count, not page count)
        # For this PDF, there's ~1 image per page, but page 1 has 2 images (logo + small icon)
        # We need to map by listing files and matching to pages.

        extracted = sorted(f for f in os.listdir(tmpdir) if f.startswith("pg-"))
        print(f"Extracted {len(extracted)} image files")

        # Strategy: extract page-by-page to get exact mapping
        # pdfimages with -f/-l is more reliable for page mapping
        print("Re-extracting page by page for accurate mapping ...")
        page_images = {}
        for pdf_page in range(1, PDF_TOTAL_PAGES + 1):
            page_prefix = os.path.join(tmpdir, f"p{pdf_page}")
            result = subprocess.run(
                ["pdfimages", "-j", "-f", str(pdf_page), "-l", str(pdf_page),
                 pdf_path, page_prefix],
                capture_output=True,
            )
            # Find the extracted file(s) for this page
            candidates = sorted(
                f for f in os.listdir(tmpdir)
                if f.startswith(f"p{pdf_page}-") and not f.startswith("pg-")
            )
            if candidates:
                # Take the largest file (main page image, not watermarks)
                best = max(candidates,
                           key=lambda f: os.path.getsize(os.path.join(tmpdir, f)))
                src = os.path.join(tmpdir, best)
                dst_name = image_filename(pdf_page)
                dst = os.path.join(output_dir, dst_name)
                # Ensure it's a jpg (some pages may be ppm)
                if best.endswith(".ppm") or best.endswith(".png"):
                    subprocess.run(
                        ["convert", src, dst],
                        check=True, capture_output=True,
                    )
                else:
                    with open(src, "rb") as sf, open(dst, "wb") as df:
                        df.write(sf.read())
                book_page = pdf_to_book_page(pdf_page)
                page_images[dst_name] = {
                    "pdf_page": pdf_page,
                    "book_page": book_page,
                }
                if pdf_page % 50 == 0:
                    print(f"  ... page {pdf_page}/{PDF_TOTAL_PAGES}")

    return page_images


def main():
    parser = argparse.ArgumentParser(description="Extract and rename PDF page images")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--output-dir", required=True, help="Output directory for images")
    args = parser.parse_args()

    page_images = extract_and_rename(args.pdf, args.output_dir)

    # Write index
    index_path = os.path.join(args.output_dir, "page_index.json")
    with open(index_path, "w") as f:
        json.dump(page_images, f, indent=2, ensure_ascii=False)

    text_pages = [v for v in page_images.values() if v["book_page"] is not None]
    print(f"\nDone. {len(page_images)} images extracted, {len(text_pages)} are text pages.")
    print(f"Index written to {index_path}")


if __name__ == "__main__":
    main()
