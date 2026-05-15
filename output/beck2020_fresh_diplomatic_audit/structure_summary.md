# Beck Fresh Diplomatic Structure Audit

This audit bootstraps the private, image-first diplomatic EpiDoc workflow. The page image remains the authority; `beck.xml` supplies structural alignment evidence only.

## Source Counts

- Fresh manifest pages: 711
- Fresh PDF pages: 711
- Fresh images: 711
- Fresh hOCR files: 711
- Fresh TXT files: 711

## Structure Ledger

- Ledger rows: 851
- `back` rows: 1
- `book` rows: 5
- `chapter` rows: 827
- `front` rows: 1
- `section` rows: 17

## Chapter Counts

- Book 1: 129/129 chapters (ok)
- Book 2: 186/186 chapters (ok)
- Book 3: 158/158 chapters (ok)
- Book 4: 192/192 chapters (ok)
- Book 5: 162/162 chapters (ok)

## Structure Issue Codes

- `duplicate-source-section-id`: 2
- `missing-source-heading`: 1
- `none`: 848

## Footnote Review State

- Accepted link rows: 402
- Accepted transcription rows: 452
- `continuation` QA rows: 1
- `linked` QA rows: 401
- `rejected-sequence-body-text` QA rows: 91
- `unresolved-markers-without-notes` QA rows: 41
- `unresolved-no-marker` QA rows: 184

## Text Correction State

- Low-confidence rows: 5049
- Low-confidence Greek-script rows: 868
- Text correction ledger: `ocr/beck2020_fresh/diplomatic/text_correction_ledger.csv`

## Back Matter Triage

- Triage rows: 278
- `encode-lightly`: 277
- `not-worth-full-modeling`: 1

## Artifacts

- Structure ledger: `ocr/beck2020_fresh/diplomatic/structure_ledger.csv`
- Text correction ledger: `ocr/beck2020_fresh/diplomatic/text_correction_ledger.csv`
- Back-matter triage ledger: `ocr/beck2020_fresh/diplomatic/back_matter_triage_ledger.csv`
