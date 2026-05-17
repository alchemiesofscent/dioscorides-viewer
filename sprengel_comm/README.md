# Sprengel Commentarius Workflow

This directory holds the committed working evidence for Sprengel's 1830
Commentarius stream.

## Contents

- `ocr_fragments/` - page-level Gemini OCR TEI fragments for Internet Archive
  item `b23982500_0002`, pages 339-666.
- `outputs/sprengel_comm_merged.xml` - merged page-level OCR XML consumed by the
  Commentarius EpiDoc builder.
- `sprengel_chapter_table.tsv` - chapter authority table mapping detected
  Commentarius chapters to generated Sprengel base-text chapter ids and labels
  when available.
- `sprengel_epidoc_prompt.md` - prompt and structural notes from the conversion
  planning pass.
- `costs.csv` - deduped OCR token/cost log for the committed fragment run.
- `page_images/` - ignored local extraction cache; do not commit it.

## Generated Output Contract

The viewer-facing generated XML path is:

```text
output/sprengel_comm_epidoc.xml
```

Do not write the Commentarius into `output/sprengel1829_epidoc.xml`; that file
is the separate Dioscorides base text. The Commentarius builder strips running
furniture, resolves page-scoped footnote targets, wraps bare Greek in
`foreign xml:lang="grc"`, emits page facsimile URLs, and records chapter
milestones for viewer navigation.

The canonical implementation lives under `scripts/sprengel/`:

```bash
python3 scripts/sprengel/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output output/sprengel_comm_epidoc.xml
```

The old entrypoint remains valid through a compatibility wrapper:

```bash
python3 scripts/build_sprengel_comm_epidoc.py \
  --source sprengel_comm/outputs/sprengel_comm_merged.xml \
  --chapter-table sprengel_comm/sprengel_chapter_table.tsv \
  --output output/sprengel_comm_epidoc.xml
```

Validate after rebuilding:

```bash
xmllint --noout output/sprengel_comm_epidoc.xml
```

Known unmatched headings are reported by the builder when a Commentarius
heading has no row in `sprengel_chapter_table.tsv`; those chapters remain
encoded with numeric display labels until the base-text authority table is
extended.
