#!/usr/bin/env python3
"""
Phase 3d: Align Tesseract OCR output with XML baseline, produce triage report.

Usage:
    python3 scripts/diff_ocr_xml.py \
        --ocr-dir ocr/raw \
        --xml-baseline ocr/xml_baseline.json \
        --manifest editions/berendes1902/manifest.json \
        --output ocr/alignment_report.json
"""

import argparse
import difflib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from page_map import pdf_to_book_page, image_filename


def normalize_text(text):
    """Normalize page text before approximate comparison."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def exact_cer(ref, hyp, max_cells):
    """Character Error Rate using Levenshtein distance."""
    if not ref:
        return 0.0 if not hyp else 1.0
    # Simple DP edit distance
    n, m = len(ref), len(hyp)
    cells = n * m
    if cells > max_cells:
        raise ValueError(
            "exact CER would require %d dynamic-programming cells; "
            "increase --max-cells or use the default approximate metric" % cells
        )
    if n == 0:
        return float(m)
    if m == 0:
        return 1.0
    # Use two-row optimization for memory
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if ref[i-1] == hyp[j-1] else 1
            curr[j] = min(curr[j-1] + 1, prev[j] + 1, prev[j-1] + cost)
        prev, curr = curr, prev
    return prev[m] / n


def approx_similarity(ref, hyp):
    """Fast approximate similarity using stdlib SequenceMatcher quick_ratio."""
    ref_norm = normalize_text(ref)
    hyp_norm = normalize_text(hyp)
    if not ref_norm and not hyp_norm:
        return 1.0
    if not ref_norm or not hyp_norm:
        return 0.0
    return difflib.SequenceMatcher(None, ref_norm, hyp_norm).quick_ratio()


def has_greek(text):
    """Check if text contains Greek Unicode characters."""
    return bool(re.search(r'[Ͱ-Ͽἀ-῿]', text))


def diff_pages(ocr_dir, xml_baseline, manifest_path, output_path, exact=False, max_cells=5000000):
    with open(xml_baseline, "r") as f:
        xml_pages = json.load(f)

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    report = {"pages": [], "summary": {}}
    total_score = 0.0
    matched = 0
    missing_ocr = 0
    missing_xml = 0
    greek_pages = []
    pages = manifest["pages"]
    metric_field = "exact_cer" if exact else "approx_cer"
    summary_field = "average_exact_cer" if exact else "average_approx_cer"
    metric_label = "exact CER" if exact else "approx CER"

    for idx, page_info in enumerate(pages, start=1):
        bp = page_info["book_page"]
        pdf_p = page_info["pdf_page"]

        # Read OCR text
        ocr_file = os.path.join(ocr_dir, "pg_%04d.txt" % pdf_p)
        ocr_text = ""
        if os.path.exists(ocr_file):
            with open(ocr_file, "r", encoding="utf-8", errors="replace") as f:
                ocr_text = f.read().strip()
        else:
            missing_ocr += 1

        # Get XML text
        xml_text = xml_pages.get(str(bp), "")
        if not xml_text:
            missing_xml += 1

        page_score = None
        similarity = None
        if xml_text and ocr_text:
            if exact:
                page_score = exact_cer(xml_text, ocr_text, max_cells)
            else:
                similarity = approx_similarity(xml_text, ocr_text)
                page_score = 1.0 - similarity

        # Detect Greek
        has_grk = has_greek(ocr_text) or has_greek(xml_text)
        if has_grk:
            greek_pages.append(bp)

        entry = {
            "book_page": bp,
            "pdf_page": pdf_p,
            "has_ocr": bool(ocr_text),
            "has_xml": bool(xml_text),
            metric_field: round(page_score, 4) if page_score is not None else None,
            "has_greek": has_grk,
            "ocr_len": len(ocr_text),
            "xml_len": len(xml_text),
        }
        if similarity is not None:
            entry["similarity"] = round(similarity, 4)
        report["pages"].append(entry)

        if page_score is not None:
            total_score += page_score
            matched += 1

        if idx % 50 == 0 or idx == len(pages):
            print("  Compared %d/%d pages (%d with OCR+XML)" % (idx, len(pages), matched), flush=True)

    avg_score = total_score / matched if matched else 0
    report["summary"] = {
        "total_pages": len(pages),
        "pages_with_both": matched,
        "missing_ocr": missing_ocr,
        "missing_xml": missing_xml,
        summary_field: round(avg_score, 4),
        "metric": (
            "Levenshtein character error rate"
            if exact
            else "1 - difflib.SequenceMatcher.quick_ratio() on normalized page text"
        ),
        "greek_page_count": len(greek_pages),
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print("Alignment report: %d pages compared" % matched)
    print("  Average %s: %.2f%%" % (metric_label, avg_score * 100))
    print("  Missing OCR: %d, Missing XML: %d" % (missing_ocr, missing_xml))
    print("  Pages with Greek: %d" % len(greek_pages))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-dir", required=True)
    parser.add_argument("--xml-baseline", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="ocr/alignment_report.json")
    parser.add_argument(
        "--exact-cer",
        action="store_true",
        help="Use guarded exact Levenshtein CER instead of the fast approximate metric.",
    )
    parser.add_argument(
        "--max-cells",
        type=int,
        default=5000000,
        help="Maximum dynamic-programming cells allowed per page with --exact-cer.",
    )
    args = parser.parse_args()

    diff_pages(
        args.ocr_dir,
        args.xml_baseline,
        args.manifest,
        args.output,
        exact=args.exact_cer,
        max_cells=args.max_cells,
    )


if __name__ == "__main__":
    main()
