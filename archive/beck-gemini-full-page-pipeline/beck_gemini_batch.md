# Beck Fresh Gemini Batch Workflow - Archived Failed Experiment

Do not use this workflow for the Beck fresh diplomatic build. It is preserved
only as an archive of the failed full-page Gemini batch experiment.

Private/local Gemini 2.5 Pro batch workflow for the fresh Beck image stream.
This stays separate from the public edition registry.

## Artifact Layout

The local runtime artifacts live under `ocr/beck2020_fresh/gemini/`:

- `requests/` - local JSONL request files and request manifests.
- `raw_response_text/` - extracted model text from Vertex AI output rows.
- `parsed_responses/` - one structured JSON response per primary page.
- `accepted_ledgers/` - conservative Gemini-derived CSV ledgers consumable by
  `scripts/build_beck_fresh_diplomatic.py`.
- `outputs/` - Gemini-native stitched TEI page-fragment comparison output.
- `usage/` - token/model/status usage CSVs.
- `summaries/` - pilot and full-run summaries.

## Pilot Commands

Build the hard pilot requests after the page images have been uploaded to the
matching Cloud Storage prefix:

```bash
python3 scripts/beck_gemini_batch.py build-requests \
  --gcs-image-prefix gs://YOUR_BUCKET/beck2020_fresh/images \
  --output ocr/beck2020_fresh/gemini/requests/pilot_requests.jsonl \
  --manifest ocr/beck2020_fresh/gemini/requests/pilot_request_manifest.json
```

Validate the local JSONL before upload/submission:

```bash
python3 scripts/beck_gemini_batch.py validate-requests \
  --gcs-image-prefix gs://YOUR_BUCKET/beck2020_fresh/images \
  --expected-count 25 \
  ocr/beck2020_fresh/gemini/requests/pilot_requests.jsonl
```

Optionally write the REST request body for
`projects.locations.batchPredictionJobs.create`:

```bash
python3 scripts/beck_gemini_batch.py write-job-request \
  --input-uri gs://YOUR_BUCKET/beck2020_fresh/requests/pilot_requests.jsonl \
  --output-uri gs://YOUR_BUCKET/beck2020_fresh/output \
  --output ocr/beck2020_fresh/gemini/requests/batch_prediction_job_request.json
```

After downloading Vertex AI batch output JSONL files:

```bash
python3 scripts/beck_gemini_batch.py parse-responses path/to/predictions.jsonl
python3 scripts/beck_gemini_batch.py validate-parsed
python3 scripts/beck_gemini_batch.py stitch-fragments
python3 scripts/beck_gemini_batch.py export-ledgers
python3 scripts/beck_gemini_batch.py summary
```

Then build the builder-led output with accepted Gemini ledgers:

```bash
python3 scripts/build_beck_fresh_diplomatic.py \
  --gemini-ledger-dir ocr/beck2020_fresh/gemini/accepted_ledgers
```

Run the existing structural validator:

```bash
python3 scripts/validate_beck_fresh_diplomatic.py \
  output/beck2020_fresh_diplomatic_epidoc.xml \
  --manifest editions/beck2020_fresh_diplomatic/manifest.json \
  --expected-pdf-pages 711
```
