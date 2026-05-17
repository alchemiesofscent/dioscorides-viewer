# Repository Audit

Audit date: 2026-05-17 20:21 CEST.

This audit supports `docs/refactor/PLAN.md`. It is a current path-group account
for the documentation-reset checkpoint. It does not authorize moves or cleanup.

## Commands Recorded

```bash
git status --short
git status --ignored --short
git rev-parse --abbrev-ref HEAD
git rev-parse --short HEAD
git ls-files | wc -l
find . -maxdepth 2 -type d | sort
du -sh ./* ./.??* 2>/dev/null | sort -hr
git ls-files docs/refactor README.md | sort
```

## Snapshot

- Branch: `refactor/tei-maker-pipeline`.
- HEAD before docs reset: `48c8653`.
- `git status --short`: clean before edits.
- Tracked files: 578.
- Large ignored/raw trees visible in this checkout include `ocr/` about 4.0G,
  `images/` about 660M, `sprengel/` about 534M, `b23982500_0002_jp2.zip` about
  330M, `berendes1902__z3.pdf` about 307M, and `beck.pdf` about 66M.

## Classification Terms

- scholarly TEI output
- raw source
- editorial/source-like input
- manifest/registry
- viewer UI
- local review UI
- reusable pipeline code
- generated intermediate
- audit/provenance
- obsolete process artifact

## Path Groups

| Path group | Tracked/ignored status | Approx. size | Classification | Decision | Notes |
| --- | --- | ---: | --- | --- | --- |
| `README.md` | tracked | 8K before rewrite | audit/provenance | preserve | Project entry point; reset around scholarly TEI outputs. |
| `docs/refactor/` | tracked | 80K before rewrite | audit/provenance | preserve | Forward plan, audit, path ledger, source manifest, and worklog. |
| `docs/` outside `refactor/` | tracked | included in docs size | audit/provenance | preserve | Existing ingest/private Beck docs remain supporting docs. |
| `output/berendes1902_epidoc.xml` | tracked | part of `output/` 63M | scholarly TEI output | preserve | Public viewer XML and regression baseline. |
| `output/sprengel1829_epidoc.xml` | tracked | part of `output/` 63M | scholarly TEI output | preserve | Sprengel base viewer XML and regression baseline. |
| `output/sprengel_comm_epidoc.xml` | tracked | part of `output/` 63M | scholarly TEI output | preserve | Commentarius viewer XML and regression baseline. |
| `output/beck2020_fresh_diplomatic_epidoc.xml` | tracked | part of `output/` 63M | scholarly TEI output | preserve | Private/local diplomatic review XML. |
| `output/beck2020_epidoc.xml`, `output/beck2020_fresh_epidoc.xml` | ignored | part of `output/` 63M | scholarly TEI output | preserve pending audit | Older/local Beck outputs; do not delete without replacement. |
| `output/*_audit/` | tracked/mixed | part of `output/` 63M | audit/provenance | preserve pending classification | Some ledgers support current TEI decisions. |
| `manifest.json` | tracked | 220K | manifest/registry | preserve | Berendes current manifest. |
| `editions.json` | tracked | 4K | manifest/registry | preserve | Current public viewer registry. |
| `editions/sprengel1829/` | tracked | part of `editions/` 190M | editorial/source-like input, manifest/registry, audit/provenance | preserve | Manifest, diplomatic XML, and page headers support Sprengel output. |
| `editions/beck2020*/` manifests/registries | tracked | part of `editions/` 190M | manifest/registry, local review UI | preserve pending audit | Private/local Beck streams. |
| `editions/beck2020/page_images/` | ignored | part of `editions/` 190M | raw source/generated intermediate | externalize/preserve until checksummed | Local page image cache, not public repo data. |
| `chunks/` | tracked with a few ignored prompt/log files | 3.0M | editorial/source-like input | preserve | Normalized Berendes chunk source, not disposable. |
| `chunks_pilot_gate/` | ignored | 48K | generated intermediate | archive/remove after audit | Pilot scratch candidate. |
| `sprengel_comm/` | mostly tracked; `page_images/` ignored | 3.9M plus ignored images | editorial/source-like input, manifest/registry, generated intermediate | preserve | OCR fragments and merged XML are source-like until reproducibility is proven. |
| `viewer/` | tracked | 92K | viewer UI | preserve | Static viewer remains first-class. |
| `tools/beck-fresh-footnotes/` | tracked | 48K | local review UI | preserve | Diagnostic review surface; not required by public viewer. |
| `scripts/` | tracked with ignored caches | 2.2M | reusable pipeline code | preserve/refactor later | Current builders, audits, OCR helpers, and wrappers. |
| `tei_maker/` | tracked with ignored caches | 76K | reusable pipeline code | preserve/extend later | Package skeleton and shared helpers. |
| `tests/` | tracked with ignored caches | 36K | reusable pipeline code | preserve | Current unit tests. |
| `prompts/` | tracked | 16K | editorial/source-like input | preserve | TEI header and model prompt material. |
| `archive/beck-gemini-full-page-pipeline/` | tracked with ignored cache | 144K | obsolete process artifact, audit/provenance | preserve as archive | Failed Beck Gemini pipeline already archived. |
| `ocr/` | ignored/mixed | 4.0G | generated intermediate, audit/provenance | externalize; preserve until audited | Large OCR and ledgers; some subtrees may encode accepted decisions. |
| `images/` | ignored | 660M | raw source/generated intermediate | externalize; preserve until audited | Raw/enhanced page image cache. |
| `sprengel/` | ignored | 534M | raw source | externalize; preserve until checksummed | Extracted JP2 tree, likely reproducible from zip. |
| `b23982500_0002_jp2.zip` | ignored | 330M | raw source | externalize; preserve until checksummed | Sprengel Commentarius source zip. |
| `berendes1902__z3.pdf` | ignored | 307M | raw source | externalize; preserve until checksummed | Berendes source PDF. |
| `beck.pdf` | ignored | 66M | raw source | externalize; preserve until checksummed | Private/local Beck source PDF. |
| `beck.xml` | ignored | 13M | raw source | externalize; preserve until checksummed | Private/local Beck comparison XML. |
| `tlg0656001.xml` through `tlg0656004.xml` | ignored | about 2.0M total | raw source | externalize; preserve until checksummed | Sprengel source XML files. |
| `berendes (1).xml` | tracked | 2.5M | editorial/source-like input | preserve | Source XML currently tracked. |
| `.github/` | tracked | 16K | audit/provenance | preserve | CI/deploy workflows. |
| `.venv/` | ignored | 40M | obsolete process artifact | remove only as local cleanup | Local environment, not repo artifact. |
| `__pycache__/`, `*/__pycache__/`, `.pytest_cache/` | ignored | 52K plus nested caches | obsolete process artifact | remove after audit or local cleanup | Disposable caches. |
| `.env` | ignored | 4K | raw/private config | preserve locally, never commit | Secret-bearing local config. |
| root `PLAN.md` and `BECK_PLAN.md` | tracked | 16K and 8K | audit/provenance | preserve pending doc audit | Historical/specialized planning docs outside current refactor authority. |
| `LICENSE`, `LICENSE-DATA.md`, `NOTICE.md`, `CITATION.cff` | tracked | small | audit/provenance | preserve | Legal/citation metadata. |

## Immediate Decisions

- Preserve all generated/review-grade TEI XMLs.
- Keep viewer files in place during this documentation checkpoint.
- Keep raw/source assets in place until checksum manifests and external copies
  are verified for the current desired storage boundary.
- Treat `chunks/`, Sprengel page-header sidecars, Commentarius chapter tables,
  Commentarius OCR XML/fragments, and Beck accepted ledgers as source-like or
  provenance-bearing material.
- Treat caches, temporary crops, old visual pass outputs, failed experiment
  outputs, and duplicated scratch as cleanup candidates only after a recorded
  audit.
