# Beck Full-Page Gemini Pipeline - Archived Failed Experiment

Status: archived. Do not pursue this route for the Beck fresh diplomatic TEI.

## What We Tried

We implemented a private/local Vertex AI Gemini 2.5 Pro batch layer for the
fresh Beck image stream at `ocr/beck2020_fresh/images/beck-0001.png` through
`beck-0711.png`.

The experiment built Cloud Storage JSONL requests where each primary page sent
Gemini the page image plus continuation context from the next page. The model
was asked to return strict JSON with these fields:

- `page_tei_fragment`
- `footnote_events`
- `cross_page_continuations`
- `name_annotations`
- `bibl_annotations`
- `text_corrections`
- `uncertainties`

The plan had two outputs:

- a builder-led diplomatic TEI enriched only from accepted ledgers;
- a Gemini-native stitched page-fragment sidecar for comparison.

The hard pilot pages were:

`11, 20, 21, 33, 38, 40, 43, 45, 54, 58, 80, 95, 279, 351, 353, 402, 434, 502, 504, 508, 624, 650, 709, 710, 711`.

## What Ran

Two Vertex AI batch jobs were submitted and completed:

- `beck2020-fresh-gemini-pilot`
- `beck2020-fresh-gemini-pilot-v2`

The first pilot used page images and a structured JSON prompt. The second pilot
added hOCR word/bbox context to force exact span anchoring.

Runtime artifacts were written under ignored local paths:

- `ocr/beck2020_fresh/gemini/requests/`
- `ocr/beck2020_fresh/gemini/raw_responses*/`
- `ocr/beck2020_fresh/gemini/parsed_responses*/`
- `ocr/beck2020_fresh/gemini/accepted_ledgers*/`
- `ocr/beck2020_fresh/gemini/outputs/`
- `ocr/beck2020_fresh/gemini/usage/`
- `ocr/beck2020_fresh/gemini/summaries/`

## Results

Pilot v1:

- Parsed pages: 25/25 after local JSON-repair handling.
- Token use: 342,772 total tokens for 25 pages.
- Finish reasons: 25 `STOP`.
- The output failed the pilot gate because many accepted-looking annotations
  lacked exact hOCR word IDs or bboxes.
- Conservative export produced almost no useful builder input.

Pilot v2:

- Added hOCR context.
- Parsed pages: 20/25.
- Five pages ended with `MAX_TOKENS`.
- Token use: 1,173,336 total tokens for 25 pages.
- The permissive accepted ledgers caused TEI validation failures:
  - 8 unresolved target/corresp refs;
  - 8 accepted footnote rows missing from TEI;
  - chapter-head tagging regressions.
- Tightened ledger export removed unsafe rows, but that also removed the main
  expected benefit: no new usable footnote links and no usable text corrections
  remained for the builder-led TEI.

The Gemini-native sidecar could be stitched for parsed pages, but it was not a
production TEI output. It was useful only as comparison evidence.

## Why It Failed

The failure was not a single bug. The approach is mismatched to the task.

Full-page JSON generation is too broad. Gemini was asked to read the page,
reconstruct diplomatic text, identify footnotes, tag names and bibliography,
detect corrections, track cross-page continuation, and emit TEI-like XML inside
JSON in one request. That overloaded the response and made strict structural
compliance unreliable.

The hOCR context solved one problem while creating another. Adding word IDs and
bboxes improved span evidence, but it made prompts extremely large. The v2 pilot
averaged about 46,933 total tokens per page and hit `MAX_TOKENS` on 5 of 25
pages. Scaling that to 711 pages would be expensive and would still produce
malformed or incomplete pages.

The model duplicated already-reviewed footnote work. Some Gemini footnote links
matched pages and note numbers that were already present in the hand-reviewed
ledgers, but with different ref IDs. When consumed by the builder, those rows
created duplicate refs and orphaned targets rather than improving unresolved
footnotes.

The accepted/uncertain boundary was weak. Gemini often marked rows as accepted
while omitting exact spans, replacement surfaces, or builder-resolvable IDs. A
strict exporter had to discard those rows. Once discarded, the remaining output
did not materially improve the unresolved-footnote baseline.

The output shape fights the builder. The reliable source of truth in this repo
is page-first hOCR plus curated sidecar ledgers. A full-page model-generated TEI
fragment is a competing reconstruction. It is useful for visual comparison, but
not safe to merge into the diplomatic TEI without heavy adjudication.

## Decision

Do not run a full 711-page Gemini batch for Beck.

Do not wire Gemini full-page ledgers into `scripts/build_beck_fresh_diplomatic.py`.

Do not treat Gemini-native page fragments as source TEI.

The only viable future use of Gemini here would be a different workflow:

- cropped image regions, not full pages;
- unresolved footnote cases only;
- one narrow question per request;
- exact hOCR word ID/bbox required before any row is accepted;
- all ambiguous output stays in review ledgers, never directly in TEI.

That would be a new targeted adjudication workflow, not a continuation of this
archived full-page pipeline.
