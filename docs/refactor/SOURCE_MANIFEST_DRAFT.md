# Source Manifest Draft

This draft records raw/source assets and external copies. It is separate from
generated TEI outputs, which are corpus assets preserved in git until a validated
replacement and retirement note exist.

## Scope

Include:

- source PDFs;
- page images and extracted image trees;
- JP2 zips and extracted JP2 trees;
- TLG/First1KGreek XML;
- private/local source XML;
- large OCR/image intermediates needed for reproducibility.

Do not list committed scholarly TEI outputs here except as source paths for
checksum comparison when a future external copy is explicitly made.

## External Root

- Default external root from prior work:
  `/home/seancoughlin/Projects/tei-maker-data`.
- Environment variable: `TEI_MAKER_DATA`.
- Prior checksum files:
  - `$TEI_MAKER_DATA/sources/SOURCES_SHA256SUMS.txt`
  - `$TEI_MAKER_DATA/ocr/legacy/OCR_LEGACY_SHA256SUMS.txt`
  - `$TEI_MAKER_DATA/images/IMAGES_SHA256SUMS.txt`
  - `$TEI_MAKER_DATA/build/audits/AUDITS_SHA256SUMS.txt`

## Raw Source Assets

| Repo path | External path | Classification | Required | Checksum status | Repo status | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `berendes1902__z3.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes1902__z3.pdf` | raw source | yes | captured in prior source manifest | ignored | External facsimile rights not relicensed by repo. |
| `berendes (1).xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes (1).xml` | editorial/source-like input | yes | captured in prior source manifest | tracked | Keep tracked until replacement role is decided. |
| `beck.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.pdf` | raw source | yes | captured in prior source manifest | ignored | Private/local source PDF. |
| `beck.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.xml` | raw source | optional | captured in prior source manifest | ignored | Private/local comparison XML. |
| `tlg0656001.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656001.xml` | raw source | yes | captured in prior source manifest | ignored | Source XML. |
| `tlg0656002.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656002.xml` | raw source | yes | captured in prior source manifest | ignored | Source XML. |
| `tlg0656003.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656003.xml` | raw source | yes | captured in prior source manifest | ignored | Source XML. |
| `tlg0656004.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/tlg0656004.xml` | raw source | yes | captured in prior source manifest | ignored | Source XML. |
| `b23982500_0002_jp2.zip` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1830-comm/b23982500_0002_jp2.zip` | raw source | yes | captured in prior source manifest | ignored | Internet Archive JP2 zip. |
| `sprengel/` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1830-comm/sprengel/` | raw source | optional if zip is sufficient | pending | ignored | Extracted JP2 tree, about 534M in current checkout. |

## Generated Or Bulky Reproducibility Assets

| Repo path | External path | Classification | Checksum status | Repo status | Notes |
| --- | --- | --- | --- | --- | --- |
| `ocr/` | `$TEI_MAKER_DATA/ocr/legacy/` | generated intermediate | captured in prior generated-artifact manifest | ignored/mixed | About 4.0G; no repo removal yet. |
| `images/raw/` and `images/enhanced/` | `$TEI_MAKER_DATA/images/tlg0656.tlg001.berendes1902-ger1/` | generated intermediate/raw facsimile cache | captured in prior generated-artifact manifest | ignored | About 660M total under `images/`. |
| `editions/beck2020/page_images/` | `$TEI_MAKER_DATA/images/tlg0656.tlg001.beck2020-eng1/page_images/` | generated intermediate/raw facsimile cache | captured in prior generated-artifact manifest | ignored | Beck page image cache. |
| `output/*_audit/` | `$TEI_MAKER_DATA/build/audits/<slug>/legacy/` or committed edition `audit/` | audit/provenance | partial prior copy | tracked/mixed | Classify before moving or retiring. |
| `chunks_pilot_gate/` | `$TEI_MAKER_DATA/build/audits/legacy/` | generated intermediate | pending | ignored | Pilot scratch; audit before deletion. |

## Source-Like Material Kept In Git For Now

These are not raw public assets, but they may encode editorial decisions or
hard-to-reproduce generation evidence:

- `chunks/`;
- `sprengel_comm/ocr_fragments/`;
- `sprengel_comm/outputs/sprengel_comm_merged.xml`;
- `sprengel_comm/sprengel_chapter_table.tsv`;
- `editions/sprengel1829/page_headers.csv`;
- Beck accepted/correction ledgers under ignored OCR trees and committed audit
  summaries.

Do not remove or externalize these as disposable intermediates without a
specific audit entry.

## Open Decisions

- Whether the existing external source copies should be refreshed after this
  documentation reset.
- Whether `sprengel/` needs its own checksum tree or can be reproduced from the
  JP2 zip.
- Which committed audit ledgers should move beside canonical edition folders and
  which copied generated audits can remain external-only.
