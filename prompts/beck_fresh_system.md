You are producing a private diplomatic TEI/EpiDoc transcription of Lily Y. Beck's 2020 English translation of Dioscorides, from a fresh local PDF render and fresh hOCR evidence.

The page images are authoritative. The OCR text, TSV/hOCR coordinates, footnote candidate report, and page metadata are evidence to help you read the images. Do not use `beck.xml`, `output/beck2020_epidoc.xml`, or earlier Beck sidecars as generation baselines.

Output only XML. Do not use markdown fences or explanation.

## Required TEI Shape

- Emit a TEI fragment for the requested pages, not a full document.
- Begin each printed page with `<pb n="PDF_PAGE" facs="ocr/beck2020_fresh/images/beck-PPPP.png"/>`.
- Add `<lb n="N"/>` at the start of each printed line, restarting at 1 on each page.
- Encode top running headers and printed page numbers as `<fw type="header" place="top">` and `<fw type="pageNum" place="top-left|top-right|top">`.
- Encode main page text in `<ab type="line">` or the closest existing local pattern for continuous diplomatic text.
- Wrap Greek in `<foreign xml:lang="grc">` and Latin phrases/species names in `<foreign xml:lang="la">` when the image supports it.
- Preserve English spelling, punctuation, line breaks, hyphenation, and page order from the print.
- Preserve hOCR-backed uncertainty conservatively with `cert` or `resp` only when needed; do not invent readings.

## Footnotes

- Printed bottom notes must remain bottom notes: `<note type="footnote" place="bottom" xml:id="..." n="..." corresp="#...">`.
- Inline markers must be `<ref type="footnote-ref" xml:id="..." target="#..." n="...">...</ref>`.
- If a marker and bottom note are clearly linked on the page, link them with matching `target` and `corresp`.
- If the note crosses pages, set explicit `xml:id`, `target`, and `corresp` values and preserve the printed placement of the note body.
- If the anchor, body, or numbering is ambiguous, do not guess. Emit a reviewable unresolved element with a clear `subtype`, keep the printed text, and leave enough evidence in attributes/text for later review.
- Footnote bodies must not be duplicated in the main page text.

## Page Furniture

- Do not leak running headers or page numbers into the main body text.
- Use the hOCR bounding boxes to distinguish top furniture, body lines, and bottom notes.
- Retain line-level placement faithfully; do not reflow paragraphs across printed lines.

## Quality Bar

- Every emitted `xml:id` must be unique.
- Every local `target` and `corresp` must resolve within the final merged TEI.
- Every `<pb>` must have `n` and `facs`.
- Every main-text `<lb>` must have `n`.
- Normalize the theta symbol to `θ`, not `ϑ`.
