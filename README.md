# TEI Maker

`tei-maker` produces scholarly TEI/EpiDoc XML editions for Dioscorides and
related review streams. The committed XML is a corpus asset, a regression
baseline, and the data source for the static viewer.

The repo currently has three jobs:

- preserve generated and review-grade EpiDoc TEI outputs for scholarly use;
- provide a dependency-free viewer for inspecting TEI against page images and
  manifests;
- refactor the existing edition-specific scripts into a reusable
  image/source-to-diplomatic-EpiDoc pipeline.

Raw source assets stay outside git in shared external storage. That includes
PDFs, extracted page images, JP2 files, TLG/First1KGreek XML, private/local
source XML, and bulky OCR or image intermediates. The repo records where those
assets live and how they were checksummed, but it does not treat them as public
redistributable files.

## Current Scholarly Outputs

Preserve these generated TEI outputs unless a validated replacement exists and
the retirement is explicitly recorded in `docs/refactor/WORKLOG.md`:

- `editions/berendes1902/tei/edition.xml` - Berendes 1902 German translation.
- `editions/sprengel1829/tei/edition.xml` - Sprengel 1829/1830 Greek/Latin base text.
- `editions/sprengel1830-comm/tei/edition.xml` - Sprengel 1830 Commentarius.
- `editions/beck2020_fresh_diplomatic/tei/edition.xml` - Beck 2020 private/local
  diplomatic review output.

Related manifests, registries, source-like sidecars, accepted review decisions,
and provenance ledgers are also preservation candidates. Cleanup work must
distinguish disposable process artifacts from scholarly outputs.

## Open The Viewer

Serve the repo root:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/viewer/
```

The public viewer reads `editions/editions.json` and committed TEI/manifests. On
localhost it can also load documented private registries, such as Beck review
registries, when the corresponding local files are present. Public editions must
not require private raw data.

The Beck fresh footnote review surface is available locally at:

```text
http://localhost:8000/tools/beck-fresh-footnotes/
```

## Repository Map

- `viewer/` - static TEI/image inspection viewer.
- `tools/` - local review surfaces.
- `editions/editions.json` - generated public viewer registry.
- `editions/` - edition manifests and committed source-like sidecars.
- `output/` - committed audit outputs and legacy local generated outputs.
- `chunks/` - normalized Berendes TEI chunk source.
- `sprengel_comm/` - Commentarius OCR fragments, merged XML, and authority
  tables.
- `scripts/` - current edition builders, OCR helpers, audits, and wrappers.
- `tei_maker/` - reusable package skeleton and shared helpers being expanded.
- `prompts/` - TEI header and model prompt material.
- `docs/refactor/` - authoritative refactor plan, audit, path ledger, source
  manifest draft, and worklog.

## Refactor Authority

`docs/refactor/PLAN.md` is the single forward plan for the reorganization. Older
baseline and artifact documents are historical/supporting records. Every
implementation phase must update `docs/refactor/WORKLOG.md` with objective,
commands, files touched, verification, and deferred risks.

No path migration or cleanup should happen before the current documentation
checkpoint is committed.

## Validation

Core package/docs checks:

```bash
python3 -m compileall tei_maker tests
python3 -m unittest discover -s tests
python3 -m tei_maker data doctor
python3 -m tei_maker editions export-json --check
python3 -m tei_maker validate --all
```

Viewer check:

```bash
node --check viewer/app.js
```

Current TEI/viewer validation examples:

```bash
python3 scripts/validate_structure.py editions/berendes1902/tei/edition.xml
python3 scripts/validate_beck_fresh_diplomatic.py \
  editions/beck2020_fresh_diplomatic/tei/edition.xml \
  --manifest editions/beck2020_fresh_diplomatic/manifest.json \
  --expected-pdf-pages 711
python3 scripts/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output /tmp/tei-maker-sprengel-comm-baseline.xml
```

## Licenses

- Viewer and processing scripts: MIT (`LICENSE`).
- TEI/data/docs: Creative Commons Attribution-NonCommercial 4.0 International
  (`LICENSE-DATA.md`).
- External facsimile images and private/local sources are not bundled or
  relicensed here; see `NOTICE.md`.
