# Refactor Plan

This is the single authoritative forward plan for the `tei-maker` refactor.
Other files in `docs/refactor/` support this plan: `REPO_AUDIT.md` records the
current repository inventory, `MIGRATION_MAP.md` records path decisions only,
`SOURCE_MANIFEST_DRAFT.md` records external raw/source assets, and
`WORKLOG.md` records each work session.

## Principle

The project is scholarly-output-first. Generated EpiDoc TEI XMLs are corpus
assets and regression baselines, not disposable build products. Do not delete or
retire Berendes, Sprengel, Sprengel Commentarius, Beck, or pilot TEI outputs
unless a validated replacement exists and the retirement is explicitly recorded.

Cleanup means retiring obsolete process artifacts after audit. It does not mean
discarding scholarly XML, manifests, accepted review decisions, or provenance
needed to explain current TEI.

## Preserved Edition Families

### Berendes 1902

- Current TEI: `output/berendes1902_epidoc.xml`.
- Current manifest: `manifest.json`.
- Source-like/editorial material: `chunks/`, `berendes (1).xml`, prompts, and
  Berendes audit ledgers.
- Status: preserve as current public viewer output and regression baseline.

### Sprengel 1829/1830 Base Text

- Current TEI: `output/sprengel1829_epidoc.xml`.
- Current manifest: `editions/sprengel1829/manifest.json`.
- Source-like/editorial material:
  `editions/sprengel1829/sprengel_diplomatic.xml`,
  `editions/sprengel1829/page_headers.csv`, and Sprengel audit ledgers.
- Status: preserve as current review-grade viewer output and regression
  baseline.

### Sprengel 1830 Commentarius

- Current TEI: `output/sprengel_comm_epidoc.xml`.
- Current manifest: `sprengel_comm/manifest.json`.
- Source-like/editorial material: `sprengel_comm/outputs/sprengel_comm_merged.xml`,
  `sprengel_comm/sprengel_chapter_table.tsv`, OCR fragments, prompt notes, and
  workflow metadata.
- Status: preserve as current review-grade viewer output and regression
  baseline.

### Beck 2020

- Current diplomatic TEI:
  `output/beck2020_fresh_diplomatic_epidoc.xml`.
- Current manifest:
  `editions/beck2020_fresh_diplomatic/manifest.json`.
- Related older/local streams:
  `editions/beck2020/`, `editions/beck2020_fresh/`, ignored local TEI outputs,
  OCR ledgers, and review queues.
- Status: preserve private/local review outputs and accepted sidecars until a
  validated public/private replacement and retirement note exist.

### Pilot TEI And Review XML

Any pilot TEI that records work not represented in a later accepted edition is a
preservation candidate. Classify it before moving, archiving, or deleting it.

## Target Architecture

- Canonical edition folders:
  - `editions/<slug>/tei/edition.xml`
  - `editions/<slug>/manifest.json`
  - `editions/<slug>/source/` for small committed source-like sidecars when
    appropriate
  - `editions/<slug>/audit/` for committed review/audit material that remains
    useful
- Viewer registry:
  - committed public registry for public editions;
  - documented local/private registry overlay for private editions;
  - registered paths must resolve from a clean checkout for public editions.
- External raw data root:
  - `TEI_MAKER_DATA` or the documented shared default;
  - contains source PDFs, images, JP2 files, TLG/First1KGreek XML, private/local
    XML, OCR scratch, and bulky generated intermediates;
  - every externalized source has a checksum and source/license note.
- Reusable pipeline package:
  - `tei_maker/` owns path/config handling, edition registry handling,
    page/image inventory, OCR evidence readers, TEI writer utilities, manifest
    writing, validation helpers, and audit/report output.
- Validation commands:
  - package checks with `compileall`, `unittest`, and `tei_maker data doctor`;
  - viewer syntax with `node --check viewer/app.js`;
  - edition-specific TEI validation and rebuild commands recorded in the
    worklog before path changes.
- Audit logs:
  - `docs/refactor/WORKLOG.md` records each work session;
  - committed audit ledgers remain with the relevant edition or in a documented
    legacy location until superseded.

## Phase 1: Documentation Reset

Scope: docs-only.

- Rewrite `README.md` around scholarly EpiDoc outputs, viewer use, reusable
  pipeline direction, and the external raw-data boundary.
- Rewrite this plan as the single forward plan.
- Add `docs/refactor/REPO_AUDIT.md` with path-group inventory and
  preserve/archive/remove decisions.
- Rewrite `CHECKLIST.md`, `MIGRATION_MAP.md`, and `SOURCE_MANIFEST_DRAFT.md` so
  they support this plan instead of competing with it.
- Mark `BASELINE.md`, `BASELINE_ARTIFACTS.md`, and `WORKLOG.md` as historical or
  supporting records where appropriate.
- Run docs/package checks.
- Commit the docs-only checkpoint.

No cleanup, deletion, path migration, or code motion happens in this phase.

## Phase 2: Audit And Logging Protocol

Before each later implementation phase, run and record:

- `git status --short`;
- relevant `git status --ignored --short`;
- relevant `find`, `du`, and `git ls-files` inventory commands;
- current validation commands for affected TEI/viewer surfaces.

Each worklog entry records timestamp, objective, files/directories touched,
commands run, verification results, docs updated, commit hash when known, and
open risks or deferred decisions. Command failures are recorded with the chosen
response.

## Phase 3: Preserve Scholarly TEI Outputs

Inventory all generated/review-grade TEI XMLs before moving anything:

- Berendes TEI;
- Sprengel base text TEI;
- Sprengel Commentarius TEI;
- Beck generated TEI variants;
- pilot TEI not represented elsewhere.

Move outputs later with `git mv` into canonical edition folders only after the
audit docs are complete. Do not rewrite TEI semantics during path migration.
Older generated variants remain named review/archive outputs until explicitly
superseded.

## Phase 4: External Raw Data Boundary

Move or copy raw reusable files into shared external storage with checksums:
PDFs, page images, JP2 zips and extracted trees, TLG/First1KGreek XML,
private/local source XML, and large OCR/image intermediates needed for
reproducibility.

The source manifest records original repo path, external path, checksum,
source/license notes, required/optional status, and whether the repo copy
remains, is ignored, or is later removed. No raw-source deletion happens until
manifest and checksum verification are complete.

## Phase 5: Viewer Stability

The viewer remains first-class and must keep working throughout the refactor.

Requirements:

- load committed TEI outputs and current manifests/registry;
- run locally from repo root with `python3 -m http.server 8000`;
- avoid private raw-data requirements for public editions;
- handle private/local editions only through documented local registry behavior.

After each viewer-affecting change, run `node --check viewer/app.js`, verify
registered paths, and update README/refactor docs if commands or paths change.

## Phase 6: Reusable Pipeline Extraction

Extract reusable logic from the current scripts without centering the design on
one pilot. The target pipeline covers raw source or page images, page inventory,
OCR evidence, diplomatic TEI construction, manifest generation, validation
reports, and viewer registration.

Old scripts remain wrappers until replacement CLI commands pass equivalent
checks. Retire wrappers only after the worklog records proof that the new command
covers the old behavior.

## Phase 7: Cleanup And Retirement

Only retire artifacts after audit classification.

Likely retirement candidates:

- caches and `__pycache__`;
- temporary crops;
- old visual-pass panels/responses;
- obsolete OCR scratch;
- failed experiment outputs;
- duplicated generated intermediates;
- stale private review queues that no longer support TEI provenance.

Not retirement candidates by default:

- generated TEI XMLs;
- manifests needed by the viewer;
- source-like editorial sidecars;
- accepted review decisions;
- provenance needed to explain current TEI;
- raw source files before external checksum capture.

If uncertain, archive rather than delete.

## Phase 8: Validation And Acceptance

Core checks after docs-only changes:

```bash
git diff -- README.md docs/refactor
python3 -m compileall tei_maker tests
python3 -m unittest discover -s tests
python3 -m tei_maker data doctor
```

Core checks after TEI/viewer path changes:

```bash
python3 scripts/validate_structure.py output/berendes1902_epidoc.xml
python3 scripts/validate_beck_fresh_diplomatic.py \
  output/beck2020_fresh_diplomatic_epidoc.xml \
  --manifest editions/beck2020_fresh_diplomatic/manifest.json \
  --expected-pdf-pages 711
python3 scripts/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output /tmp/tei-maker-sprengel-comm-baseline.xml
node --check viewer/app.js
```

Acceptance criteria:

- README clearly explains the project goal.
- This plan is the single forward plan.
- `REPO_AUDIT.md` accounts for repo contents.
- `WORKLOG.md` records every phase.
- No generated TEI XML is deleted.
- Viewer remains usable.
- Raw data boundary is documented with checksums.
- Pipeline refactor proceeds only from documented inventory and validation.

## Commit Policy

Use small commits. The current checkpoint is:

1. `docs(refactor): reset plan around scholarly TEI outputs`

Later checkpoints should separate external source manifests, edition moves,
viewer registry changes, and pipeline extraction. Each commit updates
`WORKLOG.md`, includes only files for its phase, passes relevant checks, and
leaves `git status --short` clean unless explicitly documented.
