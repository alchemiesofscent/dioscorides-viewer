# Refactor Baseline

Historical/supporting record. This file records an earlier baseline snapshot and
branch-state audit. It is not the forward refactor plan. Use
`docs/refactor/PLAN.md` for current intent and `docs/refactor/REPO_AUDIT.md`
for the current repository classification.

## Branch and Commit

- Initial observed branch: `main`
- Initial observed commit: `754d9622d4b85bbaaec20d3d4eb4743541b981c9`
- Current refactor branch: `refactor/tei-maker-pipeline`
- Current branch HEAD after approved branch switch: `18fecb1` (`Archive failed Beck Gemini pipeline`)
- Baseline tag on main: `pre-refactor-baseline`
- Working baseline tag: `pre-refactor-working-baseline`

## Git Status

Initial sandbox status before branch creation:

```text
 M scripts/build_beck_fresh_diplomatic.py
?? PLAN-beck-gemini.md
?? docs/beck_gemini_batch.md
?? prompts/beck_gemini_diplomatic_json.md
?? scripts/beck_gemini_batch.py
```

After approved branch creation, current status:

```text
## refactor/tei-maker-pipeline
```

The apparent dirty files are represented in current branch commit `18fecb1` under `archive/beck-gemini-full-page-pipeline/`. No refactor edits were made before this discrepancy was documented.

## Required Command Results

| Command | Result |
| --- | --- |
| `git status --short` | Initially dirty as shown above; current branch clean before docs. |
| `git rev-parse --abbrev-ref HEAD` | `refactor/tei-maker-pipeline` after branch creation. |
| `git rev-parse HEAD` | `18fecb1` after branch creation; initial observed commit was `754d9622d4b85bbaaec20d3d4eb4743541b981c9`. |
| `find . -maxdepth 3 -type d \| sort` | Ran; 356 directories, including `.git`, `.venv`, `chunks`, `editions`, `images`, `ocr`, `output`, `scripts`, `sprengel`, `sprengel_comm`, `tools`, `viewer`. |
| `find . -maxdepth 3 -type f \| sort` | Ran; 3836 files at max depth 3, including ignored source assets and generated outputs. |
| `find . -name "__pycache__" -type d` | Ran; repo caches plus many `.venv` caches found. |
| `find editions -maxdepth 4 -type f \| sort` | Ran; 719 files, mostly ignored Beck page images plus tracked manifests/sidecars. |
| `find output -maxdepth 4 -type f \| sort` | Ran; 56 files, including committed TEI and audit reports. |
| `find scripts -maxdepth 4 -type f \| sort` | Ran; 109 files including tracked scripts and ignored caches. |
| `find ocr chunks chunks_pilot_gate images -maxdepth 3 -type f \| sort` | Ran; 4462 files, including tracked Berendes chunks and ignored OCR/image artifacts. |

## Existing Edition Directories

- `editions/beck2020`
- `editions/beck2020_fresh`
- `editions/beck2020_fresh_diplomatic`
- `editions/sprengel1829`

## Existing TEI Outputs

Committed or visible final/review TEI outputs:

- `output/berendes1902_epidoc.xml`
- `output/sprengel1829_epidoc.xml`
- `output/sprengel_comm_epidoc.xml`
- `output/beck2020_fresh_diplomatic_epidoc.xml`

Ignored/local TEI-like outputs also exist:

- `output/beck2020_epidoc.xml`
- `output/beck2020_fresh_epidoc.xml`
- `editions/sprengel1829/sprengel_diplomatic.xml`
- `sprengel_comm/outputs/sprengel_comm_merged.xml`

## Existing Manifests and Registries

- `editions.json`
- `manifest.json`
- `editions/beck2020/manifest.json`
- `editions/beck2020/private_registry.json`
- `editions/beck2020_fresh/manifest.json`
- `editions/beck2020_fresh/private_registry.json`
- `editions/beck2020_fresh_diplomatic/manifest.json`
- `editions/beck2020_fresh_diplomatic/private_registry.json`
- `editions/sprengel1829/manifest.json`
- `sprengel_comm/manifest.json`
- `ocr/sprengel/b23982500_0002/manifest.json`

## Existing Viewer Entry Points

- `viewer/index.html`
- `viewer/app.js`
- `viewer/styles.css`
- Root `index.html`
- `tools/beck-fresh-footnotes/index.html`
- `tools/beck-fresh-footnotes/app.js`
- `tools/beck-fresh-footnotes/styles.css`

The static viewer currently reads root `editions.json` plus private local registries when present.

## Existing Scripts and Wrappers

Primary script surface:

- Berendes: `run_pipeline.sh`, `scripts/page_map.py`, `scripts/build_manifest.py`, `scripts/extract_scaffold.py`, `scripts/extract_xml_text.py`, `scripts/run_codex.py`, `scripts/merge_chunks.py`, `scripts/validate_structure.py`, normalization and audit scripts.
- Sprengel base/commentary: `scripts/sprengel/*.py` plus compatibility wrappers at `scripts/build_sprengel_*.py`, `scripts/audit_sprengel_*.py`, and `scripts/ocr_sprengel_jp2_zip.py`.
- Beck: `scripts/build_beck_epidoc.py`, `scripts/ocr_beck_pages.py`, `scripts/ocr_beck_fresh_pilot.py`, `scripts/build_beck_fresh_diplomatic.py`, `scripts/validate_beck_fresh.py`, `scripts/validate_beck_fresh_diplomatic.py`, and related correction/review scripts.
- Root OCR helpers: `gemini_ocr.py`, `vision_ocr.py`.

## Source Assets and Generated Artifacts

Likely source assets:

- `berendes1902__z3.pdf`
- `berendes (1).xml`
- `beck.pdf`
- `beck.xml`
- `tlg0656001.xml` through `tlg0656004.xml`
- `b23982500_0002_jp2.zip`
- `sprengel/`

Likely generated artifacts:

- `ocr/`
- `images/raw/`
- `images/enhanced/`
- `editions/beck2020/page_images/`
- `chunks_pilot_gate/`
- `output/*_audit/`
- `output/beck_text_cleaning/`
- `output/beck_footnote_audit/`
- `__pycache__/`
- `.pytest_cache/` if present

Likely hand-curated/editorial artifacts:

- `chunks/` normalized Berendes TEI chunks.
- `sprengel_comm/sprengel_chapter_table.tsv`.
- `editions/sprengel1829/page_headers.csv`.
- `ocr/beck2020_fresh/diplomatic/*.csv` correction/structure ledgers.
- Prompt files under `prompts/`.

These must not be hidden in unversioned external storage without explicit review.

## Existing Tests and CI

- Existing CI: `.github/workflows/pages.yml` for GitHub Pages deployment.
- No `pyproject.toml`, `pytest.ini`, `setup.cfg`, `tox.ini`, requirements file, or package metadata found.
- No formal test suite detected.
- Existing validation is script-based.

## Baseline Validation Results

- `python3 scripts/validate_structure.py output/berendes1902_epidoc.xml`: pass, 0 issues.
- `node --check viewer/app.js`: pass.
- `python3 scripts/validate_beck_fresh_diplomatic.py output/beck2020_fresh_diplomatic_epidoc.xml --manifest editions/beck2020_fresh_diplomatic/manifest.json --expected-pdf-pages 711`: pass with 0 errors and 1 warning: `FOOTNOTE_QA_OPEN_BODY_ROWS: 101 unresolved QA rows outside triaged back matter`.
- `python3 scripts/build_sprengel_comm_epidoc.py --source sprengel_comm/outputs/sprengel_comm_merged.xml --chapter-table sprengel_comm/sprengel_chapter_table.tsv --output /tmp/tei-maker-sprengel-comm-baseline.xml`: pass; wrote 328 pages and reported expected unmatched chapter headings.
- `python3 -m pytest`: baseline failure, `/usr/bin/python3: No module named pytest`.

## Known Baseline Risks

- The initial sandbox branch/status did not match the post-branch git state; current branch contains a pre-existing archive commit.
- Several ignored local source assets and generated trees are not covered by the baseline snapshot yet.
- `chunks/`, Sprengel page headers, Commentarius chapter tables, and Beck diplomatic ledgers likely contain editorial decisions.
- Current final TEI is under `output/`, not edition slug folders.
- Viewer registry is root `editions.json`, not generated from `editions/editions.toml`.
- Existing validation does not include schema-backed EpiDoc checks.
