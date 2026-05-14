# Beck Private Ingest

This repo treats `beck.xml` as private OCR/XML source evidence. The generated TEI and manifest are rebuildable local review artifacts, and Beck is not registered in the public `editions.json` by default.

Generate the private TEI and manifest:

```bash
python3 scripts/ocr_beck_pages.py \
  --pages 14,15,16,30,33,45,133 \
  --source beck.xml \
  --images editions/beck2020/page_images \
  --outdir output/beck_text_cleaning/pilot
```

This writes ignored hOCR/TSV/text evidence under `ocr/beck2020/` and text
cleanup sidecars under `output/beck_text_cleaning/`. The builder consumes
`line_roles.csv` and `token_corrections.csv` automatically when they are
present, so `beck.xml` remains unchanged.

```bash
python3 scripts/build_beck_epidoc.py \
  --source beck.xml \
  --output output/beck2020_epidoc.xml \
  --manifest editions/beck2020/manifest.json
```

Run the text clarity gate after each OCR cleanup rebuild:

```bash
python3 scripts/qc_beck_text_clarity.py \
  --source beck.xml \
  --tei output/beck2020_epidoc.xml \
  --audit output/beck_text_cleaning
```

The clarity QC counts non-furniture body tokens, checks unresolved suspect
tokens against the 99.9% threshold, verifies that accepted page furniture is
not rendered as body text, and spot-checks the high-confidence mixed Greek
correction on page 30.

Run the footnote completion QC after each rebuild:

```bash
python3 scripts/qc_beck_footnotes.py \
  --source beck.xml \
  --tei output/beck2020_epidoc.xml \
  --audit output/beck_footnote_audit
```

The QC requires every source note to be either linked in the TEI or represented
in `output/beck_footnote_audit/review_queue.csv` with page-local evidence. It
does not force ambiguous anchors.

If unresolved pages need targeted OCR evidence, run:

```bash
python3 scripts/ocr_beck_footnote_anchors.py \
  --source beck.xml \
  --images editions/beck2020/page_images \
  --audit output/beck_footnote_audit
```

This writes `output/beck_footnote_audit/ocr_candidates.csv`; the builder reads
that sidecar automatically on the next rebuild.

Extract local page images only when the private Beck PDF is available:

```bash
python3 scripts/extract_beck_images.py /path/to/beck.pdf
```

The extractor writes ignored files under `editions/beck2020/page_images/` as `beck-1.jpg` through `beck-710.jpg`. If the PDF path is wrong, it stops with a filename error.

For local viewer review, serve the repository root and open the normal viewer URL:

```bash
python3 -m http.server 8000
```

```text
http://localhost:8000/viewer/
```

On localhost, the viewer automatically appends
`editions/beck2020/private_registry.json` to the public edition registry when
the private registry is present. Beck will appear in the edition dropdown with
Berendes and Sprengel, but Berendes remains the default. Do not promote the Beck
entry to `editions.json` until a publication-safe policy exists.

## Fresh PDF-Based Beck Stream

The fresh stream ignores `beck.xml` and the older generated Beck output as
generation baselines. It renders `beck.pdf` at 300 dpi, runs Tesseract
`eng+lat+grc`, preserves hOCR coordinates, writes a page-first draft TEI, and
generates a separate private viewer manifest.

Run the representative pilot gate:

```bash
python3 scripts/ocr_beck_fresh_pilot.py \
  --pdf beck.pdf \
  --pages 14,15,16,30,33,45,58,59,133
```

This writes raw evidence under `ocr/beck2020_fresh/`, the local draft TEI at
`output/beck2020_fresh_epidoc.xml`, and the viewer manifest at
`editions/beck2020_fresh/manifest.json`.

After the pilot passes, run the full PDF:

```bash
python3 scripts/ocr_beck_fresh_pilot.py \
  --pdf beck.pdf \
  --all-pages
```

Validate the fresh TEI/manifest pair:

```bash
python3 scripts/validate_beck_fresh.py \
  output/beck2020_fresh_epidoc.xml \
  --manifest editions/beck2020_fresh/manifest.json \
  --expected-pdf-pages 711
```

Generate the footnote ambiguity queue from the fresh QA, hOCR, TEI, and
manifest:

```bash
python3 scripts/build_beck_fresh_footnote_review.py
```

This writes:

- `ocr/beck2020_fresh/review/footnote_review_queue.json`
- `ocr/beck2020_fresh/review/accepted_footnote_links.csv`
- `ocr/beck2020_fresh/review/accepted_footnote_transcriptions.csv`
- `ocr/beck2020_fresh/review/accepted_footnote_blocks.csv`
- `ocr/beck2020_fresh/review/rejected_footnote_candidates.csv`

The accepted link, block, and transcription CSVs are the only sources for
reviewed overrides. The fresh builder reads them automatically, applies approved
links and corrected note text before heuristics, skips rejected candidates, and
otherwise links only high-confidence marker evidence. Ambiguous pages remain
explicit unresolved rows until a deterministic or model visual pass writes
accepted/rejected sidecar decisions.

Run the Berendes-style autonomous visual pass on unresolved footnotes. This
creates zoom panels from the 300dpi page image, hOCR marker boxes, bottom-note
boxes, and separator rules, attaches those images to `codex exec`, and writes
structured proposals. High-confidence proposals can be applied directly to the
accepted/rejected sidecars:

```bash
python3 scripts/run_beck_fresh_footnote_visual_pass.py \
  --pages 20 \
  --run-codex \
  --apply-high-confidence
```

For a dry preparation pass, omit `--run-codex`; prompts and image panels are
written under `ocr/beck2020_fresh/review/visual_pass/`.

The browser zoom surface is diagnostic only. It is useful for inspecting the
same evidence files, but the intended ambiguity workflow is the autonomous
visual pass above:

```bash
python3 -m http.server 8000
```

```text
http://localhost:8000/tools/beck-fresh-footnotes/
```

After the visual pass writes sidecar decisions, rebuild and revalidate:

```bash
python3 scripts/ocr_beck_fresh_pilot.py --pdf beck.pdf --all-pages

python3 scripts/build_beck_fresh_footnote_review.py

python3 scripts/validate_beck_fresh.py \
  output/beck2020_fresh_epidoc.xml \
  --manifest editions/beck2020_fresh/manifest.json \
  --expected-pdf-pages 711
```

Prepare Berendes-style model-correction prompts from the fresh OCR evidence:

```bash
python3 scripts/run_beck_fresh_correction.py \
  --pages 14,15,16,30,33,45,58,59,133 \
  --dry-run
```

Remove `--dry-run` only after reviewing the prompts. Correction chunks are kept
under `ocr/beck2020_fresh/correction/chunks/` and can be merged back into the
fresh stream with:

```bash
python3 scripts/merge_beck_fresh_chunks.py \
  --chunks-dir ocr/beck2020_fresh/correction/chunks \
  --manifest editions/beck2020_fresh/manifest.json \
  --output output/beck2020_fresh_epidoc.xml
```

On localhost, the viewer also checks
`editions/beck2020_fresh/private_registry.json`, so the fresh stream appears as
a separate private review edition without changing public `editions.json`.
