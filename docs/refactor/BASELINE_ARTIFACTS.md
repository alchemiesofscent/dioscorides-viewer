# Baseline Artifacts

Historical/supporting record. This file records the earlier external baseline
snapshot. It is not the current source manifest or migration plan. Use
`docs/refactor/PLAN.md`, `docs/refactor/REPO_AUDIT.md`, and
`docs/refactor/SOURCE_MANIFEST_DRAFT.md` for current refactor decisions.

## External Snapshot

- Snapshot path: `/home/seancoughlin/Projects/tei-maker-data/baseline/20260517-181217`
- Checksum file: `/home/seancoughlin/Projects/tei-maker-data/baseline/20260517-181217/BASELINE_SHA256SUMS.txt`
- Files copied: 151 files plus the checksum file

## Captured Material

The snapshot captures:

- Committed viewer-facing TEI outputs from `output/`.
- Root and edition manifests/registries.
- Viewer and local review-surface files.
- Scripts and prompts needed to regenerate current output.
- Current docs and workflow file.
- Sprengel Commentarius builder inputs and authority tables.
- Current branch archive material under `archive/`.

## Not Captured Yet

The snapshot intentionally does not copy the full ignored source/generated asset set. These need Phase B source/externalization manifests and checksums before any removal:

- Source PDFs and source XMLs at repo root.
- JP2 zip and extracted `sprengel/` JP2 tree.
- Full `ocr/` trees.
- Raw/enhanced image trees.
- Beck page images.
- Generated audit crops and scratch output.

No bulky baseline artifacts are committed to the repo.
