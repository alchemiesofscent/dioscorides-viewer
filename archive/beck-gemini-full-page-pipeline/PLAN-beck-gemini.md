# Beck Dioscorides - Gemini 2.5 Pro Pipeline Plan

Archived with the failed full-page Gemini pipeline. Do not pursue this plan as
written. It assumed an absent 728-JP2 source set and proposed a full-page
Gemini TEI route that the later 25-page pilots showed to be too expensive,
too brittle, and insufficiently reliable for builder-led Beck TEI production.

## Source Material

- **Images**: 728 JP2 files (`b23982500_0002_jp2/`), 1569×2885 px, ~0.5 MB each, 331 MB total. Wellcome Library scans.
- **Identifications spreadsheet**: `Beck-Dioscorides-Identifications.xlsx` — 1214 botanical IDs (binomial + authority), 147 minerals, 155 animals. Keyed by book.chapter.
- **Reference output**: AI Studio sample (shown below) demonstrates Gemini 2.5 Pro can already produce structured TEI from single page images with `<bibl>`, `<note>`, `<ref>` markup.

## Architecture Overview

```
  JP2 images (728 pages)
        │
        ▼
  ┌─────────────────────┐
  │ Phase 1: Convert     │  JP2 → PNG (ImageMagick)
  └─────────────────────┘
        │
        ▼
  ┌─────────────────────┐
  │ Phase 2: Gemini API  │  Sliding window (pages N, N+1)
  │ (Vertex AI Batch)    │  System prompt + 2 images → TEI fragment
  └─────────────────────┘
        │
        ▼
  ┌─────────────────────┐
  │ Phase 3: Stitch      │  Merge overlapping windows
  │                      │  Resolve cross-page footnotes
  └─────────────────────┘
        │
        ▼
  ┌─────────────────────┐
  │ Phase 4: Enrich      │  Scientific names ← spreadsheet
  │                      │  Bibliography dedup
  └─────────────────────┘
        │
        ▼
  ┌─────────────────────┐
  │ Phase 5: Validate    │  EpiDoc schema, structure, spot-check
  └─────────────────────┘
        │
        ▼
  Final TEI XML
```

---

## Phase 1: Image Preparation

Convert JP2 to PNG for Gemini API compatibility. JP2 is not natively supported by most vision APIs.

```bash
mkdir -p beck_png
for f in b23982500_0002_jp2/*.jp2; do
  base=$(basename "$f" .jp2)
  convert "$f" "beck_png/${base}.png"
done
```

Alternatively, if storage is a concern, convert to JPEG at 90% quality (~150 KB each vs ~1.5 MB PNG). Gemini handles both.

**Output**: 728 PNG files, ~1 GB total.

---

## Phase 2: Gemini 2.5 Pro Transcription

### Why a sliding window?

Beck's footnotes routinely break across pages (the uploaded sample shows footnote 4 cut off mid-sentence). A single-page prompt cannot resolve these. Sending pages **(N, N+1)** together lets Gemini see the footnote continuation and produce a complete `<note>`.

### Window strategy

- **Window size**: 2 pages (current + next)
- **Stride**: 1 page
- **Instruction**: "Transcribe page N completely. Use page N+1 ONLY to complete any footnote that is cut off at the bottom of page N."
- **Result**: Each page gets transcribed exactly once as the "primary" page of its window. Cross-page footnotes are captured from the secondary page.

This produces 727 API calls (pages 0–726 each paired with N+1; page 727 runs solo).

### API choice: Vertex AI Batch Prediction

Google Cloud batch prediction is ~50% cheaper than online requests and has no rate limits. Requires:
1. Upload images to a GCS bucket
2. Create a JSONL request file
3. Submit batch job
4. Poll for completion
5. Download results

```bash
# Upload images to GCS
gsutil -m cp beck_png/*.png gs://YOUR_BUCKET/beck-dioscorides/images/

# Generate batch request JSONL
python3 scripts/beck_build_batch.py \
  --images-dir beck_png/ \
  --gcs-prefix gs://YOUR_BUCKET/beck-dioscorides/images/ \
  --system-prompt prompts/beck_system.md \
  --output batch_request.jsonl

# Submit batch job
python3 scripts/beck_submit_batch.py \
  --request batch_request.jsonl \
  --output-gcs gs://YOUR_BUCKET/beck-dioscorides/output/ \
  --model gemini-2.5-pro

# Download results
gsutil -m cp gs://YOUR_BUCKET/beck-dioscorides/output/* beck_raw_tei/
```

**Fallback**: If batch API is unavailable or you prefer tighter control, use the online `generateContent` endpoint with a rate limiter (≤5 RPM for free tier, higher with paid).

### System prompt (`prompts/beck_system.md`)

The prompt must handle six concerns simultaneously:

```markdown
You are producing a diplomatic TEI/EpiDoc XML transcription of Lily Y. Beck's
English translation of Dioscorides' De Materia Medica (Hildesheim: Olms-Weidmann, 2005).

You receive TWO page images. Transcribe the FIRST page completely.
Use the SECOND page ONLY to complete footnotes that are cut off at the
bottom of page 1.

## Output structure

Wrap your entire output in a single <div type="page" n="PAGE_NUMBER">.

### Main text
- <p> for body paragraphs
- <head> for chapter/section headings (e.g., "BOOK I", "Preface", "1. Iris")
- <salute> for salutations ("Dear Areios,")
- <lb/> at every printed line break
- <pb n="N"/> at the page boundary

### Footnotes
- In-text markers: <ref target="#fn_PAGE_N" type="footnote-ref">N</ref>
  (use superscript number as printed)
- Footnote body: <note xml:id="fn_PAGE_N" n="N">...</note>
  collected in a <div type="footnotes"> at the end of the page div.
- If a footnote CONTINUES from the previous page, mark it:
  <note xml:id="fn_PREVPAGE_N" n="N" type="continued">...continuation text...</note>
- If a footnote is CUT OFF at the bottom of page 1, complete it using
  the top of page 2. Do NOT transcribe any other content from page 2.

### Scientific names
- Wrap ALL binomial Latin names (genus + species) and their authorities in:
  <name type="scientific"><hi rend="italic">Genus species</hi> Authority</name>
- Wrap standalone genus names similarly:
  <name type="scientific"><hi rend="italic">Genus</hi></name>
- Common plant/animal/mineral names that are subjects of chapters:
  <name type="common">Iris</name>

### Bibliography in footnotes
- Each bibliographic reference in a footnote gets <bibl>:
  <bibl xml:id="SHORT_KEY">
    <author>Surname</author>,
    <title level="m" rend="italic">Book Title</title> or
    <title level="a">"Article Title"</title>,
    <title level="j" rend="italic">Journal</title>,
    vol (year): pages
  </bibl>
- Reuse xml:id for the SAME work. First occurrence defines it; subsequent
  occurrences use <bibl corresp="#SHORT_KEY">.
- For well-known reference works use standard keys:
  PW = Pauly-Wissowa, RE
  ANRW = Aufstieg und Niedergang der römischen Welt
  OCD = Oxford Classical Dictionary
  NH = Pliny, Naturalis Historia
  LSJ = Liddell-Scott-Jones

### Greek and Latin
- <foreign xml:lang="grc"> for Greek text (preserve polytonic accents)
- <foreign xml:lang="la"> for Latin phrases (NOT binomial names — those get <name>)

### Typography
- <hi rend="italic"> for italics
- <hi rend="bold"> for bold
- <hi rend="spaced"> for letter-spaced text (Sperrschrift)

## Rules
1. The image is AUTHORITATIVE. Transcribe exactly what is printed.
2. Preserve original punctuation, capitalization, and hyphenation.
3. Output ONLY the XML fragment. No markdown fences, no explanations.
4. Every <bibl> must have an xml:id (first occurrence) or corresp (reuse).
```

### Cost estimate

Per window: ~2 images × ~1500 tokens input + ~2000 tokens output ≈ 3500 tokens.
727 windows × 3500 tokens ≈ **2.5M tokens total**.
At Gemini 2.5 Pro batch pricing (~$1.25/1M input, $10/1M output):
- Input: ~1.1M text tokens + image tokens ≈ $5–10
- Output: ~1.5M tokens ≈ $15
- **Total: ~$20–25** (batch), ~$40–50 (online)

Image token costs may dominate — Gemini charges per image. At 728×2 = 1456 image inputs, budget ~$15–30 for images depending on resolution pricing.

**Conservative estimate: $50–80 total.**

---

## Phase 3: Stitch & Merge

### 3a. Parse raw Gemini output

Each response is a `<div type="page" n="N">` fragment. Parse all 727 into a dict keyed by page number.

### 3b. Handle cross-page footnotes

```python
# Pseudocode
for page_n in sorted(pages):
    for note in page_n.findall('.//note[@type="continued"]'):
        # This note continues a footnote from page N-1
        prev_page = pages[page_n - 1]
        original_note = prev_page.find(f'.//note[@n="{note.get("n")}"]')
        # Append continuation text to the original note
        merge_note_text(original_note, note)
        # Remove the continuation stub
        note.getparent().remove(note)
```

### 3c. Assemble into book/chapter structure

Beck's structure: Books 1–5, each with numbered chapters. The page-level `<div>`s must be re-nested into:

```xml
<div type="textpart" subtype="book" n="1">
  <div type="textpart" subtype="chapter" n="1">
    <!-- content spanning pages X–Y -->
  </div>
</div>
```

This requires detecting chapter boundaries from `<head>` elements in the page fragments. Script `beck_restructure.py` handles this.

### 3d. Merge split paragraphs

When a paragraph spans a page break, the stitcher joins the `<p>` from page N with the continuation on page N+1 (detected by: page N+1 starts with lowercase / no `<head>`).

---

## Phase 4: Enrichment

### 4a. Scientific name linking

Match `<name type="scientific">` elements against the identifications spreadsheet:

```python
# Load spreadsheet into lookup: (book, chapter) → [identifications]
# For each <name type="scientific"> in a chapter:
#   1. Normalize the binomial (strip authority)
#   2. Look up in spreadsheet by book.chapter
#   3. Add @key attribute: <name type="scientific" key="Plant_0696">
#   4. If certainty < "high", add @cert="low"
```

This enriches ~1214 botanical names with stable IDs.

### 4b. Bibliography deduplication

Gemini will produce `<bibl xml:id="...">` on first occurrence per page window, but the same work appears across hundreds of pages. Post-processing:

1. Collect all `<bibl>` elements with `@xml:id`
2. Cluster by normalized author+title
3. Assign canonical `@xml:id` to first global occurrence
4. Convert all duplicates to `<bibl corresp="#CANONICAL_ID">`
5. Build a `<listBibl>` in the `<teiHeader>` back matter

### 4c. Build standoff bibliography

```xml
<back>
  <div type="bibliography">
    <listBibl>
      <bibl xml:id="Riddle.Dioscorides">
        <author>John Riddle</author>,
        <title level="m">Dioscorides on Pharmacy and Medicine</title>.
        <pubPlace>Austin</pubPlace>: <publisher>Univ. of Texas Press</publisher>,
        <date>1985</date>.
      </bibl>
      <!-- ... all unique works ... -->
    </listBibl>
  </div>
</back>
```

### 4d. Species index

Generate a `<div type="index">` listing all identified species with back-references to chapters:

```xml
<div type="index" subtype="botanical">
  <list>
    <item xml:id="Plant_0696">
      <name type="scientific">Artemisia abrotonum L.</name>
      <ref target="#ch_3_24">3.24</ref>
    </item>
  </list>
</div>
```

---

## Phase 5: Validation

### 5a. XML well-formedness + EpiDoc schema

```bash
xmllint --noout output/beck_dioscorides_epidoc.xml
xmllint --relaxng tei-epidoc.rng --noout output/beck_dioscorides_epidoc.xml
```

### 5b. Structural checks (`beck_validate.py`)

- All 5 books present
- Chapter count per book matches expected (Beck follows Wellmann numbering)
- Every `<ref type="footnote-ref">` has a corresponding `<note>`
- No orphaned `<note type="continued">`
- Every `<bibl corresp="...">` points to an existing `@xml:id`
- All `<name type="scientific" key="...">` keys exist in the spreadsheet
- `<pb>` numbers are monotonically increasing
- No empty `<p>` or `<note>` elements

### 5c. Spot-check (Gemini)

Re-send 30 random pages to Gemini with the question: "Compare this image to the following XML transcription. List any discrepancies." Flag pages with >2 discrepancies for manual review.

### 5d. Footnote integrity

- Count total footnotes per page in XML vs visible footnote markers in images (via a second Gemini pass on a sample)
- Verify no footnote text is duplicated (from the overlap window)

---

## Script Inventory

| Script | Purpose |
|--------|---------|
| `beck_convert_images.sh` | JP2 → PNG conversion |
| `beck_build_batch.py` | Generate Vertex AI batch JSONL from image list + system prompt |
| `beck_submit_batch.py` | Submit batch job, poll for completion, download results |
| `beck_parse_responses.py` | Extract XML fragments from Gemini JSON responses |
| `beck_stitch.py` | Merge cross-page footnotes, join split paragraphs |
| `beck_restructure.py` | Re-nest page-level divs into book/chapter hierarchy |
| `beck_enrich_names.py` | Link `<name>` elements to spreadsheet IDs |
| `beck_dedup_bibl.py` | Deduplicate bibliography, build `<listBibl>` |
| `beck_build_index.py` | Generate species/mineral/animal indices |
| `beck_validate.py` | Structural integrity checks |
| `beck_spot_check.py` | Random sample QA via Gemini |

## Human Gates (3)

1. **After pilot (5 pages)**: Review TEI quality before full batch.
2. **After Phase 3 (stitch)**: Spot-check 10 cross-page footnotes manually.
3. **After Phase 5 (validation)**: Review final validation report.

## Estimates

| Phase | Time | Cost |
|-------|------|------|
| 1: Image conversion | 30 min | $0 |
| 2: Gemini batch (727 calls) | 2–4 hr | $50–80 |
| 3: Stitch & merge | 10 min | $0 |
| 4: Enrichment | 15 min | $0 |
| 5: Validation + spot-check | 1 hr | $5–10 |
| **Total** | **~4–6 hr** | **$55–90** |

## Key Differences from Berendes Pipeline

| | Berendes | Beck |
|--|----------|------|
| Language | German + Greek | English + Greek + Latin |
| OCR baseline | Tesseract (good German) | None — Gemini does direct vision |
| LLM | Codex CLI (Claude) | Gemini 2.5 Pro (Vertex AI) |
| Footnotes | Simple | Dense scholarly, cross-page |
| Bibliography | Minimal | Extensive, needs `<bibl>` tagging |
| Scientific names | In commentary | Throughout, with authorities |
| Identifications | None | 1214 botanical + 147 mineral + 155 animal |
| Cost model | Token-based (Anthropic) | Google Cloud credits |
