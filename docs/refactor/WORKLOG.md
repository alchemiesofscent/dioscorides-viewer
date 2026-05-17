# Refactor Worklog

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
- Commit hash: pending.
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
- Commit hash: pending.
- Open issues or risks: CLI commands are intentionally stubs in Phase A; behavior wiring remains for later phases.
