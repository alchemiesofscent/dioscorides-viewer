# Migration Map

| Current path | New path | Action | Reason | Tracked/untracked/unknown | Checksum captured | Commit hash when completed |
| --- | --- | --- | --- | --- | --- | --- |
| `output/berendes1902_epidoc.xml` | `editions/tlg0656.tlg001.berendes1902-ger1/tei/edition.xml` | git-mv | Move committed final Berendes TEI under canonical edition slug. | tracked | yes, baseline snapshot | pending |
| `manifest.json` | `editions/tlg0656.tlg001.berendes1902-ger1/manifest.json` | git-mv | Move Berendes viewer manifest beside edition TEI. | tracked | yes, baseline snapshot | pending |
| `output/sprengel1829_epidoc.xml` | `editions/tlg0656.tlg001.sprengel1829-grclat1/tei/edition.xml` | git-mv | Move committed Sprengel base TEI under canonical slug. | tracked | yes, baseline snapshot | pending |
| `editions/sprengel1829/manifest.json` | `editions/tlg0656.tlg001.sprengel1829-grclat1/manifest.json` | git-mv | Move Sprengel base manifest beside edition TEI. | tracked | yes, baseline snapshot | pending |
| `editions/sprengel1829/page_headers.csv` | `editions/tlg0656.tlg001.sprengel1829-grclat1/page_headers.csv` | git-mv | Preserve committed page-header sidecar with edition. | tracked | yes, baseline snapshot | pending |
| `editions/sprengel1829/sprengel_diplomatic.xml` | `editions/tlg0656.tlg001.sprengel1829-grclat1/source/sprengel_diplomatic.xml` | git-mv | Preserve small committed source-like Sprengel artifact. | tracked | yes, baseline snapshot | pending |
| `output/sprengel_comm_epidoc.xml` | `editions/tlg0656.tlg001.sprengel1830-comm/tei/edition.xml` | git-mv | Move committed Commentarius TEI under commentary slug. | tracked | yes, baseline snapshot | pending |
| `sprengel_comm/manifest.json` | `editions/tlg0656.tlg001.sprengel1830-comm/manifest.json` | git-mv | Move committed Commentarius manifest beside edition TEI if viewer uses it. | tracked | yes, baseline snapshot | pending |
| `sprengel_comm/ocr_fragments/` | keep committed until reproducibility is proven | keep | OCR fragments are source-like build inputs for now and may contain hard-to-reproduce editorial/generation decisions. | tracked | no | pending |
| `sprengel_comm/outputs/sprengel_comm_merged.xml` | keep committed until reproducibility is proven | keep | Merged OCR XML is a source-like builder input; do not externalize or remove until replacement is proven. | tracked | yes, baseline snapshot | pending |
| `sprengel_comm/sprengel_chapter_table.tsv` | `editions/tlg0656.tlg001.sprengel1830-comm/sprengel_chapter_table.tsv` | git-mv | Chapter table is curated authority data, not disposable generated output. | tracked | yes, baseline snapshot | pending |
| `output/beck2020_fresh_diplomatic_epidoc.xml` | `editions/tlg0656.tlg001.beck2020-eng1/tei/edition.xml` | git-mv | Current committed Beck final/review TEI should become edition TEI if accepted as final. | tracked | yes, baseline snapshot | pending |
| `editions/beck2020_fresh_diplomatic/manifest.json` | `editions/tlg0656.tlg001.beck2020-eng1/manifest.json` | git-mv | Current Beck diplomatic manifest should move beside edition TEI. | tracked | yes, baseline snapshot | pending |
| `editions/beck2020/` | `$TEI_MAKER_DATA/archive/<timestamp>/editions/beck2020/` | archive | Older Beck pass/review stream; preserve before retirement. | mixed tracked/ignored | partial | pending |
| `editions/beck2020_fresh/` | `$TEI_MAKER_DATA/archive/<timestamp>/editions/beck2020_fresh/` | archive | Older fresh Beck stream; preserve before retirement. | mixed tracked/ignored | partial | pending |
| `output/*_audit/` | `$TEI_MAKER_DATA/build/audits/<slug>/legacy/` | copy-external | Audits are generated/review build output; copied externally without removing committed final TEI. | mixed tracked/ignored | yes, generated copy | pending |
| `output/beck_text_cleaning/` | `$TEI_MAKER_DATA/build/audits/tlg0656.tlg001.beck2020-eng1/legacy/beck_text_cleaning/` | copy-external | Generated review outputs and crops. | ignored/untracked likely | yes, generated copy | pending |
| `ocr/` | `$TEI_MAKER_DATA/ocr/legacy/` | copy-external | OCR intermediates belong outside repo; copied as one legacy tree pending slug-level subdivision. | ignored | yes, generated copy | pending |
| `images/raw/` | `$TEI_MAKER_DATA/images/tlg0656.tlg001.berendes1902-ger1/raw/` | copy-external | Local extracted Berendes images are bulky generated assets. | ignored | yes, generated copy | pending |
| `images/enhanced/` | `$TEI_MAKER_DATA/images/tlg0656.tlg001.berendes1902-ger1/enhanced/` | copy-external | Local enhanced images are generated assets. | ignored | yes, generated copy | pending |
| `editions/beck2020/page_images/` | `$TEI_MAKER_DATA/images/tlg0656.tlg001.beck2020-eng1/page_images/` | copy-external | Beck page images are bulky local assets. | ignored | yes, generated copy | pending |
| `b23982500_0002_jp2.zip` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1830-comm/b23982500_0002_jp2.zip` | copy-external | Source JP2 zip belongs outside repo. | ignored | yes, source copy | pending |
| `sprengel/` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1830-comm/sprengel/` | copy-external | Extracted JP2 source tree belongs outside repo. | ignored | no | pending |
| `beck.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.pdf` | copy-external | Source PDF belongs outside repo. | ignored | yes, source copy | pending |
| `beck.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.beck2020-eng1/beck.xml` | copy-external | Private/source XML belongs outside repo. | ignored | yes, source copy | pending |
| `berendes1902__z3.pdf` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes1902__z3.pdf` | copy-external | Source PDF belongs outside repo. | ignored | yes, source copy | pending |
| `berendes (1).xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.berendes1902-ger1/berendes (1).xml` | copy-external | Source XML belongs outside repo if still required. | tracked | yes, baseline snapshot | pending |
| `tlg065600*.xml` | `$TEI_MAKER_DATA/sources/tlg0656.tlg001.sprengel1829-grclat1/` | copy-external | Source XML files belong outside repo unless selected as committed source artifacts. | ignored | yes, source copy | pending |
| `chunks/` | `editions/tlg0656.tlg001.berendes1902-ger1/chunks/` in a later slug migration | keep | Editorial committed source for now, not generated build output. | tracked | partial | pending |
| `scripts/` | `tei_maker/...` with wrappers | git-mv | Package pipeline logic in small groups. | tracked plus ignored caches | not applicable | pending |
| `viewer/` | `viewer/` | keep | Static viewer should continue to work from committed TEI. | tracked | yes, baseline snapshot | pending |
| `editions.json` | `editions/editions.json` | git-mv/regenerate | Generated viewer registry from `editions.toml`. | tracked | yes, baseline snapshot | pending |
| `archive/beck-gemini-full-page-pipeline/` | `archive/beck-gemini-full-page-pipeline/` | keep | Current branch contains archived failed Beck Gemini pipeline; no migration until broader docs/archive policy. | tracked | yes, baseline snapshot | pending |
