Archived failed experiment prompt. Do not reuse for production Beck processing.
The full-page Gemini pipeline failed the pilot gate because it was too
expensive, too brittle, and did not improve the builder-led TEI enough to
justify a full run.

You are reading page images from Lily Y. Beck's English translation of
Dioscorides' De materia medica. The image is authoritative. Preserve printed
text, punctuation, capitalization, Greek accents, bibliographic details, and
visible footnote evidence.

Return exactly one JSON object. Do not use markdown fences. Do not return prose
outside the JSON object.

The first image is the PRIMARY page. Transcribe and annotate only the PRIMARY
page. A NEXT_CONTEXT image may follow; use it only to complete or classify a
footnote cut off at the bottom of the PRIMARY page. A PREVIOUS_CONTEXT image may
follow for pages where a footnote may have begun on the previous page; use it
only to identify the source note, not to transcribe previous-page body text.
When PRIMARY_HOCR_WORDS are supplied, use those exact `beck-fresh-p...` word IDs
and bboxes for accepted anchors and accepted annotation spans. Do not invent
`beck-fresh-*` IDs.

The JSON object must contain these keys:

- page_tei_fragment
- footnote_events
- cross_page_continuations
- name_annotations
- bibl_annotations
- text_corrections
- uncertainties

Use this shape:

{
  "page_id": "beck-NNNN",
  "primary_page": N,
  "page_tei_fragment": "<div type=\"page\" n=\"N\" xml:id=\"beck-gemini-page-NNNN\">...</div>",
  "footnote_events": [],
  "cross_page_continuations": [],
  "name_annotations": [],
  "bibl_annotations": [],
  "text_corrections": [],
  "uncertainties": []
}

For page_tei_fragment:

- Emit a single TEI-ish XML fragment string, not a whole TEI document.
- Use single quotes for XML attribute values inside page_tei_fragment, so the
  JSON string stays valid.
- Include <pb n="N"/> at the primary page boundary.
- Use <p> or <ab type="line"> for body text, <head> for visible headings, and
  <lb/> at printed line breaks when the lineation is visible.
- Use <ref type="footnote-ref" target="#NOTE_ID">LABEL</ref> for visible
  footnote anchors.
- Emit visible bottom notes as <note type="footnote" place="bottom"
  xml:id="NOTE_ID" n="LABEL">...</note>.
- If a note continues beyond or from another page, do not silently merge it.
  Also record it in cross_page_continuations with evidence.
- Do not transcribe ordinary body text from context pages.

For footnote_events, include one object for every visible or inferred footnote
anchor/body relationship on the primary page:

{
  "decision": "accepted|uncertain|rejected",
  "ref_xml_id": "beck-fresh-ref-pNNNN-...",
  "note_xml_id": "beck-fresh-gemini-fn-pNNNN-...",
  "n": "printed label",
  "marker_bbox": "left top right bottom",
  "note_bbox": "left top right bottom",
  "anchor_word_id": "beck-fresh-pNNNN-lNNN-wNNN",
  "transcription": "exact note text, if accepted",
  "confidence": "0.00-1.00",
  "evidence": "brief page-image evidence"
}

For cross_page_continuations, include every visible cross-page note state:

{
  "status": "continuing|resolved|uncertain",
  "from_page": N,
  "to_page": N,
  "note_xml_id": "note id if known",
  "n": "printed label if known",
  "evidence": "brief image-backed evidence"
}

For name_annotations:

- Use <name type="scientific"> for exact scientific-name spans.
- Use <name type="common"> for exact common-name spans.
- Add an accepted annotation only when the span is exact by word_ids or bbox.
- If PRIMARY_HOCR_WORDS are present, accepted annotations must use exact
  `beck-fresh-p...` word_ids from that list.
- If no exact word_ids or bbox are available, use decision "uncertain", not
  "accepted".
- Do not invent stable plant, mineral, or animal IDs.

For bibl_annotations:

- Use <bibl> only for exact bibliographic spans.
- Add accepted bibl_annotations only when the span is exact by word_ids or bbox.
- If no exact word_ids or bbox are available, use decision "uncertain", not
  "accepted".
- Use corresp only if the target key appears in the same page fragment or is
  explicitly printed as the same cited work.

For text_corrections:

- Include only image-backed corrections to the existing OCR when exact word_ids
  or bbox evidence is available.
- Use decision "accepted" only when the reading is clear from the page image.
- Accepted text corrections must include exact `beck-fresh-p...` word_ids when
  PRIMARY_HOCR_WORDS are supplied.
- Use decision "uncertain" when the reading should remain in review.

For uncertainties:

- Record uncertain readings, missing spans, ambiguous footnote links, and any
  place where the context image was needed but did not settle the issue.
