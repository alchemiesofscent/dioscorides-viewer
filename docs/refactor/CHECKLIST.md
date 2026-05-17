# Refactor Checklist

This checklist is derived from `docs/refactor/PLAN.md`. It is an execution aid,
not a competing plan.

## Phase 1: Documentation Reset

- [x] Confirm current git status before edits.
- [x] Review existing README and refactor docs.
- [x] Run inventory commands needed for `REPO_AUDIT.md`.
- [x] Rewrite `README.md` around scholarly EpiDoc outputs, viewer use, pipeline
  direction, and external raw data.
- [x] Rewrite `docs/refactor/PLAN.md` as the single authoritative forward plan.
- [x] Add `docs/refactor/REPO_AUDIT.md`.
- [x] Rewrite `docs/refactor/MIGRATION_MAP.md` as a path ledger only.
- [x] Rewrite `docs/refactor/SOURCE_MANIFEST_DRAFT.md` as an external
  raw/source manifest only.
- [x] Add historical/supporting notices to baseline docs.
- [x] Update `docs/refactor/WORKLOG.md`.
- [x] Run docs/package checks.
- [x] Commit docs-only checkpoint.

## Standing Protocol Before Each Later Phase

- [ ] Record `git status --short`.
- [ ] Record relevant `git status --ignored --short`.
- [ ] Record relevant `find`, `du`, and `git ls-files` inventories.
- [ ] Record current validation commands for affected TEI/viewer surfaces.
- [ ] Update `WORKLOG.md` before or alongside implementation.
- [ ] Record command failures and response decisions.

## Phase 3: Preserve Scholarly TEI Outputs

- [x] Inventory Berendes TEI and manifest.
- [x] Inventory Sprengel base TEI, manifest, source-like sidecars, and audits.
- [x] Inventory Sprengel Commentarius TEI, manifest, OCR XML/fragments, chapter
  table, and audits.
- [x] Inventory Beck generated TEI variants, manifests, accepted ledgers, and
  review outputs.
- [x] Identify pilot TEI not represented in later outputs.
- [x] Verify no TEI output is deleted.
- [x] Move TEI later with `git mv` only after this inventory is committed.

## Phase 4: External Raw Data Boundary

- [ ] Confirm or create shared external raw-data root.
- [ ] Record source PDFs, images, JP2 files, TLG/First1KGreek XML, and
  private/local XML.
- [ ] Capture checksums for every copied source.
- [ ] Record source/license notes and required/optional status.
- [ ] Record whether each repo copy remains, is ignored, or is later removed.
- [ ] Do not delete raw sources until manifest and checksum verification are
  complete.

## Phase 5: Viewer Stability

- [x] Verify current registry and manifest paths.
- [x] Run `node --check viewer/app.js`.
- [x] Serve from repo root when paths or registry behavior changes.
- [x] Confirm public editions do not require private raw data.
- [x] Document private/local registry behavior.

## Phase 6: Reusable Pipeline Extraction

- [ ] Identify shared path/config logic.
- [x] Identify edition registry helpers.
- [ ] Identify page/image inventory logic.
- [ ] Identify OCR evidence readers.
- [ ] Identify TEI writer utilities.
- [ ] Identify manifest writer logic.
- [x] Identify validation/report helpers.
- [ ] Move code in small groups with wrappers preserved until replacement CLI
  commands pass equivalent checks.

## Phase 7: Cleanup And Retirement

- [ ] Classify cleanup candidates before removal.
- [ ] Archive uncertain material rather than deleting it.
- [ ] Preserve generated TEI, manifests, source-like sidecars, accepted review
  decisions, and provenance by default.
- [ ] Record every retirement in `WORKLOG.md`.

## Phase 8: Acceptance

- [ ] README explains the project goal.
- [ ] `PLAN.md` is the single forward plan.
- [ ] `REPO_AUDIT.md` accounts for repo contents.
- [ ] `WORKLOG.md` records every phase.
- [ ] No generated TEI XML is deleted.
- [ ] Viewer remains usable.
- [ ] Raw data boundary is documented with checksums.
- [ ] Pipeline refactor proceeds only from documented inventory and validation.
