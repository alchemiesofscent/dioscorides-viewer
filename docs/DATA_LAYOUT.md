# External data root (`$TEI_MAKER_DATA`)

Raw source assets (PDFs, JP2 archives, source XMLs), page images, OCR
intermediates, build artefacts, and regression baselines all live **outside
the repository**, under a single external data root. The repo holds only
the scholarly TEI outputs, lemma files, lemma-link claims, viewer code,
and pipeline source.

## Where it lives

The pipeline reads the environment variable `TEI_MAKER_DATA`. Set it in
your shell or in `.env` at the repo root:

```
TEI_MAKER_DATA=/home/seancoughlin/Projects/tei-maker-data
```

(See `.env.example`.) If unset, the conventional default is
`~/Projects/tei-maker-data/`.

## Layout

```
$TEI_MAKER_DATA/
├── sources/                                   # original, read-only inputs
│   ├── SOURCES_SHA256SUMS.txt                 # bit-identity manifest
│   ├── tlg0656.tlg001.berendes1902-ger1/
│   │   ├── berendes (1).xml                   # source XML from prior project
│   │   └── berendes1902__z3.pdf               # Heidelberg PDF facsimile
│   ├── tlg0656.tlg001.beck2020-eng1/
│   │   ├── beck.pdf                           # private Beck PDF
│   │   └── beck.xml                           # Beck source XML
│   ├── tlg0656.tlg001.sprengel1829-grclat1/
│   │   └── tlg0656001.xml … tlg0656004.xml    # TLG canonical Greek + variants
│   └── tlg0656.tlg001.sprengel1830-comm/
│       ├── b23982500_0002_jp2.zip             # Wellcome JP2 archive
│       └── working/                           # extracted + derivative working files
│           ├── b23982500_0002.pdf
│           ├── b23982500_0002_jp2/            # unzipped JP2s
│           └── sp-comm/                       # in-progress commentary work
├── images/                                    # page images
│   ├── IMAGES_SHA256SUMS.txt
│   ├── tlg0656.tlg001.berendes1902-ger1/
│   │   ├── raw/                               # 595 pages from PDF extraction
│   │   └── enhanced/                          # OCR-prepped derivatives
│   └── tlg0656.tlg001.beck2020-eng1/
│       └── page_images/
├── ocr/                                       # OCR intermediates (hOCR, TSV, plain text)
│   └── legacy/                                # archived prior OCR runs
├── build/                                     # generated artefacts, audit ledgers
│   ├── audits/
│   ├── chunks_pilot_gate/                     # pilot review state
│   └── costs.csv                              # LLM API cost ledger
└── baseline/                                  # regression snapshots
    └── <yyyymmdd-HHMMSS>/
```

The four edition directories (`sources/`, `images/`, `ocr/`) use the CTS
work-version form (`tlg0656.tlg001.<version>`) as the directory name, the
same form used inside the repo at `corpus/dioscorides/editions/`.

## Verifying integrity

`SOURCES_SHA256SUMS.txt` and `IMAGES_SHA256SUMS.txt` record SHA-256 hashes
for every file in their respective trees. Verify with:

```bash
( cd "$TEI_MAKER_DATA" && sha256sum -c sources/SOURCES_SHA256SUMS.txt )
( cd "$TEI_MAKER_DATA" && sha256sum -c images/IMAGES_SHA256SUMS.txt )
```

## How the v1 pipeline uses it

The v1 migrations (`pharmacopoeia migrate <edition>`) read **pre-migrated
TEI inputs from a legacy `editions/` tree that has since been removed**.
They don't currently touch `$TEI_MAKER_DATA`. The data root becomes
critical again in v1.1+, when migration stages regenerate from PDFs / JP2
sources (Gemini OCR for Beck low-confidence pages, page-image extraction
for Berendes, etc.).

## What does NOT live here

- TEI editions, lemma files, lemma-link files, manifests — those are
  scholarly outputs and live inside the repo at `corpus/dioscorides/`.
- Viewer assets, pipeline code, schemas, docs — repo-tracked.
- Secrets (`.env`) — local to each machine, gitignored, never committed.
