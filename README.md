# pharmacopoeia

Scholarly TEI/EpiDoc editions of ancient pharmaceutical texts, with a static
viewer and a deterministic migration pipeline.

The corpus is rooted at `corpus/dioscorides/` and currently ships four
editions of Dioscorides' *De materia medica*:

- **Berendes 1902** — German translation, with Berendes' commentary and
  identifications inline (Heidelberg facsimile, public domain).
- **Sprengel 1829/1830** — Greek + Latin parallel text, chapter-major, with
  Sprengel's own pairing of Greek and Latin chapters preserved as scholarly
  claims (Wellcome / Internet Archive facsimile).
- **Sprengel 1830 Commentarius** — Sprengel's Latin commentary on the same
  text (Wellcome / Internet Archive facsimile).
- **Beck 2020** — modern English translation, diplomatic transcription from
  local PDF source. Not redistributed; the TEI artifact records the
  diplomatic transcription only.

## What's in the repo

```
pharmacopoeia/
├── corpus/dioscorides/
│   ├── editions/tlg0656.tlg001.<version>/      # CTS work-version dirs
│   │   ├── manifest.json                       # carries cts_id + cts_urn
│   │   └── tei/tlg0656.tlg001.<version>.xml    # basename is globally unique
│   ├── editions/index.json                     # viewer registry
│   ├── lemmas/<short-alias>-<lang>.xml         # one taxonomy per edition×language
│   └── lemma-links/<from>--<to>.xml            # scholarly cross-edition claims
├── docs/TEI_STANDARD.md                        # canonical lb/pb/note/lemma + CTS rules
├── schemas/pharmacopoeia.sch                   # working-profile Schematron
├── pipeline/                                   # migration + validation tooling
│   ├── pharmacopoeia/                          # Python package; paths.py = registry
│   └── tests/
├── viewer/                                     # static viewer (no build step)
└── .github/workflows/{validate,pages}.yml
```

Edition CTS work-versions in v1:

| short alias | CTS work-version | CTS URN |
|---|---|---|
| `berendes1902` | `tlg0656.tlg001.berendes1902-ger1` | `urn:cts:greekLit:tlg0656.tlg001.berendes1902-ger1` |
| `sprengel1829` | `tlg0656.tlg001.sprengel1829-grclat1` | `urn:cts:greekLit:tlg0656.tlg001.sprengel1829-grclat1` |
| `sprengel1830-comm` | `tlg0656.tlg001.sprengel1830-comm` | `urn:cts:greekLit:tlg0656.tlg001.sprengel1830-comm` |
| `beck2020` | `tlg0656.tlg001.beck2020-eng1` | `urn:cts:greekLit:tlg0656.tlg001.beck2020-eng1` |

## Scholarly principle

Translations and identifications across editions are not facts — they are
**translator's claims**. Berendes's "Ingwer" for ζιγγίβερις is a translator's
identification of the Greek headword as ginger. The corpus encodes these
relations explicitly:

- Each edition has its own per-language **lemma file** (TEI `<taxonomy>`)
  listing headwords as printed in that edition.
- A **lemma-link file** records each cross-language or cross-edition pairing
  as a `<link>` with `@cert`, `@resp`, and `@evidence` — making the
  scholarly assertion visible and questionable.
- Even an edition author's own pairings (Berendes German↔Greek; Sprengel
  Greek↔Latin) are recorded with `resp="#<author>_himself"`.

See [`docs/TEI_STANDARD.md`](docs/TEI_STANDARD.md) for the canonical TEI shape
every edition conforms to (`<lb>`, `<pb>`, `<note>`, lemma identifiers,
forbidden attributes).

## Quick start

Create a virtualenv and install pipeline dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install lxml pytest
```

Run the full migration (deterministic, no API calls):

```bash
PYTHONPATH=pipeline .venv/bin/python -m pharmacopoeia.cli migrate all
for ed in berendes1902 sprengel1829 beck2020; do
  PYTHONPATH=pipeline .venv/bin/python -m pharmacopoeia.cli lemmas extract $ed
done
PYTHONPATH=pipeline .venv/bin/python -m pharmacopoeia.cli lemmas seed-links sprengel1829 sprengel1829
PYTHONPATH=pipeline .venv/bin/python -m pharmacopoeia.cli lemmas seed-links berendes1902 berendes1902
PYTHONPATH=pipeline .venv/bin/python -m pharmacopoeia.cli validate
PYTHONPATH=pipeline .venv/bin/python -m pytest pipeline/tests -v
```

Serve the viewer locally:

```bash
python3 -m http.server 8000
# open http://localhost:8000/viewer/
```

## Pipeline

All stages are deterministic Python (no LLM calls in v1):

- `migrate berendes1902` — flatten `<div subtype="continuation">` wrappers
  into parent chapter divs; add `@corresp="lemma:..."` hooks on chapter
  `<head>` Greek and German spans.
- `migrate sprengel1829` — walk `<milestone unit="chapter">` markers,
  rebracket content into per-language `<div type="textpart" subtype="chapter">`
  trees with `corresp` linking the Greek and Latin parallels.
- `migrate beck2020` — collapse 181 987 per-word `<w bbox="..." cert="...">`
  elements to plain text inside their parent `<ab>`/`<head>`; drop per-word
  xml:ids and bbox attrs (272K → 68K lines).
- `migrate sprengel1830-comm` — enforce body `<lb>` numbering, unwrap
  page-furniture `<fw>` line markers, rewrite JP2 facs URLs to IIIF JPEG
  derivatives (preserving original on `@source`).
- `lemmas extract <edition>` — walk chapter `<head>` elements to build
  per-edition lemma taxonomy files.
- `lemmas seed-links <from> <to>` — auto-seed a lemma-link file from the
  source TEI's pre-existing `@corresp` evidence.
- `validate [<edition>]` — Python checks that mirror
  `schemas/pharmacopoeia.sch` (chapter shape, note chains, xml:id
  uniqueness, lemma-link target resolution, `<lb>` standard, no bare JP2
  in `@facs`).

## External data

Raw source PDFs, JP2 archives, source XMLs, page images, OCR
intermediates, and generated build artefacts live **outside the
repository**, under the directory pointed to by `$TEI_MAKER_DATA`
(default `~/Projects/tei-maker-data/`). See
[`docs/DATA_LAYOUT.md`](docs/DATA_LAYOUT.md) for the full layout and SHA
verification commands. The v1 pipeline does not currently read from this
directory; it is the source of truth for v1.1+ regeneration workflows.

## Forward compatibility

The lemma + lemma-link pattern extends naturally to recipe texts (Galen,
Aetius, Paul of Aegina, etc.) without architectural change. Each ingredient
mention in a recipe text becomes `<term corresp="lemma:edition-grc:headword">`
referencing the appropriate materia-medica lemma. The Dioscorides lemma file
gains a `<note type="occurrence" target="...">` line per recipe use.

## Licenses

- Code (pipeline + viewer): MIT (`LICENSE`).
- TEI editions, lemma files, lemma-link files, manifests, docs: Creative
  Commons Attribution-NonCommercial 4.0 International (`LICENSE-DATA.md`).
- External facsimile images are not bundled or relicensed; see `NOTICE.md`.
