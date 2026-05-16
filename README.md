# Dioscorides Viewer

Static TEI/EpiDoc viewer for Dioscorides editions, beginning with Julius
Berendes' 1902 German translation, *Des Pedanios Dioskurides aus Anazarbos
Arzneimittellehre in fünf Büchern*, plus Sprengel review streams for the
1829/1830 Greek/Latin edition and its 1830 Commentarius.

The repository is designed to run on GitHub Pages. The text, page map, and
viewer assets are committed; bulky facsimile images are not. The viewer loads
Berendes page images directly from Heidelberg University Library facsimile URLs
recorded in the TEI and `manifest.json`, and Sprengel images from the Internet
Archive IIIF service.

## Open The Viewer

When published to GitHub Pages:

```text
https://alchemiesofscent.github.io/dioscorides-viewer/
```

For local review from the repository root:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/viewer/
```

On localhost, the viewer also looks for the private Beck registry at
`editions/beck2020/private_registry.json` and the fresh-PDF registry at
`editions/beck2020_fresh/private_registry.json`, then appends those private
review streams to the edition menu when their generated files are present. This
local overlay does not change the public `editions.json` registry used by GitHub
Pages.

The fresh Beck footnote ambiguity workflow is image-first. Generate zoom panels
and model proposals with:

```bash
python3 scripts/run_beck_fresh_footnote_visual_pass.py \
  --run-codex \
  --apply-high-confidence
```

The separate fresh Beck footnote zoom surface is available for diagnostics at:

```text
http://localhost:8000/tools/beck-fresh-footnotes/
```

## Repository Contents

- `viewer/` - dependency-free static browser viewer.
- `tools/` - local review surfaces that are not required by the public viewer.
- `editions.json` - public edition registry consumed by the viewer.
- `chunks/` - normalized Berendes TEI chunk source.
- `manifest.json` - Berendes page/image/chunk manifest.
- `editions/sprengel1829/` - Sprengel base-edition source, sidecars, and
  generated manifest data.
- `sprengel_comm/` - committed Commentarius OCR fragments, merged OCR XML,
  chapter authority table, prompt notes, and workflow metadata.
- `output/` - committed viewer-facing generated XML and committed audit
  reports.
- `scripts/` - normalization, OCR, merge, audit, and validation tools.
- `prompts/` - TEI header and transcription prompt material.
- `docs/` - ingest and workflow documentation.

Large local assets such as PDFs, JP2 zips, extracted page images, `.env`,
`sprengel/`, `ocr/`, `images/raw/`, `images/enhanced/`, and other scratch
outputs are intentionally ignored. The public site works without them.

## Generated Artifact Policy

Commit generated XML when it is the viewer-facing source of truth or an
intentional review artifact. Current committed generated outputs include:

- `output/berendes1902_epidoc.xml` - public Berendes viewer XML.
- `output/sprengel1829_epidoc.xml` - current Sprengel viewer XML slot, generated
  from the Commentarius OCR stream.
- `output/beck2020_fresh_diplomatic_epidoc.xml` - private/local diplomatic Beck
  review XML.
- `output/*_audit/` - committed audit ledgers and summaries used to review TEI
  repair decisions.

Do not commit bulky facsimiles, local OCR scratch, private source PDFs/XML, or
secret-bearing files. Keep workflow-specific source folders distinct: Berendes
normalization starts from `chunks/`, Sprengel base-edition sidecars live under
`editions/sprengel1829/`, and Commentarius OCR inputs live under
`sprengel_comm/`.

## Validate And Rebuild

Normalize chunk source:

```bash
python3 scripts/normalize_page_furniture_and_footnotes.py --chunks-dir chunks
```

Regenerate the merged TEI:

```bash
python3 scripts/merge_chunks.py \
  --chunks-dir chunks \
  --manifest manifest.json \
  --header-template prompts/tei_header.xml \
  --output output/berendes1902_epidoc.xml
```

Validate structure:

```bash
python3 scripts/validate_structure.py output/berendes1902_epidoc.xml
```

Check the viewer JavaScript:

```bash
node --check viewer/app.js
```

Rebuild the Sprengel Commentarius viewer XML:

```bash
python3 scripts/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output output/sprengel1829_epidoc.xml
```

## Source Facsimiles

Berendes page images are served from Heidelberg University Library:

https://digi.ub.uni-heidelberg.de/diglit/berendes1902

Sprengel source images are wired to the Internet Archive item:

https://archive.org/details/b23982500_0001/page/n5/mode/2up

The TEI was generated from page image labels beginning at `page-0006.png`; this
maps to Archive page `n5` and IIIF image `b23982500_0001_0006.jp2`.

This repository does not bundle or relicense external facsimile images; see
`NOTICE.md`.

## Licenses

- Viewer and processing scripts: MIT (`LICENSE`).
- TEI/data/docs: Creative Commons Attribution-NonCommercial 4.0 International
  (`LICENSE-DATA.md`).
- External facsimile images: not bundled or relicensed here; see `NOTICE.md`.
