# Ingesting New Dioscorides Editions

This project should ingest new editions into the same rubric and viewer used by
Berendes. Sprengel is the next target, followed by Wellmann.

## Inputs

For each new edition, stage the supplied material outside canonical output until
it has been checked:

- source XML
- page images or stable remote facsimile URLs
- bibliographic citation and license/source notes
- any existing page map or chapter map

Do not promote raw source XML directly to `output/`. Normalize it into chunks
first, then merge.

## Normalization Rubric

The normalized TEI should match the Berendes conventions where applicable:

- `<pb n="..." facs="..."/>` for every printed page.
- `<lb n="..."/>` for printed lines, resetting per page.
- `<fw type="header" place="top">` and `<fw type="pageNum" place="top-outer">`
  for running headers and page numbers.
- `<div type="textpart" subtype="book|chapter" n="..." xml:id="...">` for book
  and chapter structure.
- `<head>` for formal chapter title only.
- `<ab type="translation">` for edition text.
- `<note type="commentary">` and `<note type="footnote" n="..." xml:id="...">`
  for commentary and printed footnotes.
- `<ref type="footnote-ref" target="#..." xml:id="...">` plus footnote
  `corresp="#..." place="bottom"` where references are known.

## Pipeline

1. Create edition-specific chunks from supplied XML.
2. Normalize page furniture, footnotes, and title/body boundaries.
3. Build an edition manifest with page labels, PDF/scan labels if available,
   local image names if used, and remote facsimile URLs.
4. Merge chunks to `output/<edition>_epidoc.xml`.
5. Validate the merged TEI.
6. Add the edition to `editions.json`.
7. Spot-check in the viewer against page images.

## Current Sprengel State

Sprengel has been imported as a first-pass diplomatic edition in
`editions/sprengel1829/`. Its TEI is not yet normalized into Berendes-style
chunks, but it is registered in the viewer with a generated manifest so its text
can be inspected alongside Berendes while the full normalization is planned.
Images are mapped to Internet Archive item `b23982500_0001`; TEI
`page_images/page-0006.png` corresponds to Archive page `n5` and IIIF image
`b23982500_0001_0006.jp2`.

The current Sprengel generator applies deterministic normalization for the
known first-pass import artifacts: apparatus markers are emitted as
`type="footnote-ref"` / `type="footnote"` pairs, malformed Greek headings that
absorbed a note marker are repaired without leaving paragraph-leading `.]`, and
Greek `seg type="synonyma"` blocks preserve their printed order before the
lemma. This is still a page-first diplomatic normalization, not a full
Berendes-style OCR/chunk rebuild.

## hOCR And Word Alignment

hOCR is a derived layer, not a blocker for first ingest. When added, keep it
edition-specific and generated from page images or IIIF image services. The
target shape should map page, line, and word boxes to TEI page/line positions so
the viewer can later overlay text selections on the facsimile image.

## Sprengel Volume 2 OCR

The local `b23982500_0002_jp2.zip` source should be treated as an ignored
facsimile asset, not committed data. Generate hOCR and plain text into
`ocr/sprengel/b23982500_0002/`:

```bash
python3 scripts/ocr_sprengel_jp2_zip.py \
  --zip b23982500_0002_jp2.zip \
  --output-dir ocr/sprengel/b23982500_0002
```

This runner is intentionally page-first. It keeps raw whole-page hOCR in
`pass1/`, reruns low-confidence regions into `pass2_regions/`, and writes a
refined text layer plus per-page retry metadata into `refined/`. It also writes
`context.json`, a cross-page lexicon and revisit queue built from the refined
text layer after the run. The raw hOCR is the coordinate-bearing evidence layer;
refined text and context suggestions are review aids and should not be promoted
to diplomatic TEI without checking the page image.

The default OCR languages are Latin, Ancient Greek, Arabic, Hebrew, and Syriac:
`lat+grc+ara+heb+syr`. There is no German in Sprengel volume 2 OCR. On Debian or
Ubuntu, install the expected Tesseract data with:

```bash
sudo apt install \
  tesseract-ocr-lat tesseract-ocr-grc \
  tesseract-ocr-ara tesseract-ocr-heb tesseract-ocr-syr \
  tesseract-ocr-script-latn tesseract-ocr-script-grek \
  tesseract-ocr-script-arab tesseract-ocr-script-hebr \
  tesseract-ocr-script-syrc
```

For a small smoke test before a full run:

```bash
python3 scripts/ocr_sprengel_jp2_zip.py --pages 700-702
```

The first strict multilingual pilot on index scans `700-703` produced usable
OCR with `lat+grc+ara+heb+syr`: page confidence was roughly `75-79`, and only
scan `703` required a weak-region revisit. The text preserved recognizable
Arabic, Hebrew, Syriac, Greek, and Latin page-reference evidence, but it should
still be treated as OCR evidence rather than a corrected index.

For the full local run on an 8-core machine, use bounded parallelism and keep
the default language set:

```bash
python3 scripts/ocr_sprengel_jp2_zip.py --workers 4
```

If language packs are not installed yet, a non-final script smoke test can use
`--allow-missing-langs`; do not treat that output as the multilingual baseline.

## Sprengel Commentarius Viewer XML

The Commentarius stream is built from the Gemini OCR merge at
`sprengel_comm/outputs/sprengel_comm_merged.xml`. That merged OCR is derived
from committed page fragments in `sprengel_comm/ocr_fragments/`; ignored source
facsimiles and extracted page images stay outside the public data boundary.

Chapter matching uses `sprengel_comm/sprengel_chapter_table.tsv` as the
authority for chapter ids and Greek/Latin labels. The table links Commentarius
chapter detections back to the corresponding generated Sprengel text XML ids in
`output/sprengel1829_epidoc.xml` where the base-text chapter exists.

Rebuild the viewer-facing Commentarius XML with:

```bash
python3 scripts/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output output/sprengel1829_epidoc.xml
```

The implementation lives at `scripts/sprengel/build_sprengel_comm_epidoc.py`;
the old `scripts/build_sprengel_comm_epidoc.py` entrypoint is a compatibility
wrapper.

Then validate the generated XML:

```bash
xmllint --noout output/sprengel1829_epidoc.xml
```

The current known table gaps are chapters present in the Commentarius heading
stream but absent from `sprengel_chapter_table.tsv`, chiefly skipped or
combined chapter numbers around Book 4 and Book 5. The builder reports these as
unmatched headings during rebuild; they remain encoded with numeric display
labels until the base-text chapter authority is extended.
