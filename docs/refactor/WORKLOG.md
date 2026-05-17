# Refactor Worklog

Supporting record for `docs/refactor/PLAN.md`. Every work session should add an
entry with objective, touched files/directories, commands, verification, docs
updated, commit hash when known, and open risks.

## 2026-05-17 20:21 Europe/Budapest

- Objective: Perform the docs-only reset requested by the autonomous refactor
  plan before any cleanup, migration, deletion, or code motion.
- Files/directories touched:
  - `README.md`
  - `docs/refactor/PLAN.md`
  - `docs/refactor/REPO_AUDIT.md`
  - `docs/refactor/CHECKLIST.md`
  - `docs/refactor/MIGRATION_MAP.md`
  - `docs/refactor/SOURCE_MANIFEST_DRAFT.md`
  - `docs/refactor/BASELINE.md`
  - `docs/refactor/BASELINE_ARTIFACTS.md`
  - `docs/refactor/WORKLOG.md`
- Commands run:
  - `git status --short`
  - `git status --ignored --short | sed -n '1,200p'`
  - `git rev-parse --abbrev-ref HEAD`
  - `git rev-parse --short HEAD`
  - `git ls-files | wc -l`
  - `find . -maxdepth 2 -type d | sort`
  - `du -sh ./* ./.??* 2>/dev/null | sort -hr | sed -n '1,80p'`
  - `git ls-files docs/refactor README.md | sort`
  - `git diff -- README.md docs/refactor`
  - `python3 -m compileall tei_maker tests`
  - `python3 -m unittest discover -s tests`
  - `python3 -m tei_maker data doctor`
  - `node --check viewer/app.js`
  - `git diff --check`
  - `git status --short`
- Verification result:
  - Diff reviewed for docs-only scope.
  - `compileall`: pass.
  - `unittest`: 9 tests pass.
  - `tei_maker data doctor`: pass with expected warning that
    `TEI_MAKER_DATA` is not set, then reports the default external data root and
    expected source/generated mirrors present.
  - `node --check viewer/app.js`: pass.
  - `git diff --check`: pass.
- Docs updated: README and all current refactor docs listed above.
- Commit hash: pending at time of entry.
- Open risks or deferred decisions:
  - Current branch already contains prior Phase A/B-style refactor work; this
    checkpoint only resets documentation authority.
  - No generated TEI, manifests, raw data, scripts, or viewer paths were moved
    or deleted.
  - Raw/source externalization status is based on prior manifest records and
    should be refreshed before any removal decision.

## 2026-05-17 18:10 Europe/Budapest

- Action taken: Started Phase 0 baseline and safety inspection.
- Commands run, summarized:
  - `git status --short`
  - `git rev-parse --abbrev-ref HEAD`
  - `git rev-parse HEAD`
  - `find . -maxdepth 3 -type d | sort`
  - `find . -maxdepth 3 -type f | sort`
  - `find . -name "__pycache__" -type d`
  - `find editions -maxdepth 4 -type f | sort`
  - `find output -maxdepth 4 -type f | sort`
  - `find scripts -maxdepth 4 -type f | sort`
  - `find ocr chunks chunks_pilot_gate images -maxdepth 3 -type f | sort`
  - `git ls-files | sort`
  - `git ls-files --others --exclude-standard | sort`
  - `git ls-files -z | xargs -0 du -h | sort -hr | head -50`
- Files/directories affected: none.
- Verification result: Baseline inventory completed. Initial sandbox status reported dirty files on `main`: modified `scripts/build_beck_fresh_diplomatic.py` plus untracked Beck/Gemini prompt, docs, plan, and script files.
- Commit hash: none.
- Open issues or risks: After approved git branch creation, the working tree became clean on `refactor/tei-maker-pipeline` at commit `18fecb1`; this differs from the initial sandbox report and is treated as a baseline discrepancy.

## 2026-05-17 18:11 Europe/Budapest

- Action taken: Created baseline branch/tag references.
- Commands run, summarized:
  - `git switch -c refactor/tei-maker-pipeline`
  - `git tag pre-refactor-baseline`
  - `git tag pre-refactor-working-baseline`
- Files/directories affected: `.git` metadata only.
- Verification result: Current branch is `refactor/tei-maker-pipeline`. `pre-refactor-baseline` points to `main` at `754d9622d4b85bbaaec20d3d4eb4743541b981c9`; `pre-refactor-working-baseline` points to current branch HEAD `18fecb1`.
- Commit hash: none.
- Open issues or risks: `pre-refactor-baseline` does not point at current branch HEAD because of the observed branch-state discrepancy; the added working tag preserves the actual refactor starting point.

## 2026-05-17 18:12 Europe/Budapest

- Action taken: Ran baseline validation commands.
- Commands run, summarized:
  - `python3 scripts/validate_structure.py output/berendes1902_epidoc.xml`
  - `node --check viewer/app.js`
  - `python3 scripts/validate_beck_fresh_diplomatic.py output/beck2020_fresh_diplomatic_epidoc.xml --manifest editions/beck2020_fresh_diplomatic/manifest.json --expected-pdf-pages 711`
  - `python3 scripts/build_sprengel_comm_epidoc.py --source sprengel_comm/outputs/sprengel_comm_merged.xml --chapter-table sprengel_comm/sprengel_chapter_table.tsv --output /tmp/tei-maker-sprengel-comm-baseline.xml`
  - `python3 -m pytest`
- Files/directories affected: `/tmp/tei-maker-sprengel-comm-baseline.xml` created outside repo.
- Verification result:
  - Berendes validation: 0 issues.
  - Viewer JS syntax: pass.
  - Beck diplomatic validation: 0 errors, 1 warning (`FOOTNOTE_QA_OPEN_BODY_ROWS: 101 unresolved QA rows outside triaged back matter`).
  - Sprengel Commentarius builder: wrote `/tmp/tei-maker-sprengel-comm-baseline.xml`, 328 pages, 2715 footnotes, with documented unmatched headings.
  - Pytest: failed before refactor because `/usr/bin/python3: No module named pytest`.
- Commit hash: none.
- Open issues or risks: Existing validation is script-based; no package/test dependency metadata exists yet.

## 2026-05-17 18:12 Europe/Budapest

- Action taken: Created external baseline snapshot with checksums.
- Commands run, summarized:
  - Created `/home/seancoughlin/Projects/tei-maker-data/baseline/20260517-181217`.
  - Copied current committed TEI outputs, manifests, viewer files, tools, scripts, prompts, docs, workflow file, Sprengel Commentarius inputs, and archive material.
  - Generated `BASELINE_SHA256SUMS.txt`.
- Files/directories affected:
  - `/home/seancoughlin/Projects/tei-maker-data/baseline/20260517-181217`
- Verification result: Snapshot contains 152 files total, with 151 files recorded in `BASELINE_SHA256SUMS.txt`.
- Commit hash: none.
- Open issues or risks: Snapshot intentionally excludes bulky ignored assets such as PDFs, JP2 trees, raw images, and full OCR scratch; those are candidates for Phase B source/externalization manifests and checksum capture.

## 2026-05-17 18:13 Europe/Budapest

- Action taken: Created Phase 0 refactor documents.
- Commands run, summarized:
  - Created `docs/refactor/PLAN.md`.
  - Created `docs/refactor/CHECKLIST.md`.
  - Created `docs/refactor/MIGRATION_MAP.md`.
  - Created `docs/refactor/WORKLOG.md`.
  - Created `docs/refactor/BASELINE.md`.
  - Created `docs/refactor/BASELINE_ARTIFACTS.md`.
- Files/directories affected: `docs/refactor/`.
- Verification result: Pending git status and docs commit.
- Commit hash: pending at time of entry; later committed as `94a9f54`.
- Open issues or risks: First docs commit must stage only `docs/refactor/`.

## 2026-05-17 18:17 Europe/Budapest

- Action taken: Committed Phase 0 documentation checkpoint.
- Commands run, summarized:
  - `git add docs/refactor`
  - `git commit -m "docs(refactor): add migration plan and safety checklist"`
- Files/directories affected: `docs/refactor/`.
- Verification result: Commit created with only Phase 0 planning, baseline, migration map, checklist, worklog, and baseline artifact docs.
- Commit hash: `94a9f54`
- Open issues or risks: Worklog now records this hash in the next docs update because the hash was not known until after the checkpoint commit.

## 2026-05-17 18:20 Europe/Budapest

- Action taken: Added Phase A package skeleton with no pipeline code moves.
- Commands run, summarized:
  - Added `pyproject.toml` and `tei-maker` console entry point.
  - Added `tei_maker/__init__.py`, `tei_maker/__main__.py`, `tei_maker/cli.py`, `tei_maker/config.py`, and `tei_maker/io/paths.py`.
  - Added `.env.example`, unit tests, and `.github/workflows/test.yml`.
- Files/directories affected:
  - `pyproject.toml`
  - `.env.example`
  - `.github/workflows/test.yml`
  - `tei_maker/`
  - `tests/`
- Verification result:
  - `python3 -m compileall tei_maker tests`: pass.
  - `python3 -m unittest discover -s tests`: 8 tests pass.
  - `python3 -m tei_maker --help`: pass.
  - `python3 -m tei_maker run tlg0656.tlg001.berendes1902-ger1`: expected failure with clear `TEI_MAKER_DATA` error.
  - `TEI_MAKER_DATA=/tmp/tei-maker-data python3 -m tei_maker run tlg0656.tlg001.berendes1902-ger1 --from prepare --to validate`: pass as stub.
  - `python3 -m tei_maker validate --all`: pass as static-validation stub without `TEI_MAKER_DATA`.
  - `python3 -m tei_maker data doctor`: pass, reports default root and missing env warning.
  - `python3 -m tei_maker editions export-json --check`: pass as stub.
  - `node --check viewer/app.js`: pass.
- Commit hash: `52253c3`
- Open issues or risks: CLI commands are intentionally stubs in Phase A; behavior wiring remains for later phases.

## 2026-05-17 18:31 Europe/Budapest

- Action taken: Completed first non-destructive Phase B source externalization batch.
- Commands run, summarized:
  - Measured candidate sizes with `du -sh`.
  - Copied source PDFs/XML/JP2 zip into `/home/seancoughlin/Projects/tei-maker-data/sources/<slug>/`.
  - Generated `/home/seancoughlin/Projects/tei-maker-data/sources/SOURCES_SHA256SUMS.txt`.
  - Re-ran repo-side `sha256sum` for copied sources and matched every digest.
  - Added `docs/refactor/SOURCE_MANIFEST_DRAFT.md`.
  - Added `build/audits/` to `.gitignore`.
  - Enhanced `tei-maker data doctor` to report expected external source files.
- Files/directories affected:
  - External: `/home/seancoughlin/Projects/tei-maker-data/sources/`.
  - Repo: `.gitignore`, `tei_maker/cli.py`, `docs/refactor/SOURCE_MANIFEST_DRAFT.md`, `docs/refactor/CHECKLIST.md`, `docs/refactor/WORKLOG.md`.
- Verification result:
  - Source checksums matched between repo and external copies.
  - `python3 -m unittest discover -s tests`: 8 tests pass.
  - `python3 -m compileall tei_maker tests`: pass.
  - `python3 -m tei_maker data doctor`: pass and reports all expected source files present under the default external root.
  - `python3 -m tei_maker run tlg0656.tlg001.berendes1902-ger1`: expected failure without `TEI_MAKER_DATA`.
- Commit hash: `8b2c311`
- Open issues or risks: No repo assets were removed or archived. Full generated tree externalization is deferred because `ocr/` is about 4.0G, `images/` about 660M, and several tracked chunk/OCR fragment trees may contain editorial decisions.

## 2026-05-17 18:35 Europe/Budapest

- Action taken: Recorded Phase B source externalization checkpoint.
- Commands run, summarized:
  - Updated refactor docs after source asset copy.
  - Committed docs-only follow-up.
- Files/directories affected: `docs/refactor/`.
- Verification result: Documentation now points at source checkpoint commit `8b2c311`.
- Commit hash: `7179f6c`
- Open issues or risks: Generated artifact copies were still deferred at this checkpoint.

## 2026-05-17 19:37 Europe/Budapest

- Action taken: Completed conservative Phase B generated artifact copy batch.
- Commands run, summarized:
  - Copied `ocr/` to `/home/seancoughlin/Projects/tei-maker-data/ocr/legacy/`.
  - Copied `images/raw/` and `images/enhanced/` to `/home/seancoughlin/Projects/tei-maker-data/images/tlg0656.tlg001.berendes1902-ger1/`.
  - Copied `editions/beck2020/page_images/` to `/home/seancoughlin/Projects/tei-maker-data/images/tlg0656.tlg001.beck2020-eng1/page_images/`.
  - Copied generated audit/scratch output directories to `/home/seancoughlin/Projects/tei-maker-data/build/audits/<slug>/legacy/`.
  - Generated `OCR_LEGACY_SHA256SUMS.txt`, `IMAGES_SHA256SUMS.txt`, and `AUDITS_SHA256SUMS.txt`.
  - Extended `tei-maker data doctor` to report copied generated paths as warnings if absent.
- Files/directories affected:
  - External: `/home/seancoughlin/Projects/tei-maker-data/ocr/legacy/`, `/home/seancoughlin/Projects/tei-maker-data/images/`, `/home/seancoughlin/Projects/tei-maker-data/build/audits/`.
  - Repo: `tei_maker/cli.py`, `docs/refactor/SOURCE_MANIFEST_DRAFT.md`, `docs/refactor/MIGRATION_MAP.md`, `docs/refactor/CHECKLIST.md`, `docs/refactor/WORKLOG.md`.
- Verification result:
  - External image file count matches copied repo image/page-image sources: 1331 files.
  - External OCR file count is 9411 including the generated checksum manifest; repo OCR source count is 9410 files.
  - External audit file count is 50 copied files plus the generated audit checksum manifest.
  - `python3 -m compileall tei_maker tests`: pass.
  - `python3 -m unittest discover -s tests`: 9 tests pass.
  - `python3 -m tei_maker data doctor`: pass and reports source files plus generated artifact mirrors.
  - `python3 scripts/validate_structure.py output/berendes1902_epidoc.xml`: pass, 0 issues.
  - `node --check viewer/app.js`: pass.
  - `python3 scripts/validate_beck_fresh_diplomatic.py output/beck2020_fresh_diplomatic_epidoc.xml --manifest editions/beck2020_fresh_diplomatic/manifest.json --expected-pdf-pages 711`: pass with known warning `FOOTNOTE_QA_OPEN_BODY_ROWS`.
- Commit hash: pending.
- Open issues or risks: `chunks/`, `sprengel_comm/ocr_fragments/`, and `sprengel_comm/outputs/sprengel_comm_merged.xml` remain committed/source-like until reproducibility and editorial status are proven. No repo copies were removed.
