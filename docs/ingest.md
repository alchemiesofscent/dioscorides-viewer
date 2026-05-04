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

## hOCR And Word Alignment

hOCR is a derived layer, not a blocker for first ingest. When added, keep it
edition-specific and generated from page images or IIIF image services. The
target shape should map page, line, and word boxes to TEI page/line positions so
the viewer can later overlay text selections on the facsimile image.
