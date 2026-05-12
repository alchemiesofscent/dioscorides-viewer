# Beck 2020 Fresh OCR Footnote Plan

## Revision Information

- Created: 2026-05-11 09:08:52 CEST +0200
- Current revision: 2026-05-11 09:08:52 CEST +0200
- Revision note: Initial saved Beck-specific plan for rule-first, image-first
  footnote detection and autonomous visual correction.
- Maintainer note: Future edits to this document should update the current
  revision timestamp and add a short revision note.

## Purpose

Build the Beck fresh-OCR footnote correction workflow around page-image evidence,
not around OCR marker guesses. The page image is authoritative. hOCR boxes,
OCR text, and model output are evidence layers that must remain replayable
through sidecars before the TEI is rebuilt.

The current fresh stream is:

- PDF source: `beck.pdf`
- Rendered page images: `ocr/beck2020_fresh/images/beck-0001.png` through `beck-0711.png`
- hOCR/text/TSV: `ocr/beck2020_fresh/`
- Generated TEI: `output/beck2020_fresh_epidoc.xml`
- Manifest: `editions/beck2020_fresh/manifest.json`
- Footnote queue: `ocr/beck2020_fresh/review/footnote_review_queue.json`

Do not use `beck.xml` or old Beck generated output as a correction baseline.

## Core Footnote Method

For each page, use this order of operations:

1. Look for a horizontal rule or separator near the lower part of the page.
2. If the rule exists, treat text below it as the candidate footnote zone.
3. Read the note label(s) from the image below the rule.
4. Extract the bottom note block(s), even when Tesseract reads note label `1`
   as `!`, `|`, or other OCR noise.
5. For each visible bottom note label `n`, search upward in the main page text
   for the corresponding superscript/start marker.
6. If the anchor is not above the note on the same page, inspect the previous
   page image for a cross-page anchor.
7. If hOCR marker candidates exist, treat them as suggestions only. They are
   not the complete set of possible anchors.
8. If the true superscript is visible in the image but missing from hOCR marker
   candidates, create a model-proposed virtual ref with a stable `ref_xml_id`
   and `marker_bbox`.
9. Do not force uncertain links. Keep low-confidence cases unresolved with
   image/model evidence.

## Sidecar Outputs

All accepted changes must be replayable from CSV sidecars:

- `accepted_footnote_links.csv`
  - Accepted marker-to-note links.
  - Includes `page`, `ref_xml_id`, `note_xml_id`, `n`, `marker_bbox`,
    `note_bbox`, `confidence`, `method`, `reviewer`.
- `accepted_footnote_blocks.csv`
  - Accepted bottom-note blocks that heuristics missed.
  - Includes `page`, `note_xml_id`, `n`, `note_bbox`, `first_line`,
    `last_line`, `confidence`, `method`, `reviewer`.
- `rejected_footnote_candidates.csv`
  - False marker candidates and intentionally rejected detections.

The fresh TEI builder must consume sidecars before applying heuristics:

1. Accepted note blocks override missing or weak note-block detection.
2. Accepted links override marker heuristics.
3. Rejected refs are skipped.
4. Deterministic high-confidence links may still be applied.
5. Unresolved cases remain explicit evidence rows, not silent guesses.

## Autonomous Visual Pass

Use `scripts/run_beck_fresh_footnote_visual_pass.py` as the Berendes-style
image-first model runner.

For each queued row, it should generate:

- Full page overview panel.
- Zoomed marker/body crop.
- Zoomed bottom-note crop.
- Overlay colors:
  - Red: hOCR marker candidates.
  - Gold: detected bottom-note blocks.
  - Green: hOCR separator/horizontal rules.
- Prompt containing:
  - The visual panel.
  - The full 300dpi page image.
  - The previous page image when available.
  - hOCR lines near candidate markers and note blocks.
  - bottom-zone hOCR lines.
  - separator boxes.
  - current TEI state for that page.

The model must return one structured JSON object:

```json
{
  "decision": "accept_link | reject_marker | propose_note_block | unresolved",
  "page": 0,
  "ref_xml_id": "",
  "note_xml_id": "",
  "n": "",
  "marker_bbox": "",
  "note_bbox": "",
  "first_line": "",
  "last_line": "",
  "confidence": 0.0,
  "evidence": ""
}
```

Decision rules:

- `accept_link`: use when image evidence clearly connects a superscript/start
  marker to a bottom note.
- `reject_marker`: use when a candidate is punctuation, possessive, quotation,
  or otherwise not a footnote marker.
- `propose_note_block`: use when the image clearly shows a bottom note block
  that hOCR/heuristics missed.
- `unresolved`: use when the image evidence is insufficient.

If a visually clear superscript is missing from hOCR marker candidates, use the
suggested virtual ref ID and include `marker_bbox`; the TEI builder will attach
the ref to the nearest word by bbox.

## Full Run Procedure

Regenerate the queue:

```bash
python3 scripts/build_beck_fresh_footnote_review.py
```

Run a small pilot after prompt or schema changes:

```bash
python3 scripts/run_beck_fresh_footnote_visual_pass.py \
  --pages 2,23 \
  --limit 2 \
  --run-codex \
  --apply-high-confidence \
  --max-parallel 2 \
  --resume
```

Run all queued rows, accuracy-first and resumable:

```bash
python3 scripts/run_beck_fresh_footnote_visual_pass.py \
  --run-codex \
  --apply-high-confidence \
  --max-parallel 4 \
  --resume
```

Only apply model decisions with `confidence >= 0.85`. Completed response JSON
files under `ocr/beck2020_fresh/review/visual_pass/responses/` are reusable;
do not delete them during a resume.

After the visual pass, rebuild the fresh TEI:

```bash
python3 scripts/ocr_beck_fresh_pilot.py --pdf beck.pdf --all-pages
```

Then regenerate the queue and repeat only if newly accepted note blocks create
new linkable rows:

```bash
python3 scripts/build_beck_fresh_footnote_review.py
```

Stop when a cycle adds no high-confidence sidecar rows or after three cycles.

## Validation

Run:

```bash
python3 scripts/validate_beck_fresh.py \
  output/beck2020_fresh_epidoc.xml \
  --manifest editions/beck2020_fresh/manifest.json \
  --expected-pdf-pages 711
```

Also run:

```bash
node --check viewer/app.js
node --check tools/beck-fresh-footnotes/app.js
python3 -m py_compile \
  scripts/ocr_beck_fresh_pilot.py \
  scripts/build_beck_fresh_footnote_review.py \
  scripts/run_beck_fresh_footnote_visual_pass.py \
  scripts/validate_beck_fresh.py
```

Acceptance criteria:

- TEI parses and has 711 page breaks.
- All `xml:id` values are unique.
- All `target` and `corresp` values resolve.
- Every linked footnote has `n`, `place="bottom"`, matching `target`/`corresp`,
  and stable IDs.
- Footnote body text does not leak into main page body text.
- Remaining uncertain cases are explicit queue/proposal rows, not hidden guesses.

## Current Known Lessons

- Page 20 / printed xvi: the visible superscript after `senses:` was not a
  normal hOCR marker candidate; the bottom note label `1` was OCRed as `!`.
  The workflow must allow image-derived virtual refs and OCR-noisy note labels.
- Page 23: the model saw a likely superscript not present in marker candidates.
  This confirms that hOCR marker candidates are only suggestions.
- Page 2: a candidate in `Dioscorides'` was correctly rejected as a possessive
  apostrophe, not a footnote marker.
