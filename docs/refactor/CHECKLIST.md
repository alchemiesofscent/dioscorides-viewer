# Refactor Checklist

## Phase 0: Baseline and Inventory

- [x] Confirm working branch.
- [x] Confirm clean or documented dirty git status.
- [x] Create `docs/refactor/PLAN.md`.
- [x] Create `docs/refactor/CHECKLIST.md`.
- [x] Create `docs/refactor/MIGRATION_MAP.md`.
- [x] Create `docs/refactor/WORKLOG.md`.
- [x] Create `docs/refactor/BASELINE.md`.
- [x] Capture repository tree and file inventory.
- [x] Identify tracked vs untracked large assets.
- [x] Identify current final TEI outputs.
- [x] Identify current manifests.
- [x] Identify viewer paths.
- [x] Identify scripts and wrappers.
- [x] Identify likely generated artifacts.
- [x] Identify likely hand-curated/editorial artifacts.
- [x] Capture baseline TEI/manifests/viewer files into `$TEI_MAKER_DATA/baseline/...`.
- [x] Generate checksums.
- [x] Commit baseline docs.

## Phase A: Package Skeleton Only, No Behavior Change

- [x] Add `pyproject.toml` using PEP 621.
- [x] Add console entry point `tei-maker`.
- [x] Create `tei_maker/__init__.py`.
- [x] Create `tei_maker/cli.py` with help text and stub subcommands.
- [x] Create `tei_maker/config.py`.
- [x] Create `tei_maker/io/paths.py`.
- [x] Path resolver supports `TEI_MAKER_DATA`.
- [x] Generation commands require `TEI_MAKER_DATA`.
- [x] Viewer/static validation commands do not require `TEI_MAKER_DATA`.
- [x] Generation output does not silently default to repo root.
- [x] Add `.env.example`.
- [x] Add minimal import and path-resolution tests.
- [x] Add `.github/workflows/test.yml` if appropriate.
- [x] Run tests.
- [x] Commit.

## Phase B: Data/Build Boundary and Externalization

- [x] Define canonical external data layout.
- [x] Decide whether `chunks/` content is generated or editorial.
- [x] Create `docs/refactor/SOURCE_MANIFEST_DRAFT.md` or `editions/sources.manifest.toml`.
- [x] Record source files, checksums, URLs, licenses, and required status.
- [x] Copy source PDFs/JP2/XML files to `$TEI_MAKER_DATA/sources/<slug>/`.
- [x] Verify checksums.
- [x] Copy OCR/chunk/image/audit generated trees to `$TEI_MAKER_DATA`.
- [ ] Archive no-longer-needed generated artifacts.
- [x] Update `.gitignore`.
- [ ] Update existing scripts minimally to use `tei_maker.io.paths` where safe.
- [x] Add `tei-maker data doctor`.
- [x] Verify old scripts still run where feasible.
- [ ] Commit.

## Phase C: Edition Registry and CTS Slugs

- [ ] Create `editions/editions.toml`.
- [ ] Keep filesystem slug separate from full CTS URN.
- [ ] Store edition registry fields.
- [ ] Document Sprengel Commentarius modeling decision.
- [ ] Rename committed edition folders using `git mv`.
- [ ] Move final TEI to `editions/<slug>/tei/edition.xml`.
- [ ] Move committed manifests to `editions/<slug>/manifest.json`.
- [ ] Move small committed Sprengel Commentarius artifacts if appropriate.
- [ ] Archive older Beck passes.
- [ ] Generate `editions/editions.json`.
- [ ] Add `tei-maker editions export-json`.
- [ ] Add `tei-maker editions export-json --check`.
- [ ] Update viewer paths.
- [ ] Run static server smoke test where feasible.
- [ ] Commit.

## Phase D: Code Motion into Package

- [ ] Move shared utilities first with `git mv`.
- [ ] Keep thin wrappers in old locations temporarily if needed.
- [ ] Move manifest/page-map logic.
- [ ] Move scaffold extraction logic.
- [ ] Move chunk merge logic.
- [ ] Move structural validation logic.
- [ ] Move OCR drivers.
- [ ] Move Berendes pipeline code into a subpackage.
- [ ] Move Sprengel base pipeline code into a subpackage.
- [ ] Move Sprengel Commentarius code into a subpackage.
- [ ] Move Beck code into a subpackage.
- [ ] Split Beck builder, footnotes, QC, OCR, and pipeline as needed.
- [ ] Add or update imports.
- [ ] Wire CLI commands.
- [ ] Run tests after each moved group.
- [ ] Commit after each meaningful group.

## Phase E1: Validator Introduction, Report-Only First

- [ ] Add schema directory.
- [ ] Pin numbered EpiDoc schema version.
- [ ] Record schema source and checksum.
- [ ] Implement XML well-formedness validation.
- [ ] Implement Relax NG validation.
- [ ] Add project-level checks.
- [ ] Run validator in report-only mode.
- [ ] Save report to `build/audits/<slug>/`.
- [ ] Avoid semantic TEI fixes in this phase.
- [ ] Add coherent CI validation.
- [ ] Commit.

## Phase E2: TEI/CTS Compliance Pass

- [ ] Implement `tei_maker/tei/headers.py`.
- [ ] Generate standardized `teiHeader` from `editions.toml`.
- [ ] Generate CTS-aware `refsDecl`.
- [ ] Keep full CTS URNs in metadata/attributes.
- [ ] Do not force full CTS URNs directly into `xml:id`.
- [ ] Implement safe XML/CTS ID helpers with tests.
- [ ] Apply to one edition first.
- [ ] Diff against baseline.
- [ ] Apply to remaining editions.
- [ ] Validate all committed TEI.
- [ ] Commit accepted semantic TEI diffs.

## Phase F: Documentation and Retirement

- [ ] Create or update `docs/pipeline.md`.
- [ ] Create or update `docs/editions.md`.
- [ ] Create or update `docs/tei-conventions.md`.
- [ ] Create or update `docs/contributing.md`.
- [ ] Rewrite `README.md`.
- [ ] Add Mermaid pipeline diagram.
- [ ] Document `TEI_MAKER_DATA`.
- [ ] Document clean clone behavior.
- [ ] Document external source reconstruction.
- [ ] Document archive policy.
- [ ] Document validation and CI.
- [ ] Retire old plans only after content is represented.
- [ ] Remove wrappers only after proof gates.
- [ ] Commit.
