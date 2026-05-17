# TEI Maker Refactor Plan

## Target Architecture

- Python package: `tei_maker/`
- Console command: `tei-maker`
- Canonical edition registry: `editions/editions.toml`
- Viewer registry generated from TOML: `editions/editions.json`
- Committed final TEI: `editions/<slug>/tei/edition.xml`
- External data root: `/home/seancoughlin/Projects/tei-maker-data`, addressed by `TEI_MAKER_DATA`
- External source/generated layout:
  - `$TEI_MAKER_DATA/sources/<slug>/`
  - `$TEI_MAKER_DATA/ocr/<slug>/`
  - `$TEI_MAKER_DATA/chunks/<slug>/`
  - `$TEI_MAKER_DATA/images/<slug>/`
  - `$TEI_MAKER_DATA/build/audits/<slug>/`
  - `$TEI_MAKER_DATA/archive/<timestamp>/<original-relative-path>`
- Repo-generated audits: gitignored `build/audits/<slug>/`
- Static viewer: works from committed TEI and committed registry without `TEI_MAKER_DATA`
- Generation/rebuild commands: require explicit `TEI_MAKER_DATA`

## Current Baseline

- Initial observed branch before branch creation: `main`
- Refactor branch: `refactor/tei-maker-pipeline`
- Main/baseline tag: `pre-refactor-baseline` at `754d9622d4b85bbaaec20d3d4eb4743541b981c9`
- Working baseline tag: `pre-refactor-working-baseline` at current branch HEAD after branch-state discrepancy
- Current branch HEAD at plan creation: `18fecb1` (`Archive failed Beck Gemini pipeline`)
- Expected external data root: `/home/seancoughlin/Projects/tei-maker-data`

The first sandbox status reported dirty Beck/Gemini files on `main`. After the approved branch switch, the working tree was clean on `refactor/tei-maker-pipeline` with those files represented by commit `18fecb1` under `archive/beck-gemini-full-page-pipeline/`. This discrepancy is recorded as a baseline risk in `BASELINE.md` and `WORKLOG.md`.

## Edition Slugs

- `tlg0656.tlg001.berendes1902-ger1`
- `tlg0656.tlg001.sprengel1829-grclat1`
- `tlg0656.tlg001.sprengel1830-comm`
- `tlg0656.tlg001.beck2020-eng1`

## Phase Checklist

### Phase 0: Baseline and inventory

Create planning docs, capture repo state, identify source/generated/editorial files, create an external baseline snapshot with checksums, then commit the docs before any structural refactor.

### Phase A: Package skeleton only, no behavior change

Add `pyproject.toml`, `tei_maker/`, path-resolution helpers, a `tei-maker` CLI with stub commands, `.env.example`, minimal tests, and CI if appropriate. Do not move existing pipeline logic.

### Phase B: Data/build boundary and externalization

Define external data layout, identify generated vs editorial artifacts, copy source assets and generated scratch trees to `TEI_MAKER_DATA`, verify checksums, update `.gitignore`, and add an initial `tei-maker data doctor`.

### Phase C: Edition registry and CTS-style slug migration

Create `editions/editions.toml`, keep slug and CTS fields separate, move final committed TEI and manifests under canonical slug folders, generate `editions/editions.json`, and keep the viewer working.

### Phase D: Code motion into package

Move code with `git mv` in small groups, keep wrappers temporarily, then wire package modules and CLI commands.

### Phase E1: Validator introduction, report-only first

Add pinned schema validation, XML/project checks, report-only output under `build/audits/<slug>/`, and CI wiring where coherent.

### Phase E2: TEI/CTS compliance pass

Standardize headers and CTS declarations separately from mechanical refactors. Apply to one edition first, compare against baseline, then continue.

### Phase F: Documentation and retirement

Replace overlapping old docs, document `TEI_MAKER_DATA`, clean-clone behavior, validation, archive policy, and retire wrappers only after proof gates.

## Validation Strategy

- Preserve baseline behavior before mechanical moves.
- Run existing checks first:
  - `python3 scripts/validate_structure.py output/berendes1902_epidoc.xml`
  - `node --check viewer/app.js`
  - `python3 scripts/validate_beck_fresh_diplomatic.py output/beck2020_fresh_diplomatic_epidoc.xml --manifest editions/beck2020_fresh_diplomatic/manifest.json --expected-pdf-pages 711`
  - `python3 scripts/build_sprengel_comm_epidoc.py --source sprengel_comm/outputs/sprengel_comm_merged.xml --chapter-table sprengel_comm/sprengel_chapter_table.tsv --output /tmp/tei-maker-sprengel-comm-baseline.xml`
- Treat missing `pytest` as a baseline tooling gap until packaging adds test dependencies.
- After Phase A, add import/path tests and require `pytest`.
- After Phase C, require `tei-maker editions export-json --check`.
- After validator work, require `tei-maker validate --all` to pass or emit documented known issues.

## Archive Policy

- Do not delete valuable project material during mechanical phases.
- Archive uncertain or heavy generated/source material under `$TEI_MAKER_DATA/archive/<YYYYMMDD-HHMMSS>/<original-relative-path>`.
- Preserve original relative paths.
- Record archive operations in `$TEI_MAKER_DATA/archive/ARCHIVE_MANIFEST.tsv`.
- For tracked small historical material, prefer `git mv` into a repo archive only when it is useful to review.
- Do not remove final TEI, prompts, OCR, chunks, manifests, or working scripts without a committed checkpoint and proof gate.

## Commit Policy

- Commit after planning docs.
- Commit after package skeleton.
- Commit after each externalization batch.
- Commit after each slug migration.
- Commit after each package move group.
- Commit after each CLI command becomes functional.
- Commit after validator/test workflow changes.
- Keep mechanical moves separate from semantic TEI/CTS changes.
- Stage only files belonging to the current phase.

## Stop Conditions

Stop and document before continuing if:

- A move would overwrite a non-identical file.
- A checksum mismatch appears.
- A TEI output changes during a mechanical phase.
- A viewer path cannot be resolved.
- A source asset appears untracked and irreplaceable.
- A script has unknown callers.
- A generated artifact may contain editorial decisions.
- A test failure appears after a change and was not present in baseline.
- A deletion candidate has not been archived or proven disposable.
