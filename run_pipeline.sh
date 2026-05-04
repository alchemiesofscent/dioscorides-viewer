#!/usr/bin/env bash
set -euo pipefail

# Berendes 1902 TEI/EpiDoc Pipeline
# Run from the tei-maker project root.

PDF="berendes1902__z3.pdf"
XML="berendes (1).xml"
SCRIPTS="scripts"
CHUNK_SIZE=5
MODEL="claude-sonnet-4-6"

echo "=== Phase 0: Setup ==="

# Check dependencies
missing=()
for cmd in convert tesseract python3 pdfimages; do
    if ! command -v "$cmd" &>/dev/null; then
        missing+=("$cmd")
    fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: Missing required commands: ${missing[*]}"
    echo "Install with: sudo apt install imagemagick tesseract-ocr tesseract-ocr-deu tesseract-ocr-grc poppler-utils"
    exit 1
fi

mkdir -p images/raw ocr/{raw,footnotes} chunks output prompts

echo "=== Phase 1: Extract images from PDF ==="
if [ ! -f images/raw/page_index.json ]; then
    python3 "$SCRIPTS/rename_pages.py" --pdf "$PDF" --output-dir images/raw
else
    echo "  (skipping — images already extracted)"
fi

mapfile -t TEXT_IMAGE_NAMES < <(
    python3 -c 'import sys; sys.path.insert(0, "scripts"); from page_map import all_text_pages; [print(p["image"]) for p in all_text_pages()]'
)
total=${#TEXT_IMAGE_NAMES[@]}

count_existing_for_bases() {
    local dir="$1"
    local suffix="$2"
    local count=0
    local img_name base
    for img_name in "${TEXT_IMAGE_NAMES[@]}"; do
        base="${img_name%.jpg}"
        if [ -f "${dir}/${base}${suffix}" ]; then
            count=$((count + 1))
        fi
    done
    printf "%s\n" "$count"
}

image_names_for_pdf_pages() {
    local pages_csv="$1"
    python3 - "$pages_csv" <<'PY'
import sys

requested = []
for raw in sys.argv[1].split(","):
    raw = raw.strip()
    if not raw:
        continue
    try:
        requested.append(int(raw))
    except ValueError:
        raise SystemExit(f"Invalid PDF page number: {raw}")

sys.path.insert(0, "scripts")
from page_map import all_text_pages

pages = {p["pdf_page"]: p["image"] for p in all_text_pages()}
missing = [p for p in requested if p not in pages]
if missing:
    raise SystemExit("PDF page(s) are not text pages: " + ", ".join(map(str, missing)))

for pdf_page in requested:
    print(pages[pdf_page])
PY
}

echo "  Text pages selected: $total (skipping PDF scans without book pages)"

# ---------------------------------------------------------------------------
# Phase 2: OCR with on-demand enhancement
#
# Enhanced images are intermediates only needed by Tesseract.
# Instead of materializing ~9 GB of upscaled PNGs, we enhance each page into
# a temp file, run Tesseract, then discard the PNG.  Only ocr/raw/*.txt is
# required for the default pipeline. Footnote OCR is an opt-in rescue path.
# ---------------------------------------------------------------------------

ocr_page() {
    # Usage: ocr_page <raw_jpg> <ocr_out_base> <convert_args...>
    local img="$1" out="$2"; shift 2
    local tmp
    tmp=$(mktemp /tmp/tei_enhance_XXXXXX.png)
    convert "$img" "$@" "$tmp" || { echo "  ERROR: convert failed on $img" >&2; rm -f "$tmp"; return 1; }
    tesseract "$tmp" "$out" -l deu+grc --psm 6 2>/dev/null || \
    tesseract "$tmp" "$out" -l deu --psm 6 2>/dev/null || \
    tesseract "$tmp" "$out" -l eng --psm 6 2>/dev/null || true
    rm -f "$tmp"
}

echo "=== Phase 2a: Full-page OCR ($total pages) ==="
ocr_done=$(count_existing_for_bases ocr/raw .txt)
if [ "$ocr_done" -lt "$total" ]; then
    count=0
    for img_name in "${TEXT_IMAGE_NAMES[@]}"; do
        count=$((count + 1))
        img="images/raw/${img_name}"
        base="${img_name%.jpg}"
        out="ocr/raw/${base}"
        if [ ! -f "${out}.txt" ]; then
            echo "  OCR $count/$total: $base"
            ocr_page "$img" "$out" -resize 200% -sharpen 0x1.0 -normalize
        else
            echo "  OCR $count/$total: $base (cached)"
        fi
    done
    echo "  OCR completed: $count pages"
else
    echo "  (skipping — OCR already done)"
fi

echo "=== Phase 2b: Footnote OCR ==="
if [ "${RUN_FOOTNOTE_OCR:-0}" != "1" ]; then
    echo "  (skipping — set RUN_FOOTNOTE_OCR=1 for rescue OCR; optionally set FOOTNOTE_PDF_PAGES=184,185)"
else
    if [ -n "${FOOTNOTE_PDF_PAGES:-}" ]; then
        mapfile -t FOOTNOTE_IMAGE_NAMES < <(image_names_for_pdf_pages "$FOOTNOTE_PDF_PAGES")
    else
        FOOTNOTE_IMAGE_NAMES=("${TEXT_IMAGE_NAMES[@]}")
    fi
    footnote_total=${#FOOTNOTE_IMAGE_NAMES[@]}
    fn_done=0
    for img_name in "${FOOTNOTE_IMAGE_NAMES[@]}"; do
        base="${img_name%.jpg}"
        if [ -f "ocr/footnotes/${base}_fn.txt" ]; then
            fn_done=$((fn_done + 1))
        fi
    done
    if [ "$fn_done" -lt "$footnote_total" ]; then
        count=0
        for img_name in "${FOOTNOTE_IMAGE_NAMES[@]}"; do
            count=$((count + 1))
            img="images/raw/${img_name}"
            base="${img_name%.jpg}"
            out="ocr/footnotes/${base}_fn"
            if [ ! -f "${out}.txt" ]; then
                echo "  Footnote OCR $count/$footnote_total: ${base}_fn"
                ocr_page "$img" "$out" \
                    -gravity South -crop 100%x25%+0+0 +repage \
                    -resize 300% -sharpen 0x1.5 -normalize
            else
                echo "  Footnote OCR $count/$footnote_total: ${base}_fn (cached)"
            fi
        done
        echo "  Footnote OCR completed: $count pages"
    else
        echo "  (skipping — footnote OCR already done)"
    fi
fi

echo "=== Phase 3a: Build manifest ==="
python3 "$SCRIPTS/build_manifest.py" --chunk-size "$CHUNK_SIZE" --output manifest.json

echo "=== Phase 3b: Extract XML baseline text ==="
python3 "$SCRIPTS/extract_xml_text.py" "$XML" --output ocr/xml_baseline.json

echo "=== Phase 3c: Extract scaffold ==="
python3 "$SCRIPTS/extract_scaffold.py" "$XML" --output scaffold.json

echo "=== Phase 3d: Diff OCR vs XML ==="
python3 "$SCRIPTS/diff_ocr_xml.py" \
    --ocr-dir ocr/raw \
    --xml-baseline ocr/xml_baseline.json \
    --manifest manifest.json \
    --output ocr/alignment_report.json

echo ""
echo "=== Phases 0-3 complete ==="
echo ""
echo "Next steps:"
echo "  1. Review alignment report:  cat ocr/alignment_report.json | python3 -m json.tool | head -30"
echo "  2. Page pilot (dry):         python3 scripts/run_codex.py --manifest manifest.json --scaffold scaffold.json --ocr-dir ocr/raw --xml-baseline ocr/xml_baseline.json --images-dir images/raw --system-prompt prompts/system.md --output-dir chunks --pdf-pages 184 --dry-run"
echo "  3. Page pilot (live):        (same as above without --dry-run)"
echo "  4. Full batch:               python3 scripts/run_codex.py ... --max-parallel 4"
echo "  5. Merge:                    python3 scripts/merge_chunks.py --chunks-dir chunks --manifest manifest.json --header-template prompts/tei_header.xml --output output/berendes1902_epidoc.xml"
echo "  6. Validate:                 python3 scripts/validate_structure.py output/berendes1902_epidoc.xml"
