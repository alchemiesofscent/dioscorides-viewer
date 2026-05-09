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
