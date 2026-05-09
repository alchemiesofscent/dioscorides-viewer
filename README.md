# Dioscorides Viewer

Static TEI/EpiDoc viewer for Dioscorides editions, beginning with Julius
Berendes' 1902 German translation, *Des Pedanios Dioskurides aus Anazarbos
Arzneimittellehre in fünf Büchern*, and an initial diplomatic import of
Sprengel's 1829/1830 Greek/Latin edition.

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
`editions/beck2020/private_registry.json` and appends Beck to the edition menu
when the private generated files are present. This local overlay does not change
the public `editions.json` registry used by GitHub Pages.

## Repository Contents

- `viewer/` - static browser viewer.
- `editions.json` - edition registry consumed by the viewer.
- `editions/sprengel1829/` - imported Sprengel TEI and generated page manifest.
- `chunks/` - normalized TEI chunk source for Berendes.
- `output/berendes1902_epidoc.xml` - merged TEI/EpiDoc output.
- `manifest.json` - Berendes page/image/chunk manifest.
- `scripts/` - normalization, merge, and validation tools.
- `prompts/` - TEI header and transcription prompt material.

Large local assets such as the source PDF, extracted page images, and OCR/hOCR
outputs are intentionally ignored. The public site works without them.

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
