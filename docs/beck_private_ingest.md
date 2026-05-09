# Beck Private Ingest

This repo treats `beck.xml` as private OCR/XML source evidence. The generated TEI and manifest are rebuildable local review artifacts, and Beck is not registered in the public `editions.json` by default.

Generate the private TEI and manifest:

```bash
python3 scripts/build_beck_epidoc.py \
  --source beck.xml \
  --output output/beck2020_epidoc.xml \
  --manifest editions/beck2020/manifest.json
```

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

For local viewer review, use `editions/beck2020/private_registry.json` as the Beck registry source instead of adding Beck to the public `editions.json`. Do not promote the Beck entry to `editions.json` until a publication-safe policy exists.
