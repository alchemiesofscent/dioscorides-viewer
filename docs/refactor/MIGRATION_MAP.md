# Migration Map

This file is a path ledger only. It records candidate moves and their current
status; it does not authorize cleanup, deletion, semantic TEI rewrites, or
unlogged path migration. `docs/refactor/PLAN.md` is the forward plan.

## Rules

- Use `git mv` for tracked path moves.
- Preserve generated TEI outputs by default.
- Keep manifests and registries valid after every viewer-affecting move.
- Move source-like sidecars only after their role is recorded in
  `REPO_AUDIT.md`.
- Do not remove raw source assets until `SOURCE_MANIFEST_DRAFT.md` or its
  successor records checksums and external locations.

## Candidate Canonical Edition Paths

| Current path | Candidate path | Classification | Status | Notes |
| --- | --- | --- | --- | --- |
| `editions/berendes1902/tei/edition.xml` | `editions/berendes1902/tei/edition.xml` | scholarly TEI output | done | Moved from `output/berendes1902_epidoc.xml`; no TEI semantics changed. |
| `editions/berendes1902/manifest.json` | `editions/berendes1902/manifest.json` | manifest/registry | done | Moved from root `manifest.json`; viewer registry updated. |
| `chunks/` | `editions/berendes1902/source/chunks/` or keep | editorial/source-like input | undecided | Treat as committed editorial source for now. |
| `editions/sprengel1829/tei/edition.xml` | `editions/sprengel1829/tei/edition.xml` | scholarly TEI output | done | Moved from `output/sprengel1829_epidoc.xml`; no TEI semantics changed. |
| `editions/sprengel1829/manifest.json` | `editions/sprengel1829/manifest.json` | manifest/registry | done | Already near canonical; retained in place. |
| `editions/sprengel1829/sprengel_diplomatic.xml` | `editions/sprengel1829/source/sprengel_diplomatic.xml` | editorial/source-like input | pending | Preserve as source-like evidence. |
| `editions/sprengel1829/page_headers.csv` | `editions/sprengel1829/source/page_headers.csv` or `audit/` | audit/provenance | undecided | Contains accepted page-furniture evidence. |
| `editions/sprengel1830-comm/tei/edition.xml` | `editions/sprengel1830-comm/tei/edition.xml` | scholarly TEI output | done | Moved from `output/sprengel_comm_epidoc.xml`; builder input stayed in `sprengel_comm/`. |
| `editions/sprengel1830-comm/manifest.json` | `editions/sprengel1830-comm/manifest.json` | manifest/registry | done | Moved from `sprengel_comm/manifest.json`; viewer registry updated. |
| `sprengel_comm/outputs/sprengel_comm_merged.xml` | `editions/sprengel1830-comm/source/sprengel_comm_merged.xml` or keep | editorial/source-like input | undecided | Builder input; do not externalize until reproducibility is proven. |
| `sprengel_comm/ocr_fragments/` | `editions/sprengel1830-comm/source/ocr_fragments/` or keep | editorial/source-like input | undecided | Tracked fragments may contain hard-to-reproduce OCR/editorial decisions. |
| `sprengel_comm/sprengel_chapter_table.tsv` | `editions/sprengel1830-comm/source/sprengel_chapter_table.tsv` | editorial/source-like input | pending | Curated chapter authority table. |
| `editions/beck2020_fresh_diplomatic/tei/edition.xml` | `editions/beck2020_fresh_diplomatic/tei/edition.xml` | scholarly TEI output | done | Moved from `output/beck2020_fresh_diplomatic_epidoc.xml`; private registry updated. |
| `editions/beck2020_fresh_diplomatic/manifest.json` | `editions/beck2020_fresh_diplomatic/manifest.json` | manifest/registry | done | Retained existing directory to avoid breaking private registry conventions. |
| `editions/beck2020/` | archive or keep | local review UI / manifest / raw-like images | undecided | Audit before retirement; page images are ignored raw/generated assets. |
| `editions/beck2020_fresh/` | archive or keep | local review UI / manifest | undecided | Older fresh stream; preserve until superseded. |

## External Raw/Generated Boundary Candidates

| Current path | Candidate external location | Classification | Status | Notes |
| --- | --- | --- | --- | --- |
| `berendes1902__z3.pdf` | `$TEI_MAKER_DATA/sources/berendes1902/` | raw source | copied/checksummed in prior draft | Keep ignored repo copy until explicit removal decision. |
| `beck.pdf` | `$TEI_MAKER_DATA/sources/beck2020/` | raw source | copied/checksummed in prior draft | Private/local source. |
| `beck.xml` | `$TEI_MAKER_DATA/sources/beck2020/` | raw source | copied/checksummed in prior draft | Private/local comparison source. |
| `b23982500_0002_jp2.zip` | `$TEI_MAKER_DATA/sources/sprengel1830-comm/` | raw source | copied/checksummed in prior draft | Internet Archive JP2 source zip. |
| `tlg0656001.xml` through `tlg0656004.xml` | `$TEI_MAKER_DATA/sources/sprengel1829/` | raw source | copied/checksummed in prior draft | TLG/First1KGreek-like source XML. |
| `sprengel/` | `$TEI_MAKER_DATA/sources/sprengel1830-comm/` | raw source | pending | Extracted JP2 tree; likely reproducible from zip. |
| `ocr/` | `$TEI_MAKER_DATA/ocr/legacy/` | generated intermediate | copied/checksummed in prior draft | No repo removal yet. |
| `images/` | `$TEI_MAKER_DATA/images/` | generated intermediate/raw facsimile cache | copied/checksummed in prior draft | No repo removal yet. |
| `output/*_audit/` | edition `audit/` or `$TEI_MAKER_DATA/build/audits/` | audit/provenance | undecided | Some ledgers should stay committed; classify per edition. |

## Non-Migration Items For Now

- `viewer/` remains in place.
- `tools/beck-fresh-footnotes/` remains in place until Beck review surfaces are
  audited.
- `scripts/` wrappers remain until package replacements prove equivalent.
- `tei_maker/` remains the destination for reusable package logic.
