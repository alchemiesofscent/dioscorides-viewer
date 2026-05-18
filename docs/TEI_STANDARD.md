# pharmacopoeia TEI standard

This document defines the canonical TEI shape every edition in
`corpus/dioscorides/editions/` must conform to. Each migration in
`pipeline/pharmacopoeia/migrate/` normalizes its output to these rules; the
validator (`pipeline/pharmacopoeia/validators/checks.py` and
`schemas/pharmacopoeia.sch`) asserts conformance.

The goal is one consistent shape across heterogeneous source TEI so that the
viewer, schema-validation, lemma extraction, and cross-edition linking can
treat all editions uniformly.

## Edition identifiers (CTS work-version form)

Each edition has three identifiers:

| form | example | used for |
|---|---|---|
| **short alias** | `berendes1902` | CLI args, lemma URI prefixes, viewer registry `id` |
| **CTS work-version** | `tlg0656.tlg001.berendes1902-ger1` | edition **directory name** and TEI **file basename** |
| **CTS URN** | `urn:cts:greekLit:tlg0656.tlg001.berendes1902-ger1` | manifest `cts_urn` field, viewer registry `cts_urn`, future TEI header CTS metadata |

The TEI file basename is the full CTS work-version (e.g.
`tlg0656.tlg001.berendes1902-ger1.xml`), so the file is uniquely identified
even if copied out of its directory:

```
corpus/dioscorides/editions/
├── tlg0656.tlg001.berendes1902-ger1/
│   ├── manifest.json
│   └── tei/
│       └── tlg0656.tlg001.berendes1902-ger1.xml
├── tlg0656.tlg001.sprengel1829-grclat1/
│   ├── manifest.json
│   └── tei/
│       └── tlg0656.tlg001.sprengel1829-grclat1.xml
└── ...
```

CTS textgroup `tlg0656` is Dioscorides; work `tlg001` is *De materia
medica*. Version suffixes follow CTS conventions: `-ger1` (German
translation), `-grclat1` (Greek + Latin parallel — non-standard but
descriptive), `-lat1` (Latin), `-eng1` (English). The mapping between short
alias and CTS form is the single source of truth in
`pipeline/pharmacopoeia/paths.py::EDITION_REGISTRY`.

The lemma URI namespace continues to use the **short alias**
(`lemma:berendes1902-grc:zingiberis`) rather than the full CTS form,
because the URIs appear hundreds of times per edition and the short form is
substantially more readable. The CTS URN is still recorded in each lemma
file's `<teiHeader>` for provenance.

## `<lb/>` — line beginning

**Canonical form:** `<lb n="N"/>` — self-closing, no space before `/>`,
integer `@n` counting printed lines on the current page (resets at each
`<pb/>`).

- `@n` is **required** when `<lb>` is a descendant of the main text stream
  (`<ab>`, `<p>`, `<head>`). It records the printed body line number on the
  page.
- `@n` is **optional** when `<lb>` is inside a `<note>` body. There it marks a
  visual break within the footnote text, not a page-line.
- Empty main-stream `<lb>` milestones are not allowed. If a body-line marker
  has no text before the next line, page break, or block boundary, migration
  removes it and renumbers the page.
- `@xml:id` is **optional**, recommended only when other elements reference
  the line (e.g. Sprengel 1829's `<ref target="#spr-lb-...">`). Recommended
  format: `<edition-prefix>-lb-<book>-<page>-<line>` (e.g.
  `spr-lb-2-0332-08`).
- `@break="no"` is the canonical way to mark a hyphenated line-end. Example:

  ```xml
  Ingwer-<lb n="2" break="no"/>pflanze
  ```

  No ad-hoc hyphen-preservation conventions.
- **Forbidden attributes on `<lb>`**: `bbox`, `cert`, `source`, `seq`, plain
  `id` (use `xml:id`). These are stripped at migration time.

## `<fw>` — page furniture

`<fw>` records printed page furniture, chiefly running headers, printed page
numbers, and signatures. It is outside the body line-numbering stream.

- `<fw>` must not contain `<lb>` descendants. If source OCR places
  `<lb n="1"/>` inside a running header or signature, the migration unwraps the
  marker and preserves the furniture text.
- Removing furniture line markers must not shift the meaning of body lines:
  migrations renumber main-stream `<lb>` values from `1..N` after each `<pb>`.
- Use explicit furniture types and placement, e.g.
  `<fw type="header" place="top">COMMENTARIUS</fw>`,
  `<fw type="pageNum" place="top-outer">340</fw>`, or
  `<fw type="sig" place="bottom">Y 2</fw>`.

## `<pb/>` — page beginning

**Canonical form:**

```xml
<pb n="N" facs="URL" xml:id="<prefix>-pb-NNNN"/>
```

- `@n` is the printed page number (Roman numerals allowed, e.g. `n="vi"`).
- `@xml:id` is **required** for cross-referencing. Recommended format:
  `<edition-prefix>-pb-NNNN` where NNNN is the source-image page index.
- `@facs` must be a **renderable image URL** — never `.jp2`. Allowed:
  - Heidelberg JPEG:
    `https://digi.ub.uni-heidelberg.de/diglitData/image/.../*.jpg`
  - Internet Archive IIIF JPEG derivative:
    `https://iiif.archive.org/image/iiif/3/<item>/full/1200,/0/default.jpg`
  - Local relative path to JPEG/PNG:
    `page_images/page-0006.png` or `local:beck2020/images/beck-0001.png`
- **JP2 archive URLs are rewritten** at migration time to their IIIF JPEG
  derivative. The original JP2 URL is preserved on `@source` so archival
  provenance isn't lost. Example:

  Before (in `editions/sprengel1830-comm/tei/edition.xml`):
  ```xml
  <pb n="339" facs="https://archive.org/download/b23982500_0002/b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0347.jp2"/>
  ```
  After migration:
  ```xml
  <pb n="339"
      facs="https://iiif.archive.org/image/iiif/3/b23982500_0002%2Fb23982500_0002_jp2.zip%2Fb23982500_0002_jp2%2Fb23982500_0002_0347.jp2/full/1200,/0/default.jpg"
      source="https://archive.org/download/b23982500_0002/b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0347.jp2"/>
  ```

## `<div type="textpart">` — book/chapter axis

- Top-level: `<div type="textpart" subtype="edition" xml:lang="LANG">` (used
  when an edition has multiple parallel language streams, e.g. Sprengel grc
  + la).
- Books: `<div type="textpart" subtype="book" n="N" xml:id="<prefix>-book-N">`.
- Chapters: `<div type="textpart" subtype="chapter" n="B.C" xml:id="<prefix>-ch-B-C">`.
  - `@n` is **required** and follows the form `B.C` (e.g. `2.189`).
  - `<head>` is **required** as the first child.
  - When the chapter has a known cross-language pair, `@corresp` points at the
    paired chapter (e.g. `corresp="#spr-ch-2.189-la"`).
- Sub-sections (Beck-style `1.1.1`): `<div type="textpart" subtype="section"
  n="B.C.S">`. Sub-sections may reuse `@n` values across chapters
  (`1.2.1` appears under both 1.1 and 1.2), so their `@xml:id` carries an
  arbitrary disambiguator from the source — do not normalize.

## `<note>` — footnote bodies

- Body: `<note place="bottom" xml:id="..." n="N" corresp="#ref-...">`.
- Marker in text: `<ref target="#fn-..." type="footnote-ref">N</ref>`.
- Cross-page footnote bodies (a single note continued onto the next page) use
  `@next`/`@prev` to chain. Both halves carry the same `@n`. (v1: deferred for
  Berendes; the existing xml:id/corresp pattern is preserved.)

## Lemma identifiers

- Format: `lemma:<edition-slug>-<lang>:<headword-slug>` (e.g.
  `lemma:berendes1902-de:ingwer`).
- In edition TEI, references use `@corresp` on `<foreign>`, `<hi rend="bold">`,
  `<term>`, etc.: `<term corresp="lemma:sprengel1829-grc:zingiberis">…</term>`.
- In lemma files (`corpus/dioscorides/lemmas/*.xml`), each `<category>` carries
  the URI on `@n` — **not** `@xml:id`, because `xml:id` must be a NCName (no
  colons allowed):

  ```xml
  <category n="lemma:sprengel1829-grc:zingiberis">
    <catDesc><foreign xml:lang="grc">ζιγγίβερις</foreign></catDesc>
    <note type="occurrence" target="corpus/dioscorides/editions/sprengel1829/tei/edition.xml#spr-ch-2.189-grc"/>
  </category>
  ```

- The validator looks up `<category>` by `@n`.

## Lemma-link files

```xml
<linkGrp type="lemma-translation"
         from="lemma:sprengel1829-grc" to="lemma:sprengel1829-la">
  <link xml:id="link-0001"
        target="lemma:sprengel1829-grc:zingiberis lemma:sprengel1829-la:zingiberis"
        cert="high" resp="#sprengel_himself"
        evidence="Sprengel's parallel printing pairs chapter 2.189 ..."/>
</linkGrp>
```

- `@type` is **open vocabulary** (`lemma-translation`, `lemma-recipe-ingredient`,
  `lemma-equivalence-claim`, etc.). The validator does not enumerate it.
- `@from` / `@to` declare the source/target lemma namespaces.
- `@target` on `<link>` is exactly two whitespace-separated lemma URIs.
- `@cert` ∈ {high, medium, low}.
- `@resp` points at a person identifier (e.g. `#sprengel_himself`, `#beck`).

## Forbidden attributes (stripped at migration time)

- On any element: `bbox`, `cert`, `source`, `seq` (Beck OCR artefacts).
  - Exception: `@source` on `<pb>` is allowed when it preserves the original
    JP2 archive URL after the migration has rewritten `@facs` to the IIIF
    JPEG derivative.
- On any element: `class` (MediaWiki residue).
- On `<lb>`, `<pb>`, etc.: per-word `xml:id` patterns matching
  `beck-fresh(?:-diplomatic)?-p\d+-l\d+(-w\d+)?` (Beck OCR per-word ids).

## Annotation rules in text

- Scientific binomial / genus (the only level treated as identification):
  `<name type="taxon" ref="ipni:798435-1">Zingiber officinale Roscoe</name>`
- Vernacular plant / animal / mineral names: `<term corresp="lemma:...">name</term>`.
- Persons: `<persName ref="viaf:...">Dioskurides</persName>`.
- Places: `<placeName ref="pleiades:...">Anazarba</placeName>`.
- Foreign words: `<foreign xml:lang="grc">…</foreign>`.

Annotation is **major-item only**. No full word-tokenization.
