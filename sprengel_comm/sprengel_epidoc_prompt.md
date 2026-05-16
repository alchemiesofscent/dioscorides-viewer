# Produce viewer-ready EpiDoc TEI XML from `sprengel_comm_merged.xml`

## Context

We have a page-level diplomatic TEI transcription of Sprengel's *Commentarius in Dioscoridem* (vol. 2, pages 339–666) in `sprengel_comm_merged.xml`. It was produced by Gemini 2.5 Pro OCR and has been through a remediation pass (page-scoped footnote IDs like `fn436_1`, normalized language codes, fixed hyphenation, etc.).

This file now needs to be transformed into EpiDoc TEI XML that works with our existing custom HTML viewer. The viewer already renders the Berendes 1902 edition from `berendes (1).xml` in the same project folder.

The Sprengel file lives in the Ubuntu working directory at:
```
/home/seancoughlin/Projects/tei-maker/sprengel_comm/sprengel_comm_merged.xml
```

The Berendes viewer file is at:
```
/home/seancoughlin/Projects/tei-maker/berendes (1).xml
```

## What the viewer expects

Based on the Berendes XML, the viewer consumes this structure:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI>
  <teiHeader>...</teiHeader>
  <text>
    <!-- Front matter sections use <h2> + <p id="..."> -->

    <!-- Book divisions use <h2> -->
    <h2>Zweites Buch</h2>

    <!-- Chapters use <div type="chapter"> -->
    <div type="chapter" n="2.1" tuid="DiosMatMed:2.1" id="div-XXX">
      <milestone type="section" n="2.1" display="DISPLAY_NAME" id="e-XXX" page="NNN"/>
      <pb n="NNN" facs="FACS_URL" id="e-NNN"/>

      <!-- Chapter heading in <p> with <span> wrappers -->
      <p n="2.1" id="p-NNN">
        <span type="num">Cap. 1 </span>
        <span type="grk">Περὶ ...</span>
        <span type="deu"><b>LATIN TITLE</b></span>
        COMMENTARY TEXT...
        <note n="1" display="[1]" corresp="#cite_note-1" id="ftn-NNN"/>
      </p>

      <!-- Separator -->
      <hr id="hrN"/>

      <!-- Footnotes as ordered list -->
      <div class="mw-references-wrap" id="div-NNN">
        <ol class="references">
          <li id="cite_note-1"><span class="reference-text">...</span></li>
        </ol>
      </div>
    </div>
  </text>
</TEI>
```

Key viewer conventions:
- `<pb n="..." facs="URL"/>` — page breaks with facsimile links
- `<p id="p-NNN">` — sequential paragraph IDs across the whole document
- `<note n="N" display="[N]" corresp="#cite_note-N" id="ftn-NNN"/>` — inline footnote markers
- `<li id="cite_note-N">` — footnote bodies in `<ol class="references">`
- `<foreign xml:lang="grc">` — Greek passages (already present in Sprengel file)
- `<foreign xml:lang="ar">` / `<foreign xml:lang="he">` — Arabic/Hebrew (already present)
- `<hi rend="italic">` — italic text (already present)
- `<hr/>` separators between text and footnotes
- `<milestone type="section">` with `display` attribute for TOC generation

## Source file structure (current)

The Sprengel merged XML currently has:
- `<TEI>` with `<teiHeader>`, `<text>`, `<body>`
- `<pb n="339"/>` through `<pb n="666"/>` (328 pages)
- `<lb/>` and `<lb break="no"/>` line breaks
- `<ref target="#fnP_N">` inline footnote refs
- `<note xml:id="fnP_N" n="N" place="foot">` footnote bodies, sometimes in `<div type="footnotes">`
- `<foreign xml:lang="grc/ar/he/syc">` language tags
- `<hi rend="italic">` formatting
- `<label>Cap. XXXIII.</label>` chapter labels (inconsistent — some are in running text)
- Running headers as bare text after `<pb/>` (e.g., `IN DIOSCORIDEM. II. 32—34. 437`)
- Catch-words at page bottoms (e.g., `Ee 2`)

## Transformation tasks

### 1. Add facsimile URLs to `<pb/>` elements

The page images are on Internet Archive. Two scans available:

**Primary (Royal College of Physicians):** `b23982500_0002`
- Image pattern: `https://archive.org/download/b23982500_0002/b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_{LEAF:04d}.jp2`
- Offset: book page P → leaf = P + 8 (page 339 = leaf 0347)
- Missing: pages 436–437 (use BIU Santé for these)

**Secondary (BIU Santé):** `BIUSante_dioscsprengelx02`
- Use for pages 436–437 only (leaves 0437, 0438)
- Pattern: `https://archive.org/download/BIUSante_dioscsprengelx02/BIUSante_dioscsprengelx02_jp2.zip/BIUSante_dioscsprengelx02_jp2%2FBIUSante_dioscsprengelx02_{LEAF:04d}.jp2`

Add `facs` attribute to every `<pb/>`.

### 2. Detect and wrap chapters

Sprengel's commentary follows Dioscorides' chapter numbering. Chapter boundaries are marked by `Cap. N.` (Roman numerals) in the text, sometimes in `<label>` tags, sometimes inline. The Dioscorides chapter numbers in this volume range across Books I–V.

#### Detecting chapter boundaries vs. cross-references

Most `Cap. N.` occurrences (~690) are cross-references to other chapters, not boundaries. A `Cap. N.` is a **boundary** when it:
- Is in a `<label>` tag, OR
- Appears at the start of a paragraph/section (after a `<pb/>` running header or after the previous chapter's last sentence), OR
- Is immediately followed by a Greek lemma (e.g., `Cap. XXXIII. Ὠμοτάριχον...`)

A `Cap. N.` is a **cross-reference** (leave inline, do not split) when it appears mid-sentence in commentary prose (e.g., `...ut diximus ad Cap. XII.`).

#### Determining book number

Parse running headers **before removing them** (task 5). The pattern `IN DIOSCORIDEM. {ROMAN}. {chapter-range}. {page}` gives the book number for each page. Build a page→book lookup, then combine with the detected `Cap.` number to get `BOOK.CHAPTER`.

#### Linking to the text edition (primary)

The Sprengel text edition (`sprengel1829_epidoc.xml`) already has chapter milestones:
```xml
<milestone unit="chapter" n="1.1" xml:id="spr-ch-1.1-la" label="De Iride"
           pairedLabel="Περὶ Ἴριδος" corresp="#spr-ch-1.1-grc"/>
```

For each detected commentary chapter, add a `corresp` attribute pointing to the text edition:
```xml
<div type="chapter" n="1.1" tuid="SprengelComm:1.1" id="div-NNN"
     corresp="sprengel1829_epidoc.xml#spr-ch-1.1-la">
```

Use the text edition's `label` (Latin) as the primary `display` name on the milestone, and `pairedLabel` (Greek) as a secondary display. The milestone should be:
```xml
<milestone type="section" n="1.1" display="De Iride" display-grc="Περὶ Ἴριδος" id="e-NNN" page="PAGE"/>
```

#### Linking to Berendes (secondary)

The Berendes viewer file uses `tuid="DiosMatMed:1.1"`. The shared `n` attribute (`1.1`, `2.33`, etc.) provides the cross-link. The viewer can match any `SprengelComm:X.Y` chapter to `DiosMatMed:X.Y` by the `n` value.

#### Chapter wrapping

For each detected chapter:
- Wrap in `<div type="chapter" n="BOOK.CHAPTER" tuid="SprengelComm:BOOK.CHAPTER" id="div-NNN" corresp="sprengel1829_epidoc.xml#spr-ch-BOOK.CHAPTER-la">`
- Add `<milestone type="section" n="BOOK.CHAPTER" display="LATIN_TITLE" display-grc="GREEK_TITLE" id="e-NNN" page="PAGE"/>`

**Important:** Chapter boundaries often fall mid-page. A chapter may start on one page and end on another. The `<div>` should span across `<pb/>` elements as needed.

#### Reference data

A pre-extracted lookup table is available at `sprengel_chapter_table.tsv` (TSV, 918 rows):
```
n	xml_id	label_la	label_grc
1.1	spr-ch-1.1-la	De Iride	Περὶ Ἴριδος
1.2	spr-ch-1.2-la	De Acoro	Περὶ Ἀ��όρου
...
5.182	spr-ch-5.182-la	De atramento	Περὶ μέλανος
```

Use this table to:
- Look up `label_la` → `display` attribute on the commentary milestone
- Look up `label_grc` → `display-grc` attribute
- Look up `xml_id` → build the `corresp` URI (`sprengel1829_epidoc.xml#spr-ch-{n}-la`)

If a commentary chapter's `n` has no match in the table (unlikely), fall back to whatever heading text appears inline after `Cap. N.`

The full text edition file is `sprengel1829_epidoc.xml` in the same directory.

### 3. Convert footnotes to viewer format

Current:
```xml
<ref target="#fn436_1">1</ref>
...
<note xml:id="fn436_1" n="1" place="foot">Footnote text.</note>
```

Target:
```xml
<note n="1" display="[1]" corresp="#cite_note-436_1" id="ftn-SEQUENTIAL"/>
...
<hr id="hr-PAGE"/>
<div class="mw-references-wrap" id="div-fn-PAGE">
  <ol class="references">
    <li id="cite_note-436_1"><span class="reference-text">Footnote text.</span></li>
  </ol>
</div>
```

- Replace `<ref target="...">` with self-closing `<note>` markers
- Group footnote bodies per page into `<ol class="references">` blocks
- Place footnote blocks at the end of each page's content (before the next `<pb/>`)
- Use sequential IDs for `ftn-NNN` across the whole document

### 4. Convert line breaks to paragraphs

The current file uses `<lb/>` for every printed line. The viewer doesn't render `<lb/>` — it expects `<p>` elements.

**Strategy:**
- Remove `<lb/>` and `<lb break="no"/>` elements
- Join lines into continuous text (respecting `break="no"` for hyphenation: remove the hyphen and join the word)
- Wrap each logical paragraph in `<p id="p-NNN">`
- Paragraph boundaries: blank lines in the source, or chapter-heading transitions

### 5. Handle running headers and catch-words

- Remove running headers (e.g., `IN DIOSCORIDEM. II. 32—34. 437`, `436 COMMENTARIUS`)
- Remove catch-words / signature marks (e.g., `Ee 2`, `DIOSCORIDES II. Dd`)
- These are print artifacts, not content

### 6. Update `<teiHeader>`

Ensure the header identifies this as Sprengel's Commentarius:
```xml
<teiHeader>
  <fileDesc>
    <titleStmt>
      <title>Commentarius in Pedanii Dioscoridis Anazarbei De Materia Medica</title>
      <author>Kurt Sprengel</author>
      <date>1830</date>
    </titleStmt>
    <sourceDesc>
      <bibl>
        <title>Pedanii Dioscoridis Anazarbei De materia medica libri quinque</title>
        <editor>Kurt Polykarp Joachim Sprengel</editor>
        <publisher>Car. Cnoblochii</publisher>
        <pubPlace>Leipzig</pubPlace>
        <date>1830</date>
        <note>Tomus II: Commentarius</note>
      </bibl>
    </sourceDesc>
  </fileDesc>
</teiHeader>
```

### 7. Sequential ID assignment

All `id` attributes must be globally unique and sequential:
- `p-1`, `p-2`, ... for paragraphs
- `ftn-1`, `ftn-2`, ... for footnote markers
- `div-1`, `div-2`, ... for chapter divs
- `e-1`, `e-2`, ... for milestones and page breaks
- `hr-1`, `hr-2`, ... for separators

### 8. Wrap bare Greek characters

The CLI validator found 21 Greek characters sitting outside `<foreign xml:lang="grc">` tags. Find all runs of Greek Unicode (U+0370–U+03FF, U+1F00–U+1FFF) not already inside a `<foreign>` element and wrap them in `<foreign xml:lang="grc">...</foreign>`.

### 9. Normalize Greek theta symbol

10 instances of `ϑ` (U+03D1, GREEK THETA SYMBOL) appear in the file. Normalize all to `θ` (U+03B8, GREEK SMALL LETTER THETA). This is a character-level normalization, not a content change.

## Do NOT change

- Greek, Arabic, Hebrew, Syriac text content (aside from the `ϑ` → `θ` normalization above)
- `<foreign xml:lang="...">` tags (already correct after normalization — but *add* missing wrappers per task 8)
- `<hi rend="italic">` markup
- Footnote text content

## Validation

After transformation:
1. `xmllint --noout` — zero errors
2. Every `corresp` in a `<note>` marker points to exactly one `<li id="cite_note-...">`
3. Every `<div type="chapter">` has a corresponding `<milestone>`
4. Every `<pb>` has a `facs` attribute
5. No `<lb/>` elements remain
6. No running headers or catch-words in the output
7. No Greek characters (U+0370–U+03FF, U+1F00–U+1FFF) outside `<foreign xml:lang="grc">`
8. No `ϑ` (U+03D1) remaining — all normalized to `θ`
7. All `id` attributes are unique
8. Report: total chapters detected, total pages, total footnotes, total paragraphs
