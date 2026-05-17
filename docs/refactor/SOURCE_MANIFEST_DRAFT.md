# Source Manifest Draft

This draft records the first non-destructive Phase B source copy. It is not yet the canonical `editions/sources.manifest.toml`.

## External Root

- `TEI_MAKER_DATA`: `/home/seancoughlin/Projects/tei-maker-data`
- Source checksum file: `/home/seancoughlin/Projects/tei-maker-data/sources/SOURCES_SHA256SUMS.txt`
- Copy method: non-destructive copy to `$TEI_MAKER_DATA/sources/<slug>/`
- Removal/archive status: no repo files removed or archived in this batch

## Copied Sources

| Slug | Source file | External path | SHA256 | Required | License/source notes |
| --- | --- | --- | --- | --- | --- |
| `tlg0656.tlg001.berendes1902-ger1` | `berendes1902__z3.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes1902__z3.pdf` | `4b6cc1adcd4076d9423bccdfa937e683da31c8e65f908ee60605720ab5532ee7` | yes | Local source PDF; external facsimile rights not relicensed by repo. |
| `tlg0656.tlg001.berendes1902-ger1` | `berendes (1).xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes (1).xml` | `91763b5f9e18ea41c5671b01467035d14be78b81cf135f71eebf60cf316260e5` | yes | Existing source XML; currently tracked and not moved in this batch. |
| `tlg0656.tlg001.beck2020-eng1` | `beck.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.pdf` | `60ef22d296fcd4fcf8a2a0ff65830b138b8830913014ea2be816647dd7b617ff` | yes | Local/private source PDF; keep out of committed repo. |
| `tlg0656.tlg001.beck2020-eng1` | `beck.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.xml` | `4f87c63e9baa26f6e239f52161fc2e60b28c47de35149c803510d2ef442ab49d` | optional/comparison | Local/private source XML; keep out of committed repo. |
| `tlg0656.tlg001.sprengel1829-grclat1` | `tlg0656001.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656001.xml` | `a38ad4b330fd795793e65a310acf4eb74ea5ee6b1137f9a7cb18db9c584611f8` | yes | Local source XML. |
| `tlg0656.tlg001.sprengel1829-grclat1` | `tlg0656002.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656002.xml` | `7da6325c8684b1f6024e1f501b9637162f92df977fa4f6d3e633598165b8cbe9` | yes | Local source XML. |
| `tlg0656.tlg001.sprengel1829-grclat1` | `tlg0656003.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656003.xml` | `64ea7abbefaae9f2cd0931a113f82683b3ec7b931ff17456112276cd3bd79b16` | yes | Local source XML. |
| `tlg0656.tlg001.sprengel1829-grclat1` | `tlg0656004.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656004.xml` | `1c19a7c0068d3514d07e11b9abb2d6446a328c767e88b51908f940b01b970052` | yes | Local source XML. |
| `tlg0656.tlg001.sprengel1830-comm` | `b23982500_0002_jp2.zip` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1830-comm/b23982500_0002_jp2.zip` | `70b9786efda5f0d70ec0f4402144f18e6ce70cb4b5a878660967b8ac19a06165` | yes | Internet Archive JP2 source zip; extracted `sprengel/` tree not copied in this batch because it duplicates the zip and is 534M. |

## Deferred Phase B Copies

These trees are not copied or archived yet:

- `ocr/` at about 4.0G.
- `images/` at about 660M.
- `editions/beck2020/page_images/` at about 185M.
- `sprengel/` extracted JP2 tree at about 534M.
- `output/` audit/build trees at about 63M.
- `chunks/` at about 3.0M. This appears editorial and should remain versioned until explicitly reviewed.
- `sprengel_comm/ocr_fragments/`. These are tracked OCR fragments and may contain hard-to-reproduce editorial/generation decisions.

## Open Questions

- Whether `chunks/` should become committed edition source under the Berendes slug or external generated chunks.
- Whether `sprengel_comm/ocr_fragments/` are reproducible OCR intermediates or should stay committed as source-like evidence.
- Whether older Beck page image trees should be copied as generated images or archived as obsolete review evidence.
