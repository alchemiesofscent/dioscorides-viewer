# Berendes 1902 — Diplomatic TEI/EpiDoc Edition: CLI Production Plan

## Source Material

- **PDF**: `berendes1902__z3.pdf` — 594 pages, 307 MB, embedded 72 DPI JPEGs (1368×2246 px)
- **Existing XML**: `berendes (1).xml` — ~5865 lines, pseudo-TEI (HTML-style tags), all 5 books + front matter. Not EpiDoc-compliant. Not diplomatically transcribed. Useful as **structural scaffold** and **text comparison baseline**.
- **Heidelberg digitization**: facs URLs in existing XML. PDF page N = Heidelberg scan N-1.

## Page Layout (from inspection of sample pages)

The 1902 Enke edition has a consistent two-layer layout per chapter:

1. **Translation text** (Dioscorides via Berendes): chapter number, Greek heading (Περί …), German title in bold, then the German translation. Normal-size Roman type.
2. **Commentary** (Berendes): separated by a horizontal rule. Same or slightly smaller type. Botanical identifications, pharmacological notes, cross-references to Pliny, Theophrastus, Galen.
3. **Footnotes**: superscript numbers in text, notes at page bottom in smallest type. Greek and Latin mixed in.
4. **Running headers**: book/chapter ref on verso, title on recto.
5. **Page numbers**: top outer corner.

## Target Output

Single valid TEI XML file following **EpiDoc** conventions. Key structures:

```xml
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>…</teiHeader>
  <text>
    <front>…</front>
    <body>
      <div type="edition" xml:lang="de">
        <div type="textpart" subtype="book" n="1">
          <div type="textpart" subtype="chapter" n="1">
            <head>…</head>
            <ab type="translation"><lb n="1"/>…<pb n="24" facs="…"/><lb n="1"/>…</ab>
            <note type="commentary"><lb n="1"/>…</note>
            <note type="footnote" n="1">…</note>
          </div>
        </div>
      </div>
    </body>
  </text>
</TEI>
```

- `<lb n="N"/>` on every printed line (resets per page)
- `<pb n="X" facs="URL"/>` on every page break
- `<foreign xml:lang="grc">` for Greek
- `<hi rend="bold|italic|spaced">` for typography
- `<fw type="header">` for running headers
- `<note type="commentary">` vs `<ab type="translation">` for the two textual layers
- `<note type="footnote" n="N">` for footnotes

---

## Pipeline Architecture

### Phase 0: Environment Setup

```bash
# On user's machine (where codex cli is installed)
# Assumes: codex cli, imagemagick, tesseract, python3, xmllint

# Install tesseract language packs if not present
# macOS:  brew install tesseract-lang
# Ubuntu: apt install tesseract-ocr-deu tesseract-ocr-grc
# Or download tessdata_fast manually:
#   curl -Lo /usr/share/tesseract-ocr/4.00/tessdata/deu.traineddata \
#     https://github.com/tesseract-ocr/tessdata_fast/raw/main/deu.traineddata
#   curl -Lo /usr/share/tesseract-ocr/4.00/tessdata/grc.traineddata \
#     https://github.com/tesseract-ocr/tessdata_fast/raw/main/grc.traineddata

pip install lxml

# Project directory structure
mkdir -p tei-maker/{images/{raw,enhanced},ocr/{raw,aligned},chunks,output,scripts,prompts}
```

### Phase 1: Image Extraction & Enhancement

```bash
# 1a. Extract embedded JPEGs from PDF (fast, no re-rendering)
pdfimages -j berendes1902__z3.pdf images/raw/pg
# Produces: images/raw/pg-000.jpg … pg-593.jpg

# 1b. Rename to sequential with zero-padding
cd images/raw
for f in pg-*.jpg; do
  n=$(echo "$f" | sed 's/pg-0*//' | sed 's/.jpg//')
  printf -v padded "%04d" "$n"
  mv "$f" "pg_${padded}.jpg"
done

# 1c. Enhance for OCR: upscale 2x, sharpen, binarize for Tesseract
mkdir -p ../enhanced
for img in pg_*.jpg; do
  convert "$img" \
    -resize 200% \
    -sharpen 0x1.0 \
    -normalize \
    "../enhanced/${img%.jpg}.png"
done

# 1d. Generate footnote crops (bottom 25%, 3x upscale) for later use
mkdir -p ../enhanced/footnotes
for img in pg_*.jpg; do
  convert "$img" \
    -gravity South -crop 100%x25%+0+0 +repage \
    -resize 300% \
    -sharpen 0x1.5 \
    -normalize \
    "../enhanced/footnotes/${img%.jpg}_fn.png"
done
```

### Phase 2: Tesseract OCR Baseline

```bash
# 2a. Run Tesseract on all enhanced images (German primary, Greek secondary)
mkdir -p ocr/raw
for img in images/enhanced/pg_*.png; do
  base=$(basename "$img" .png)
  tesseract "$img" "ocr/raw/${base}" -l deu+grc --psm 6 2>/dev/null
done

# 2b. Also produce hOCR output (preserves bounding boxes — useful for line-break detection)
mkdir -p ocr/hocr
for img in images/enhanced/pg_*.png; do
  base=$(basename "$img" .png)
  tesseract "$img" "ocr/hocr/${base}" -l deu+grc --psm 6 hocr 2>/dev/null
done

# 2c. OCR the footnote crops separately (catches small print better)
mkdir -p ocr/footnotes
for img in images/enhanced/footnotes/pg_*_fn.png; do
  base=$(basename "$img" .png)
  tesseract "$img" "ocr/footnotes/${base}" -l deu+grc --psm 6 2>/dev/null
done
```

### Phase 3: Diff OCR Against Existing XML

This phase produces a quality report and an aligned text file per page.

```bash
# 3a. Extract plain text per page from existing XML
python3 scripts/extract_xml_text.py "berendes (1).xml" > ocr/xml_baseline.json
# Output: {"page_27": "Bärwurz, Bärendill oder Bärenfenchel…", "page_28": "…", …}

# 3b. Extract chapter scaffold from existing XML
python3 scripts/extract_scaffold.py "berendes (1).xml" > scaffold.json
# Output: chapter numbers, tuid values, Greek headings, German titles, page assignments

# 3c. Build page manifest (maps PDF pages → book pages → sections → chunks)
python3 scripts/build_manifest.py > manifest.json
# Defines chunks of 5 pages each, ~120 chunks total

# 3d. Align OCR output with XML baseline, produce diff report
python3 scripts/diff_ocr_xml.py \
  --ocr-dir ocr/raw \
  --xml-baseline ocr/xml_baseline.json \
  --manifest manifest.json \
  --output ocr/alignment_report.json

# The alignment report shows per-page:
#   - character error rate (CER) of Tesseract vs existing XML
#   - specific disagreements (useful for Codex: "these are the contested readings")
#   - pages where XML has no corresponding text (gaps in existing edition)
#   - Greek passages (flagged for special attention)
```

### Phase 4: Codex CLI Batch — Correction & EpiDoc Markup

This is the core production phase. Each Codex call receives:
- The page image(s) via `-i`
- The Tesseract OCR text (noisy but structurally complete)
- The existing XML text for those pages (for comparison)
- The scaffold (expected chapter structure)
- The alignment diff (contested readings to resolve)

The agent's job shifts from **raw transcription** to **arbitration + markup**: read the image, choose the correct reading where OCR and XML disagree, add EpiDoc structure.

```bash
# 4a. Pilot run — 3 chunks to validate prompt quality
# HUMAN GATE: review output of these 3 before proceeding
python3 scripts/run_codex.py \
  --manifest manifest.json \
  --scaffold scaffold.json \
  --ocr-dir ocr/raw \
  --xml-baseline ocr/xml_baseline.json \
  --alignment ocr/alignment_report.json \
  --images-dir images/raw \
  --system-prompt prompts/system.md \
  --output-dir chunks/ \
  --chunk-ids front_001,book1_001,book3_001 \
  --dry-run  # prints assembled prompts without calling codex

# Review the dry-run output, then:
python3 scripts/run_codex.py \
  --manifest manifest.json \
  ... \
  --chunk-ids front_001,book1_001,book3_001

# 4b. Full batch (after pilot approval)
python3 scripts/run_codex.py \
  --manifest manifest.json \
  --scaffold scaffold.json \
  --ocr-dir ocr/raw \
  --xml-baseline ocr/xml_baseline.json \
  --alignment ocr/alignment_report.json \
  --images-dir images/raw \
  --footnote-ocr-dir ocr/footnotes \
  --enhanced-dir images/enhanced \
  --system-prompt prompts/system.md \
  --output-dir chunks/ \
  --max-parallel 4
```

**What `run_codex.py` does per chunk:**

```
For each chunk (5 pages):
  1. Assemble prompt:
     - System prompt (EpiDoc rules)
     - Scaffold slice (expected chapters on these pages)
     - OCR text for pages N..N+4
     - XML baseline text for same pages (if available)
     - Alignment diff (disagreements to resolve)
     - Footnote OCR text (from enhanced crops)

  2. Call codex:
     codex -i images/raw/pg_NNNN.jpg \
           -i images/raw/pg_NNNN+1.jpg \
           ... \
           --model claude-sonnet-4-6 \
           --full-auto \
           "$(cat assembled_prompt.txt)"

  3. Extract XML fragment from codex output
  4. Validate fragment is well-formed XML
  5. Save to chunks/{section}/{chunk_id}.xml
  6. Log: chunk_id, token_usage, duration, any warnings
```

**Codex system prompt** (`prompts/system.md`):

```markdown
You are producing a diplomatic TEI/EpiDoc XML edition. You receive:
- Page images (authoritative source — trust the image over all other inputs)
- Tesseract OCR text (noisy baseline — good structure, bad Greek, occasional char errors)
- Existing XML text (reference — may have transcription errors or non-diplomatic modernizations)
- Alignment diff (where OCR and XML disagree — resolve by reading the image)

## Your task
1. Read each page image carefully
2. Use the OCR text as a starting scaffold
3. Correct errors by consulting the image (the image is always right)
4. Add EpiDoc TEI markup:
   - <lb n="N"/> at every printed line break (restart numbering each page)
   - <pb n="PAGE" facs="URL"/> at page transitions
   - <foreign xml:lang="grc"> around Greek text
   - <hi rend="bold|italic|spaced"> for typography
   - <fw type="header" place="top"> for running headers
   - <ab type="translation"> for Dioscorides translation text
   - <note type="commentary"> for Berendes' commentary (after horizontal rule)
   - <note type="footnote" n="N"> for footnotes
   - <head> for chapter headings
   - <div type="textpart" subtype="chapter" n="BOOK.CHAPTER">
5. Preserve original 1902 orthography exactly (Theil, Uebersetzung, etc.)
6. Output ONLY the XML fragment. No explanations.

## Resolving disagreements
When OCR and XML text differ, read the image. Common OCR errors in this text:
- Greek: almost always wrong in OCR. Transcribe Greek from the image directly.
- ü→ii, ö→6, ä→a in eng-fallback OCR (less common with deu)
- Ligatures: fi, fl, ff sometimes misread
- Footnote superscripts: often garbled
- Long s (ſ): may appear in some passages

## Facs URL pattern
https://digi.ub.uni-heidelberg.de/diglitData/image/berendes1902/3/0_{{PAGE_PADDED}}.jpg
For roman-numeral pages: .../1/00_ROEM_{{N}}.jpg
```

### Phase 5: Merge & Assembly

```bash
# 5a. Merge all chunks into single TEI document
python3 scripts/merge_chunks.py \
  --chunks-dir chunks/ \
  --manifest manifest.json \
  --header-template prompts/tei_header.xml \
  --output output/berendes1902_epidoc.xml

# 5b. Format
xmllint --format output/berendes1902_epidoc.xml > output/berendes1902_epidoc_fmt.xml
```

### Phase 6: Validation

```bash
# 6a. Well-formedness
xmllint --noout output/berendes1902_epidoc.xml

# 6b. EpiDoc schema validation
curl -sO https://epidoc.stoa.org/schema/latest/tei-epidoc.rng
xmllint --relaxng tei-epidoc.rng --noout output/berendes1902_epidoc.xml

# 6c. Structural integrity
python3 scripts/validate_structure.py output/berendes1902_epidoc.xml
# Checks: all 5 books, chapter counts, pb/lb sequencing, footnote refs, Greek wrapping

# 6d. Coverage diff against existing XML
python3 scripts/diff_chapters.py "berendes (1).xml" output/berendes1902_epidoc.xml
# Reports missing/extra chapters

# 6e. Spot-check: 20 random pages, Codex compares image vs XML
python3 scripts/spot_check.py \
  --xml output/berendes1902_epidoc.xml \
  --images-dir images/raw \
  --sample-size 20
```

### Phase 7: Patch & Finalize

```bash
# 7a. Auto-patch from validation report
python3 scripts/patch_from_report.py \
  --report output/validation_report.json \
  --xml output/berendes1902_epidoc.xml \
  --images-dir images/raw

# 7b. Re-validate (repeat Phase 6 until clean)

# HUMAN GATE: review final validation report before declaring done
```

---

## Script Inventory

| Script | Purpose | Autonomous? |
|--------|---------|-------------|
| `rename_pages.py` | Map PDF page indices → book page numbers | Yes |
| `build_manifest.py` | Generate page manifest + chunk definitions | Yes |
| `extract_scaffold.py` | Extract chapter structure from existing XML | Yes |
| `extract_xml_text.py` | Extract plain text per page from existing XML | Yes |
| `diff_ocr_xml.py` | Align Tesseract output with XML, produce diff report | Yes |
| `run_codex.py` | Main production loop: assemble prompts, call `codex -i`, save chunks | Yes (after pilot) |
| `merge_chunks.py` | Assemble chunks into final TEI document | Yes |
| `validate_structure.py` | Structural integrity checks | Yes |
| `diff_chapters.py` | Coverage comparison against existing XML | Yes |
| `spot_check.py` | Random sample visual QA via Codex | Yes |
| `patch_from_report.py` | Auto-fix validation issues | Yes |

## Human Gates (2 total, ~30 min combined)

1. **After Phase 4a pilot** (~15 min): Review 3 sample chunks before full batch.
2. **After Phase 6** (~15 min): Review final validation report.

## Estimates

| Phase | Time | Cost (tokens) |
|-------|------|---------------|
| 0–1: Setup + image extraction | 1–2 hr | 0 |
| 2: Tesseract OCR (594 pages) | 30–60 min | 0 |
| 3: Diff + alignment | 10 min | 0 |
| 4: Codex batch (~120 chunks) | 4–6 hr | ~1.5M tokens |
| 5: Merge | 5 min | 0 |
| 6: Validation | 30 min | ~100K tokens (spot-check) |
| 7: Patching | 1–2 hr | ~200K tokens |
| **Total** | **~8–12 hr** | **~1.8M tokens** |

Token savings vs pure-vision approach: ~30% reduction because Codex is correcting OCR rather than transcribing from scratch. Greek passages and footnotes account for most of the remaining vision-token cost.

## Autonomy Profile

Phases 0→1→2→3 run as a single unattended shell script.
Phase 4a (pilot) requires one human review.
Phases 4b→5→6 run unattended.
Phase 7 requires one human review of the final report.

Total human time: ~30 minutes across ~10 hours of compute.
