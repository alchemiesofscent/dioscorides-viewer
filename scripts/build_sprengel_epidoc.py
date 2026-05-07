#!/usr/bin/env python3
"""Build page-first diplomatic Sprengel EpiDoc and viewer manifest."""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
from typing import Callable
import xml.etree.ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
NS = f"{{{TEI}}}"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
ARCHIVE_ID = "b23982500_0001"

ET.register_namespace("", TEI)
ET.register_namespace("xml", XML)


FRONT_LABELS = {
    "title_page": "Title Page",
    "dedication": "Dedication",
    "preface": "Praefatio ad Dioscoridem",
    "errata": "Errata",
}
BOOK_1_GREEK_TITLE = "ΠΕΔΑΝΙΟΥ ΔΙΟΣΚΟΡΙΔΟΥ ΑΝΑΖΑΡΒΕΩΣ ΠΕΡΙ ΥΛΗΣ ΙΑΤΡΙΚΗΣ ΒΙΒΛΙΟΝ Α."
BOOK_1_LATIN_TITLE = "PEDANII DIOSCORIDIS ANAZARBEI DE MATERIA MEDICA LIBER I. PRAEFATIO."
BOOK_1_PROEM_TITLE = "ΠΡΟΟΙΜΙΟΝ."
FRONT_MIDPAGE_HEAD_SPLITS = {
    ("IX", "III. De aetate Dioscoridis."): (8, set()),
    ("X", "IV. De vitae genere."): (16, set()),
    ("XI", "V. De secta, cui nomen dederit."): (15, set()),
    ("XII", "VI. De dictionis genere."): (28, {26, 27}),
    ("XVI", "C. De synonymis plantarum barbaris."): (8, {7}),
    ("XVII", "VIII. De codicibus manuscriptis."): (19, set()),
    ("XX", "IX. De editionibus."): (13, set()),
    ("XXI", "X. De aliis adminiculis."): (23, set()),
    ("XXV", "XI. De hujus editionis ratione."): (15, set()),
}
FRONT_INLINE_SUBHEADS = {
    "C. De synonymis plantarum barbaris.",
}
LINE_TEXT_REPLACEMENTS = {
    "spr-lb-fm-0018-13": "chigenes ",
    "spr-lb-fm-0019-06": "solita: e. g. ἰδρωτοποιΐα, ἐμφαρυγξάμενος, τὸ ἅλας loco",
    "spr-lb-fm-0019-28": "His accedit, (lib. II. c. 63.) ἔξαγίου ponderis ve-",
    "spr-lb-fm-0020-01": "Nec dictiones φασκίωσον (lib. II. c. 67.), σφέκλη,",
    "spr-lb-fm-0020-02": "loco τρυγός (lib. II. c. 137.) qua Alexander Trallianus",
    "spr-lb-fm-0020-03": "primus utitur (lib. II. p. 630.), νηστικός loco νῆστις,",
    "spr-lb-fm-0020-04": "flexiones σεσέλιδος loco σεσέλεως, πτέρεως loco",
    "spr-lb-fm-0020-05": "πτέριδος, nisi ex aetate proficisci possunt, qua lingua graeca",
    "spr-lb-fm-0020-06": "jam βαρβαροφωνεῖν coeperat.",
    "spr-lb-fm-0020-18": "rum. Etenim de eo testatur Galenus, πλῆθος ὀνομάτων",
    "spr-lb-fm-0020-19": "ἐφ' ἑκάστῃ βοτάνῃ μάτην προστιθέντα, fabulas de trans-",
    "spr-lb-fm-0020-25": "nunquam eadem recepit ",
    "spr-lb-fm-0020-26": "quandoque repetunt; neque adjunctae sunt nostris sy-",
    "spr-lb-fm-0021-04": "μακοποιὸν ἔθνος appellaverat ",
    "spr-lb-fm-0031-08": "ceptus editionibus, p. 131. 183. 172. κελύφῳ et κελύφοις",
    "spr-lb-fm-0031-09": "scripsi, ubi κελύφει et κελύφεσι ponendum est. P. 192.",
    "spr-lb-fm-0031-10": "Βουπρήστου scripsi, quemadmodum omnes editiones,",
    "spr-lb-fm-0031-11": "loco Βουπρήστεως.",
    "spr-lb-fm-0031-13": "p. 11. lin. 7. ὄξει loco ὄξῳ,",
    "spr-lb-fm-0031-20": "et plerisque locis Ἀφροί falso scripsi, cum ex Aldina",
    "spr-lb-fm-0031-22": "rexi. P. 10. 12. 20. γλῶτταν legendum: p. 120. 203.",
    "spr-lb-fm-0031-23": "204. 205. 110. λίπος: p. 137. ὀμφακῖτις: p. 243. κε-",
    "spr-lb-fm-0031-24": "ραῗτις: p. 283. μυῗτις: p. 327. νυκτερῖτις, ἀερῖτις, αἰγῖτις,",
    "spr-lb-fm-0031-25": "πελαγῖτις: p. 344. δακτυλῖτις: p. 129. Ἄγνος: p. 153.",
    "spr-lb-fm-0031-26": "ἰχώρ: p. 296. τοίχων: p. 321. Ἰβηρίς.",
}
ELEMENT_TEXT_REPLACEMENTS = {
    "spr-app-fm-0020-32": "Comm. de bibl. Vindob. lib. 2. p. 593.",
    "spr-app-fm-0020-35": (
        "De prophetis Aegyptiorum cf. Clem. Alex. strom. 1. p. 305.\n"
        "Porphyr. de abstinent. p. 321. Aristid. orat. vol. 3. p. 553."
    ),
}
TARGET_TAIL_REPLACEMENTS = {
    "#spr-app-fm-0018-28": {"; dein et κάκτος et στρύχνον μανικὸν ἢ δορύκνιον,": "; dein et κάκτος et στρύχνον μανικὸν ὅ δορύκνιον,"},
    "#spr-app-fm-0020-34": {"Aetius": "Aëtius"},
}

GREEK_HEAD_RE = re.compile(r"Κε[φπ]\.\s*([^.\[]+)\.?\s*(?:\([^)]+\)\.?\s*)?\[([^\]]+)\]?")
MALFORMED_GREEK_HEAD_REF_RE = re.compile(r"^(?P<prefix>.*\S)\[(?P<label>\d+[a-z]?)\]\s*$", re.IGNORECASE)
LATIN_CAP_RE = re.compile(
    r"Cap\.\s+([IVXLCDM]+)\.?\s*(?:\([^)]+\)\.?\s*)?\[([^\]]+)\]",
    re.IGNORECASE,
)
LATIN_BRACKETED_CAP_RE = re.compile(r"\[Cap\.\s+([IVXLCDM]+)\.?\s+([^\]]+)\]", re.IGNORECASE)
GREEK_PAREN_TITLE_RE = re.compile(r"^\s*(\([^)]+\)\.?)\s*\[([^\]]+)\]?")
GREEK_BROKEN_TITLE_RE = re.compile(r"^\s*(Περὶ[^\]]+)\]\.?\s*")
APPARATUS_SPLIT_RE = re.compile(r"(?:^|\s+)(\d+\s*[a-z]?)\)\s+", re.IGNORECASE)
NOTE_LABEL_RE = re.compile(r"^\[(\d+[a-z]?)\]$", re.IGNORECASE)
FRONT_SUBSECTION_PREFIX_RE = re.compile(r"^\s*([A-Z]+|[IVXLCDM]+)\.")
BOOK_1_UNHEADED_CHAPTER_STARTS = {
    "spr-lb-1-0170-12": ("147", "Ῥοῦς ὁ ἐπὶ τὰ ὄψα", "Περὶ Ῥοῦ"),
    "spr-lb-1-0171-17": ("148", "Φοῖνιξ ἐν Αἰγύπτῳ", "Περὶ Φοίνικος"),
    "spr-lb-1-0172-13": ("149", "Τῶν δὲ θηβαϊκῶν", "Περὶ θηβαϊκῶν φοινίκων"),
    "spr-lb-1-0173-12": ("150", "Φοῖνιξ, ἣν ἔνιοι ἐλάτην ἢ σπάθην καλοῦσι", "Περὶ σπάθης φοίνικος"),
    "spr-lb-1-0174-15": ("151", "Ῥόα πᾶσα", "Περὶ Ῥόας"),
}
BOOK_1_GREEK_OCR_CHAPTER_OVERRIDES = {
    "Περὶ Πισσελαίου": "95",
    "Περὶ λιγνύος τῆς ἐξ ὑγρᾶς πίσσης": "96",
    "Περὶ ξηρᾶς πίσσης": "97",
    "Περὶ ζωπίσσης": "98",
    "Περὶ ἀσφάλτου": "99",
}
BOOK_2_GREEK_LOGICAL_CHAPTER_OVERRIDES = {
    "Περὶ ὀῤῥοῦ γάλακτος": "76",
    "Περὶ σχιστοῦ γάλακτος": "77",
    "Περὶ Πιτύας": "85",
    "Περὶ Στέατος": "86",
    "Πῶς τὸ στέαρ ἀρωματιστεῖον": "91",
    "Πῶς σαμψυχίζεται τὸ στέαρ": "92",
    "Περὶ Αἱμάτων": "97",
    "Περὶ Ἀποπάτου": "98",
    "Περὶ Οὔρων": "99",
    "Περὶ Παγκρατίου": "203",
    "Περὶ Καππάρεως": "204",
    "Περὶ Λεπιδίου": "205",
}
BOOK_2_LATIN_LOGICAL_CHAPTER_OVERRIDES = {
    "De Isatide sylvestri": "216",
}
BOOK_3_GREEK_LOGICAL_CHAPTER_OVERRIDES = {
    "Περὶ Καλαμίνθης": "37",
    "Περὶ Θύμου": "38",
    "Περὶ Θύμβρας": "39",
    "Περὶ Ἑρπύλλου": "40",
    "Περὶ Σαμψύχου": "41",
    "Περὶ Μάρου": "42",
    "Περὶ Ἀκίνου": "43",
    "Περὶ Βακχάρεως": "44",
    "Περὶ Πηγάνου": "45",
    "Περὶ Πηγάνου ἀγρίου": "46",
    "Περὶ Μώλυος": "47",
    "Περὶ Πάνακος": "48",
    "Περὶ Πάνακος Ἀσκληπιοῦ": "49",
    "Περὶ Πάνακος Χειρωνίου": "50",
    "Περὶ Λιγυστικοῦ": "51",
    "Περὶ Σταφυλίνου": "52",
    "Περὶ Σεσελέως μασσαλεωτικοῦ": "53",
    "Περὶ Κυμίνου ἀγρίου": "62",
}
BOOK_3_LATIN_LOGICAL_CHAPTER_OVERRIDES = {
    "De Calamintha": "37",
    "De Thymo": "38",
    "De Thymbra": "39",
    "De Serpyllo": "40",
    "De Maiorana": "41",
    "De Maro": "42",
    "De Acino": "43",
    "De Bacchare": "44",
    "De Ruta": "45",
    "De ruta sylvestri": "46",
    "De Moly": "47",
    "De Panace Heracleo": "48",
    "De Panace Asclepio": "49",
    "De Panace Chironio": "50",
    "De Ligustico": "51",
    "De Dauco sylvestri": "52",
    "De Seseli massiliensi": "53",
    "De Cymino sylvatico": "62",
}
# These printed markers stay in the inline diplomatic text, but they should not
# mint standalone navigation milestones in the reviewed Book 3 sequence.
BOOK_3_SUPPRESSED_GREEK_CHAPTER_MARKERS = {
    "spr-ch-3.5",
    "spr-ch-3.6",
    "spr-ch-3.38",
    "spr-ch-3.39",
    "spr-ch-3.42",
    "spr-ch-3.48",
}
BOOK_3_SUPPRESSED_LATIN_LABELS = {"De Meliloto"}
BOOK_3_UNHEADED_CHAPTER_STARTS = {
    "spr-lb-3-0435-12": ("54", "Τὸ δὲ αἰθιοπικὸν λεγόμενον σέσελι", "Περὶ σεσέλεως αἰθιοπικοῦ"),
    "spr-lb-3-0436-04": ("55", "Τὸ δὲ ἐν Πελοποννήσῳ γεννώμενον", "Περὶ σεσέλεως πελοποννησιακοῦ"),
    "spr-lb-3-0436-11": ("56", "Τορδύλεον, οἱ δὲ τόρδυλον", "Περὶ Τορδυλείου"),
    "spr-lb-3-0437-06": ("57", "Σίσων σπερμάτιόν ἐστι", "Περὶ Σίσωνος"),
    "spr-lb-3-0437-12": ("58", "Ἄνισον", "Περὶ Ἀνίσου"),
    "spr-lb-3-0438-07": ("59", "Κάρος σπερμάτιόν ἐστι", "Περὶ Κάρου"),
    "spr-lb-3-0438-12": ("60", "Ἄνηθον τὸ ἐσθιόμενον", "Περὶ Ἀνήθου"),
    "spr-lb-3-0439-07": ("61", "Κύμινον τὸ ἥμερον", "Περὶ Κυμίνου"),
}
GREEK_NUMERAL_VALUES = {
    "α": 1,
    "β": 2,
    "γ": 3,
    "δ": 4,
    "ε": 5,
    "ϛ": 6,
    "ς": 6,
    "ζ": 7,
    "η": 8,
    "θ": 9,
    "ι": 10,
    "κ": 20,
    "λ": 30,
    "μ": 40,
    "ν": 50,
    "ξ": 60,
    "ο": 70,
    "π": 80,
    "ϟ": 90,
    "ϙ": 90,
    "ρ": 100,
    "σ": 200,
    "τ": 300,
    "υ": 400,
    "φ": 500,
    "χ": 600,
    "ψ": 700,
    "ω": 800,
    "ϡ": 900,
}


@dataclass(frozen=True)
class ChapterMarker:
    lang: str
    key: str
    label: str = ""
    raw_label: str = ""
    inline_title: str = ""


@dataclass(frozen=True)
class HeadingDecision:
    canonical_n: str = ""
    display_label: str = ""
    source_label_policy: str = ""
    decision_note: str = ""


@dataclass
class Page:
    facs: str
    n: str
    xml_id: str
    index: int
    front_section: str = ""
    front_section_title: str = ""
    front_subsection: str = ""
    front_subsection_title: str = ""
    book: str = ""
    zones: dict[str, list[ET.Element | ChapterMarker]] = field(
        default_factory=lambda: {"grc": [], "la": [], "commentary": [], "front": []}
    )
    chapter_starts: dict[str, list[str]] = field(default_factory=lambda: {"grc": [], "la": []})


@dataclass
class Chapter:
    key: str
    book: str
    chapter: str
    labels: dict[str, str] = field(default_factory=dict)
    raw_labels: dict[str, str] = field(default_factory=dict)
    pages: dict[str, str] = field(default_factory=dict)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def attr(element: ET.Element, name: str) -> str:
    if name == "xml:id":
        return element.get(XML_ID) or element.get("xml:id") or ""
    if name == "xml:lang":
        return element.get(XML_LANG) or element.get("xml:lang") or ""
    return element.get(name) or ""


def text_content(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def lb_number(element: ET.Element) -> int | None:
    value = attr(element, "n")
    if not value or not value.isdigit():
        return None
    return int(value)


def paragraph_line_range(
    paragraph: ET.Element,
    include_line: Callable[[int | None], bool],
) -> ET.Element | None:
    clone = copy.copy(paragraph)
    clone.text = paragraph.text if include_line(None) else None
    clone.tail = paragraph.tail
    for child in list(clone):
        clone.remove(child)

    current_line: int | None = None
    kept = bool(clone.text and clone.text.strip())
    for child in list(paragraph):
        if local_name(child.tag) == "lb":
            current_line = lb_number(child)
        if include_line(current_line):
            clone.append(copy.deepcopy(child))
            kept = True

    if not kept:
        return None
    return clone


def normalize_chapter_label_text(text: str, lang: str) -> str:
    text = " ".join(text.split()).strip()
    if lang == "grc":
        match = MALFORMED_GREEK_HEAD_REF_RE.match(text)
        if match and "[Περὶ" in match.group("prefix"):
            return match.group("prefix").rstrip(" .") + ".]"
    return text


def clean_label(text: str, lang: str) -> str:
    text = normalize_chapter_label_text(text, lang)
    if lang == "grc":
        match = GREEK_HEAD_RE.search(text)
        if match:
            return match.group(2).replace("[", "").strip(" .")
        return re.sub(r"^Κε[φπ]\.\s*[^.]+\.?\s*", "", text).strip(" .")
    match = LATIN_CAP_RE.search(text)
    if match:
        return match.group(2).strip(" .")
    match = LATIN_BRACKETED_CAP_RE.search(text)
    if match:
        return match.group(2).strip(" .")
    return re.sub(r"^Cap\.\s*[-IVXLCDM().]+\s*", "", text, flags=re.I).strip(" .")


def class_token(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def front_subsection_key(section: str, title: str, counts: defaultdict[str, int]) -> str:
    match = FRONT_SUBSECTION_PREFIX_RE.match(title)
    base = match.group(1).lower() if match else class_token(title)[:40]
    base = class_token(base) or "section"
    key = f"{section}-{base}"
    counts[key] += 1
    return key if counts[key] == 1 else f"{key}-{counts[key]}"


def roman_to_int(value: str) -> int | None:
    roman = value.upper().strip()
    if not re.fullmatch(r"[IVXLCDM]+", roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for index, char in enumerate(roman):
        current = values[char]
        next_value = values.get(roman[index + 1], 0) if index + 1 < len(roman) else 0
        total += -current if current < next_value else current
    return total


def normalized_chapter_label(raw_label: str, lang: str) -> str:
    return clean_label(raw_label, lang).replace("  ", " ").strip()


def heading_decision_key(book: str, lang: str, label: str) -> tuple[str, str, str]:
    return (book, lang, normalized_chapter_label(label, lang))


def load_heading_decisions(path: Path | None) -> dict[tuple[str, str, str], HeadingDecision]:
    if path is None or not path.exists():
        return {}
    decisions: dict[tuple[str, str, str], HeadingDecision] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            canonical_n = (row.get("canonical_n") or "").strip()
            if not canonical_n:
                continue
            book = (row.get("book") or "").strip()
            lang = (row.get("lang") or "").strip()
            if not book or lang not in {"grc", "la"}:
                continue
            decision = HeadingDecision(
                canonical_n=canonical_n,
                display_label=(row.get("display_label") or "").strip(),
                source_label_policy=(row.get("source_label_policy") or "").strip(),
                decision_note=(row.get("decision_note") or "").strip(),
            )
            for value in (
                row.get("display_label") or "",
                row.get("heading_label") or "",
                row.get("source_heading_text") or "",
            ):
                key = heading_decision_key(book, lang, value)
                if key[2]:
                    decisions[key] = decision
    return decisions


def parse_greek_chapter_number(text: str) -> int | None:
    match = GREEK_HEAD_RE.search(text)
    if not match:
        return None
    numeral = match.group(1).split("(", 1)[0].strip()
    numeral = re.split(r"\s+", numeral, maxsplit=1)[0]
    numeral = unicodedata.normalize("NFD", numeral.lower())
    numeral = "".join(char for char in numeral if unicodedata.category(char) != "Mn")
    numeral = re.sub(r"[.'’ʻʼ`´΄ʹʹ᾽᾿]+", "", numeral)
    if numeral == "στ":
        return 6
    total = 0
    for char in numeral:
        if char in {" ", "-", "‐", "‑"}:
            continue
        value = GREEK_NUMERAL_VALUES.get(char)
        if value is None:
            return None
        total += value
    return total or None


def greek_head_raw_label(text: str) -> str:
    match = GREEK_HEAD_RE.search(text)
    return match.group(0).strip() if match else ""


def chapter_key_sort_key(key: str) -> tuple[int, int | str]:
    book, _, chapter = key.partition(".")
    book_key = int(book) if book.isdigit() else 999
    chapter_key: int | str = int(chapter) if chapter.isdigit() else chapter
    return book_key, chapter_key


def archive_scan_number(facs: str, fallback_index: int) -> int:
    match = re.search(r"page-(\d{4})\.(?:png|jpe?g|jp2)$", facs)
    return int(match.group(1)) if match else fallback_index


def archive_page_url(archive_id: str, scan_number: int) -> str:
    return f"https://archive.org/details/{archive_id}/page/n{max(0, scan_number - 1)}/mode/1up"


def archive_iiif_image_url(archive_id: str, scan_number: int, width: int) -> str:
    path = (
        f"{archive_id}%2F{archive_id}_jp2.zip%2F"
        f"{archive_id}_jp2%2F{archive_id}_{scan_number:04d}.jp2"
    )
    return f"https://iiif.archive.org/image/iiif/3/{path}/full/{width},/0/default.jpg"


def image_name(facs: str, fallback_index: int) -> str:
    return Path(facs).name if facs else f"page-{fallback_index:04d}.png"


def first_page_break(element: ET.Element) -> ET.Element | None:
    for child in element.iter():
        if local_name(child.tag) == "pb":
            return child
    return None


def copy_without_page_breaks(element: ET.Element) -> ET.Element | None:
    if local_name(element.tag) == "pb":
        return None
    clone = copy.deepcopy(element)
    for parent in list(clone.iter()):
        for child in list(parent):
            if local_name(child.tag) == "pb":
                parent.remove(child)
    return clone


def apply_text_replacements(element: ET.Element) -> None:
    element_replacement = ELEMENT_TEXT_REPLACEMENTS.get(attr(element, "xml:id"))
    if element_replacement is not None:
        element.text = element_replacement
        for child in list(element):
            element.remove(child)

    for child in element.iter():
        if child is not element:
            child_replacement = ELEMENT_TEXT_REPLACEMENTS.get(attr(child, "xml:id"))
            if child_replacement is not None:
                child.text = child_replacement
                for grandchild in list(child):
                    child.remove(grandchild)
            tail_replacements = TARGET_TAIL_REPLACEMENTS.get(attr(child, "target"))
            if child.tail and tail_replacements:
                for old, new in tail_replacements.items():
                    child.tail = child.tail.replace(old, new)
        if local_name(child.tag) != "lb":
            continue
        replacement = LINE_TEXT_REPLACEMENTS.get(attr(child, "xml:id"))
        if replacement is not None:
            child.tail = replacement + ("\n" if (child.tail or "").endswith("\n") else "")


def append_to_last_text(element: ET.Element, text: str) -> None:
    children = list(element)
    if children:
        children[-1].tail = (children[-1].tail or "") + text
    else:
        element.text = (element.text or "") + text


def materialize_text_newlines(element: ET.Element) -> None:
    if element.text and "\n" in element.text:
        parts = element.text.split("\n")
        element.text = parts[0]
        for offset, part in enumerate(parts[1:]):
            lb = ET.Element(f"{NS}lb")
            lb.tail = part
            element.insert(offset, lb)

    index = 0
    while index < len(element):
        child = element[index]
        materialize_text_newlines(child)
        if child.tail and "\n" in child.tail:
            parts = child.tail.split("\n")
            child.tail = parts[0]
            insert_at = index + 1
            for part in parts[1:]:
                lb = ET.Element(f"{NS}lb")
                lb.tail = part
                element.insert(insert_at, lb)
                insert_at += 1
            index = insert_at
        else:
            index += 1


def bracketed_synonyma(seg: ET.Element) -> ET.Element:
    clone = copy.deepcopy(seg)
    clone.text = "[" + (clone.text or "").lstrip()
    append_to_last_text(clone, "]")
    materialize_text_newlines(clone)
    return clone


def remove_leading_head_close(element: ET.Element) -> bool:
    pattern = re.compile(r"^\s*\.\]\s*")
    if element.text and pattern.match(element.text):
        element.text = pattern.sub("", element.text, count=1)
        return True
    for child in element.iter():
        if child is element:
            continue
        if child.tail and pattern.match(child.tail):
            child.tail = pattern.sub("", child.tail, count=1)
            return True
        if child.text and pattern.match(child.text):
            child.text = pattern.sub("", child.text, count=1)
            return True
    return False


def paragraph_with_synonyma_after_lemma(
    paragraph: ET.Element,
    seg: ET.Element,
    strip_leading_head_close: bool = False,
) -> tuple[ET.Element, bool]:
    clone = copy.deepcopy(paragraph)
    stripped = remove_leading_head_close(clone) if strip_leading_head_close else False
    synonyma = bracketed_synonyma(seg)

    def split_first_word(text: str) -> tuple[str, str] | None:
        match = re.match(r"(\s*\S+)(\s+.*)?$", text, flags=re.DOTALL)
        if not match:
            return None
        return match.group(1), (match.group(2) or "")

    split = split_first_word(clone.text or "")
    if split:
        first, rest = split
        clone.text = first + " "
        synonyma.tail = rest
        clone.insert(0, synonyma)
        return clone, stripped

    for index, child in enumerate(list(clone)):
        split = split_first_word(child.tail or "")
        if split:
            first, rest = split
            child.tail = first + " "
            synonyma.tail = rest
            clone.insert(index + 1, synonyma)
            return clone, stripped

    clone.insert(0, synonyma)
    return clone, stripped


def inline_chapter_head(head: ET.Element) -> ET.Element:
    title = copy.deepcopy(head)
    title.tag = f"{NS}seg"
    title.attrib.clear()
    title.set("type", "chapterTitle")
    return title


def paragraph_with_inline_head(
    paragraph: ET.Element,
    head: ET.Element,
    strip_leading_head_close: bool = False,
    line_break_after_head: bool = False,
) -> tuple[ET.Element, bool]:
    clone = copy.deepcopy(paragraph)
    stripped = remove_leading_head_close(clone) if strip_leading_head_close else False
    title = inline_chapter_head(head)

    for index, child in enumerate(list(clone)):
        if local_name(child.tag) == "lb":
            existing_tail = child.tail or ""
            child.tail = ""
            if line_break_after_head:
                clone.insert(index + 1, title)
                continuation_lb = ET.Element(f"{NS}lb")
                continuation_lb.tail = existing_tail.lstrip()
                clone.insert(index + 2, continuation_lb)
            else:
                title.tail = " " + existing_tail.lstrip()
                clone.insert(index + 1, title)
            return clone, stripped

    existing_text = clone.text or ""
    clone.text = ""
    if line_break_after_head:
        clone.insert(0, title)
        continuation_lb = ET.Element(f"{NS}lb")
        continuation_lb.tail = existing_text.lstrip()
        clone.insert(1, continuation_lb)
    else:
        title.tail = " " + existing_text.lstrip()
        clone.insert(0, title)
    return clone, stripped


class SprengelBuilder:
    def __init__(
        self,
        source: Path,
        archive_id: str,
        iiif_width: int,
        heading_decisions: Path | None = None,
    ) -> None:
        self.source = source
        self.archive_id = archive_id
        self.iiif_width = iiif_width
        self.root = ET.parse(source).getroot()
        self.heading_decisions = load_heading_decisions(heading_decisions)
        self.pages: dict[str, Page] = {}
        self.page_order: list[str] = []
        self.chapters: dict[str, Chapter] = {}
        self.marker_counts: dict[str, int] = {}
        self.ref_id_counts: defaultdict[str, int] = defaultdict(int)
        self.ref_ids_by_target: defaultdict[str, list[str]] = defaultdict(list)
        self.front_unpaged: defaultdict[str, list[ET.Element]] = defaultdict(list)
        self.book_opening_commentary: list[ET.Element] = []
        self.source_ids = {
            element.get(XML_ID)
            for element in self.root.iter()
            if element.get(XML_ID)
        }
        self.source_targets = {
            (element.get("target") or "").lstrip("#")
            for element in self.root.iter()
            if element.get("target", "").startswith("#")
        }

    def page_for_pb(self, pb: ET.Element) -> Page:
        facs = attr(pb, "facs")
        if not facs:
            facs = f"generated-page-{len(self.page_order) + 1:04d}"
        if facs not in self.pages:
            page = Page(
                facs=facs,
                n="" if attr(pb, "n") == "None" else attr(pb, "n"),
                xml_id=attr(pb, "xml:id") or f"spr-pb-{len(self.page_order) + 1:04d}",
                index=len(self.page_order) + 1,
            )
            self.pages[facs] = page
            self.page_order.append(facs)
        else:
            page = self.pages[facs]
            if not page.n and attr(pb, "n") and attr(pb, "n") != "None":
                page.n = attr(pb, "n")
        return page

    def chapter_for(self, book: str, chapter: str) -> Chapter:
        key = f"{book}.{chapter}"
        if key not in self.chapters:
            self.chapters[key] = Chapter(key=key, book=book, chapter=chapter)
        return self.chapters[key]

    def add_chapter_start(
        self,
        page: Page,
        lang: str,
        book: str,
        chapter: str,
        raw_label: str,
        display_label: str = "",
        inline_title: str = "",
    ) -> ChapterMarker:
        normalized_chapter = str(int(chapter)) if chapter.isdigit() else chapter
        chapter_record = self.chapter_for(book, normalized_chapter)
        raw_label = normalize_chapter_label_text(raw_label, lang)
        label = display_label or clean_label(raw_label, lang)
        decision = self.heading_decision(book, lang, raw_label)
        if decision and decision.display_label:
            label = decision.display_label
        if label and lang not in chapter_record.labels:
            chapter_record.labels[lang] = label
        if raw_label and lang not in chapter_record.raw_labels:
            chapter_record.raw_labels[lang] = " ".join(raw_label.split())
        chapter_record.pages[lang] = page.facs
        if chapter_record.key not in page.chapter_starts[lang]:
            page.chapter_starts[lang].append(chapter_record.key)
        return ChapterMarker(
            lang=lang,
            key=chapter_record.key,
            label=label,
            raw_label=" ".join(raw_label.split()) if raw_label else "",
            inline_title=inline_title.format(n=chapter_record.key, label=label) if inline_title else "",
        )

    def printed_chapter_number(self, lang: str, raw_label: str) -> str:
        if lang == "grc":
            number = parse_greek_chapter_number(raw_label)
            return str(number) if number is not None else ""
        match = LATIN_CAP_RE.search(raw_label)
        if match:
            number = roman_to_int(match.group(1))
            return str(number) if number is not None else ""
        match = LATIN_BRACKETED_CAP_RE.search(raw_label)
        if match:
            number = roman_to_int(match.group(1))
            return str(number) if number is not None else ""
        return ""

    def canonical_chapter_number(
        self,
        book: str,
        lang: str,
        raw_label: str,
        fallback_chapter: str = "",
    ) -> str:
        label = normalized_chapter_label(raw_label, lang)
        decision = self.heading_decision(book, lang, raw_label)
        if decision and decision.canonical_n:
            return decision.canonical_n
        if book == "1" and lang == "grc":
            override = BOOK_1_GREEK_OCR_CHAPTER_OVERRIDES.get(label)
            if override:
                return override
        if book == "2":
            if lang == "grc":
                override = BOOK_2_GREEK_LOGICAL_CHAPTER_OVERRIDES.get(label)
                if override:
                    return override
                printed = self.printed_chapter_number(lang, raw_label)
                # This duplicated Book 2 source-id block is twenty entries behind the logical sequence.
                if fallback_chapter.isdigit() and 161 <= int(fallback_chapter) <= 179:
                    return str(int(fallback_chapter) + 20)
                if "(" in raw_label and printed:
                    return printed
                if fallback_chapter and fallback_chapter.isdigit() and "(" in raw_label:
                    return fallback_chapter
                if printed:
                    return printed
                if fallback_chapter and fallback_chapter.isdigit():
                    return fallback_chapter
            elif lang == "la":
                override = BOOK_2_LATIN_LOGICAL_CHAPTER_OVERRIDES.get(label)
                if override:
                    return override
        if book == "3":
            if lang == "grc":
                override = BOOK_3_GREEK_LOGICAL_CHAPTER_OVERRIDES.get(label)
                if override:
                    return override
            elif lang == "la":
                override = BOOK_3_LATIN_LOGICAL_CHAPTER_OVERRIDES.get(label)
                if override:
                    return override
        return self.printed_chapter_number(lang, raw_label) or fallback_chapter

    def heading_decision(self, book: str, lang: str, raw_label: str) -> HeadingDecision | None:
        label = normalized_chapter_label(raw_label, lang)
        if not label:
            return None
        return self.heading_decisions.get((book, lang, label))

    def suppress_chapter_marker(self, chapter_div: ET.Element, book: str, lang: str) -> bool:
        return (
            book == "3"
            and lang == "grc"
            and attr(chapter_div, "xml:id") in BOOK_3_SUPPRESSED_GREEK_CHAPTER_MARKERS
        )

    def suppress_latin_marker(self, book: str, raw_label: str) -> bool:
        return book == "3" and normalized_chapter_label(raw_label, "la") in BOOK_3_SUPPRESSED_LATIN_LABELS

    def enriched_greek_chapter_label(self, chapter_div: ET.Element, raw_label: str) -> str:
        if GREEK_HEAD_RE.search(raw_label):
            return raw_label
        paragraph = next((child for child in list(chapter_div) if local_name(child.tag) == "p"), None)
        if paragraph is None:
            return raw_label
        match = GREEK_PAREN_TITLE_RE.match(text_content(paragraph))
        if match:
            return f"{raw_label.rstrip()} {match.group(1)} [{match.group(2).strip()}]"
        match = GREEK_BROKEN_TITLE_RE.match(text_content(paragraph))
        if match:
            return f"{raw_label.rstrip()} [{match.group(1).strip(' .')}]"
        return raw_label

    def source_chapter_hint(self, chapter_div: ET.Element, book: str) -> str:
        source_id = attr(chapter_div, "xml:id")
        match = re.fullmatch(rf"spr-ch-{re.escape(book)}\.(\d+)", source_id)
        if match:
            return match.group(1)
        return attr(chapter_div, "n")

    def target_id_for_label(self, page: Page, book: str, label: str) -> str:
        scan_number = archive_scan_number(page.facs, page.index)
        normalized_label = re.sub(r"\s+", "", label)
        return f"spr-app-{book}-{scan_number:04d}-{normalized_label}"

    def next_ref_id(self, target_id: str) -> str:
        base = f"ref-{target_id}"
        self.ref_id_counts[base] += 1
        return base if self.ref_id_counts[base] == 1 else f"{base}-{self.ref_id_counts[base]}"

    def normalize_ref(self, ref: ET.Element, target_id: str | None = None, label: str | None = None) -> None:
        target = attr(ref, "target")
        if target_id is None and target.startswith("#"):
            target_id = target[1:]
        if not target_id or not target_id.startswith("spr-app-"):
            return

        if label is None:
            label = text_content(ref)
        label_match = NOTE_LABEL_RE.match(label.strip())
        normalized_label = label_match.group(1) if label_match else label.strip("[] ")
        if not normalized_label:
            return

        ref.set("target", f"#{target_id}")
        ref.set("type", "footnote-ref")
        ref_id = attr(ref, "xml:id")
        if not ref_id:
            ref_id = self.next_ref_id(target_id)
            ref.set(XML_ID, ref_id)
        if ref_id not in self.ref_ids_by_target[target_id]:
            self.ref_ids_by_target[target_id].append(ref_id)
        ref.text = normalized_label
        for child in list(ref):
            ref.remove(child)

    def normalize_refs_in_tree(self, element: ET.Element) -> None:
        for ref in element.iter(f"{NS}ref"):
            self.normalize_ref(ref)

    def normalize_note(self, note: ET.Element) -> ET.Element:
        materialize_text_newlines(note)
        self.normalize_refs_in_tree(note)
        note.set("type", "footnote")
        note.set("place", "bottom")
        note_id = attr(note, "xml:id")
        if note_id:
            ref_ids = self.ref_ids_by_target.get(note_id) or []
            if ref_ids:
                note.set("corresp", " ".join(f"#{ref_id}" for ref_id in ref_ids))
        return note

    def repaired_greek_head(self, head: ET.Element, page: Page, book: str) -> tuple[ET.Element, bool]:
        clone = copy.deepcopy(head)
        text = text_content(clone)
        match = MALFORMED_GREEK_HEAD_REF_RE.match(text)
        if not match or "[Περὶ" not in match.group("prefix"):
            self.normalize_refs_in_tree(clone)
            return clone, False

        label = match.group("label")
        target_id = self.target_id_for_label(page, book, label)
        clone.clear()
        clone.text = match.group("prefix").rstrip(" .")
        ref = ET.SubElement(clone, f"{NS}ref")
        self.normalize_ref(ref, target_id=target_id, label=label)
        ref.tail = ".]"
        return clone, True

    def should_break_after_inline_head(self, lang: str, book: str, chapter: str) -> bool:
        return lang == "grc" and book == "1" and chapter == "65"

    def greek_marker_for_line(
        self,
        page: Page,
        book: str,
        line: ET.Element,
        text: str,
    ) -> ChapterMarker | None:
        raw_label = greek_head_raw_label(text)
        chapter = self.canonical_chapter_number(book, "grc", raw_label) if raw_label else ""
        display_label = ""
        if not chapter and book == "1":
            override = BOOK_1_UNHEADED_CHAPTER_STARTS.get(attr(line, "xml:id"))
            if override:
                chapter, raw_label, display_label = override
        if not chapter and book == "3":
            override = BOOK_3_UNHEADED_CHAPTER_STARTS.get(attr(line, "xml:id"))
            if override:
                chapter, raw_label, display_label = override
        if not chapter:
            return None
        inline_title = "{n} {label}" if book == "3" and display_label else ""
        return self.add_chapter_start(
            page,
            "grc",
            book,
            chapter,
            raw_label,
            display_label=display_label,
            inline_title=inline_title,
        )

    def add_greek_markers_in_paragraph(
        self,
        page: Page,
        book: str,
        paragraph: ET.Element,
    ) -> list[ET.Element | ChapterMarker]:
        if local_name(paragraph.tag) != "p":
            return [paragraph]

        output: list[ET.Element | ChapterMarker] = []

        def new_paragraph() -> ET.Element:
            clone = ET.Element(paragraph.tag, dict(paragraph.attrib))
            clone.text = None
            return clone

        def paragraph_has_content(element: ET.Element) -> bool:
            return bool((element.text or "").strip() or list(element))

        current = new_paragraph()
        current.text = paragraph.text
        for child in list(paragraph):
            marker = None
            if local_name(child.tag) == "lb":
                marker = self.greek_marker_for_line(page, book, child, child.tail or "")
            if marker is not None:
                if paragraph_has_content(current):
                    output.append(current)
                output.append(marker)
                current = new_paragraph()
            child_clone = copy.deepcopy(child)
            if marker is not None and marker.inline_title:
                existing_tail = child_clone.tail or ""
                child_clone.tail = ""
                title = ET.Element(f"{NS}seg")
                title.set("type", "chapterTitle")
                title.text = marker.inline_title
                title.tail = " " + existing_tail.lstrip()
                current.append(child_clone)
                current.append(title)
            else:
                current.append(child_clone)

        if paragraph_has_content(current):
            current.tail = paragraph.tail
            output.append(current)
        return output

    def front_midpage_split(
        self,
        page: Page | None,
        head: ET.Element,
        paragraph: ET.Element | None,
    ) -> tuple[ET.Element | None, ET.Element | None] | None:
        if page is None or paragraph is None or local_name(paragraph.tag) != "p":
            return None
        rule = FRONT_MIDPAGE_HEAD_SPLITS.get((page.n, text_content(head)))
        if rule is None:
            return None
        split_start, skip_lines = rule
        prelude = paragraph_line_range(
            paragraph,
            lambda line: line is not None and line < split_start and line not in skip_lines,
        )
        remainder = paragraph_line_range(
            paragraph,
            lambda line: line is not None and line >= split_start and line not in skip_lines,
        )
        return prelude, remainder

    def collect_front(self) -> None:
        front = self.root.find(f".//{NS}front")
        if front is None:
            return
        subsection_counts: defaultdict[str, int] = defaultdict(int)
        for child in list(front):
            name = local_name(child.tag)
            section = "title_page" if name == "titlePage" else attr(child, "type") or name
            if section == "sigla":
                for node in list(child):
                    if local_name(node.tag) != "pb":
                        self.book_opening_commentary.extend(self.output_items(node))
                continue
            direct_head = child.find(f"{NS}head")
            section_title = FRONT_LABELS.get(section) or (text_content(direct_head) if direct_head is not None else "") or section
            current_subsection = ""
            current_subsection_title = ""
            current_page: Page | None = None
            saw_page = False
            children = list(child)
            index = 0
            while index < len(children):
                node = children[index]
                node_name = local_name(node.tag)
                if node_name == "pb":
                    current_page = self.page_for_pb(node)
                    current_page.front_section = section
                    current_page.front_section_title = section_title
                    current_page.front_subsection = current_subsection
                    current_page.front_subsection_title = current_subsection_title
                    saw_page = True
                    index += 1
                    continue
                if node_name == "head" and saw_page:
                    next_node = children[index + 1] if index + 1 < len(children) else None
                    split = self.front_midpage_split(current_page, node, next_node)
                    if split is not None:
                        prelude, remainder = split
                        if current_page is not None and prelude is not None:
                            current_page.zones["front"].extend(self.output_items(prelude))
                        split_title = text_content(node)
                        if split_title not in FRONT_INLINE_SUBHEADS:
                            current_subsection_title = split_title
                            current_subsection = front_subsection_key(
                                section,
                                current_subsection_title,
                                subsection_counts,
                            )
                        if current_page is not None:
                            current_page.front_subsection = current_subsection
                            current_page.front_subsection_title = current_subsection_title
                            current_page.zones["front"].extend(self.output_items(node))
                            if remainder is not None:
                                current_page.zones["front"].extend(self.output_items(remainder))
                        index += 2
                        continue
                    current_subsection_title = text_content(node)
                    current_subsection = front_subsection_key(section, current_subsection_title, subsection_counts)
                    if current_page is not None:
                        current_page.front_subsection = current_subsection
                        current_page.front_subsection_title = current_subsection_title
                if current_page is None:
                    if node_name != "head":
                        self.front_unpaged[section].extend(self.output_items(node))
                    index += 1
                    continue
                current_page.zones["front"].extend(self.output_items(node))
                index += 1

    def collect_body_language(self, language_div: ET.Element, lang: str) -> None:
        state = {
            "page": None,
            "book": "",
            "chapter": "",
            "chapter_marker_pending": False,
            "chapter_raw_label": "",
            "consume_leading_head_close": False,
            "pending_inline_head": None,
        }

        def process(node: ET.Element) -> None:
            name = local_name(node.tag)
            if name == "pb":
                page = self.page_for_pb(node)
                state["page"] = page
                if state["book"] and not page.book:
                    page.book = str(state["book"])
                return

            if name == "div":
                previous = state.copy()
                subtype = attr(node, "subtype")
                if subtype == "book":
                    state["book"] = attr(node, "n")
                    state["chapter"] = ""
                    state["chapter_marker_pending"] = False
                    for child in list(node):
                        process(child)
                elif subtype == "chapter":
                    state["chapter_marker_pending"] = True
                    head = next((child for child in list(node) if local_name(child.tag) == "head"), None)
                    state["chapter_raw_label"] = (
                        normalize_chapter_label_text(text_content(head), lang) if head is not None else ""
                    )
                    if lang == "grc" and state["chapter_raw_label"]:
                        state["chapter_raw_label"] = self.enriched_greek_chapter_label(
                            node,
                            str(state["chapter_raw_label"]),
                        )
                    state["chapter"] = (
                        self.canonical_chapter_number(
                            str(state["book"]),
                            lang,
                            str(state["chapter_raw_label"]),
                            self.source_chapter_hint(node, str(state["book"])),
                        )
                    )
                    if self.suppress_chapter_marker(node, str(state["book"]), lang):
                        state["chapter"] = ""
                    children = list(node)
                    index = 0
                    while index < len(children):
                        child = children[index]
                        if local_name(child.tag) == "head" and lang == "grc":
                            page = state["page"]
                            if page is not None and state["book"]:
                                if state["chapter_marker_pending"] and state["chapter"]:
                                    page.zones[lang].append(
                                        self.add_chapter_start(
                                            page,
                                            lang,
                                            str(state["book"]),
                                            str(state["chapter"]),
                                            str(state["chapter_raw_label"]),
                                        )
                                    )
                                    state["chapter_marker_pending"] = False
                                repaired_head, consumed = self.repaired_greek_head(child, page, str(state["book"]))
                                state["pending_inline_head"] = repaired_head
                                if consumed:
                                    state["consume_leading_head_close"] = True
                                index += 1
                                continue
                        if (
                            lang == "grc"
                            and local_name(child.tag) == "seg"
                            and attr(child, "type") == "synonyma"
                        ):
                            page = state["page"]
                            if (
                                page is not None
                                and index + 1 < len(children)
                                and local_name(children[index + 1].tag) == "p"
                            ):
                                paragraph_source = children[index + 1]
                                pending_head = state["pending_inline_head"]
                                if isinstance(pending_head, ET.Element):
                                    paragraph_source, stripped = paragraph_with_inline_head(
                                        paragraph_source,
                                        pending_head,
                                        strip_leading_head_close=bool(state["consume_leading_head_close"]),
                                        line_break_after_head=self.should_break_after_inline_head(
                                            lang,
                                            str(state["book"]),
                                            str(state["chapter"]),
                                        ),
                                    )
                                    state["pending_inline_head"] = None
                                    if stripped:
                                        state["consume_leading_head_close"] = False
                                paragraph, stripped = paragraph_with_synonyma_after_lemma(
                                    paragraph_source,
                                    child,
                                    strip_leading_head_close=bool(state["consume_leading_head_close"]),
                                )
                                if stripped:
                                    state["consume_leading_head_close"] = False
                                self.normalize_refs_in_tree(paragraph)
                                page.zones[lang].extend(
                                    self.add_greek_markers_in_paragraph(page, str(state["book"]), paragraph)
                                )
                                index += 2
                                continue
                            if page is not None:
                                synonyma = bracketed_synonyma(child)
                                self.normalize_refs_in_tree(synonyma)
                                page.zones[lang].append(synonyma)
                            index += 1
                            continue
                        if (
                            lang == "grc"
                            and isinstance(state["pending_inline_head"], ET.Element)
                            and local_name(child.tag) == "p"
                        ):
                            page = state["page"]
                            if page is not None:
                                paragraph, stripped = paragraph_with_inline_head(
                                    child,
                                    state["pending_inline_head"],
                                    strip_leading_head_close=bool(state["consume_leading_head_close"]),
                                    line_break_after_head=self.should_break_after_inline_head(
                                        lang,
                                        str(state["book"]),
                                        str(state["chapter"]),
                                    ),
                                )
                                state["pending_inline_head"] = None
                                if stripped:
                                    state["consume_leading_head_close"] = False
                                self.normalize_refs_in_tree(paragraph)
                                page.zones[lang].extend(
                                    self.add_greek_markers_in_paragraph(page, str(state["book"]), paragraph)
                                )
                                index += 1
                                continue
                        if (
                            lang == "grc"
                            and state["consume_leading_head_close"]
                            and local_name(child.tag) == "p"
                        ):
                            page = state["page"]
                            if page is not None:
                                paragraph = copy.deepcopy(child)
                                if remove_leading_head_close(paragraph):
                                    state["consume_leading_head_close"] = False
                                    self.normalize_refs_in_tree(paragraph)
                                    page.zones[lang].extend(
                                        self.add_greek_markers_in_paragraph(page, str(state["book"]), paragraph)
                                    )
                                    index += 1
                                    continue
                        process(child)
                        index += 1
                else:
                    for child in list(node):
                        process(child)
                state.update(previous)
                return

            page = state["page"]
            if page is None:
                return
            if state["book"] and not page.book:
                page.book = str(state["book"])

            if lang == "grc" and state["chapter_marker_pending"] and state["book"] and state["chapter"]:
                page.zones[lang].append(
                    self.add_chapter_start(
                        page,
                        lang,
                        str(state["book"]),
                        str(state["chapter"]),
                        str(state["chapter_raw_label"]),
                    )
                )
                state["chapter_marker_pending"] = False

            if lang == "la":
                raw_text = text_content(node)
                matches = list(LATIN_CAP_RE.finditer(raw_text)) + list(LATIN_BRACKETED_CAP_RE.finditer(raw_text))
                matches.sort(key=lambda match: match.start())
                for match in matches:
                    chapter_num = roman_to_int(match.group(1))
                    if chapter_num and state["book"]:
                        raw_label = match.group(0)
                        if self.suppress_latin_marker(str(state["book"]), raw_label):
                            continue
                        page.zones[lang].append(
                            self.add_chapter_start(
                                page,
                                lang,
                                str(state["book"]),
                                self.canonical_chapter_number(
                                    str(state["book"]),
                                    lang,
                                    raw_label,
                                    str(chapter_num),
                                ),
                                raw_label,
                            )
                        )

            items = self.output_items(node)
            if lang == "grc" and state["book"] and local_name(node.tag) == "p":
                marked_items: list[ET.Element | ChapterMarker] = []
                for item in items:
                    if isinstance(item, ET.Element):
                        marked_items.extend(self.add_greek_markers_in_paragraph(page, str(state["book"]), item))
                    else:
                        marked_items.append(item)
                items = marked_items
            page.zones[lang].extend(items)

        for child in list(language_div):
            process(child)

    def split_apparatus_note(self, note: ET.Element) -> list[ET.Element]:
        original_id = attr(note, "xml:id")
        original_n = attr(note, "n")
        text = text_content(note)
        matches = list(APPARATUS_SPLIT_RE.finditer(text))
        if not matches or not original_id:
            return [note]

        pieces: list[tuple[str, str]] = [(original_n, text[: matches[0].start()].strip())]
        for index, match in enumerate(matches):
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            pieces.append((match.group(1), text[match.end() : next_start].strip()))

        output = []
        for index, (number, piece_text) in enumerate(pieces):
            if not piece_text:
                continue
            if index == 0:
                clone = copy.deepcopy(note)
                clone.text = piece_text
                for child in list(clone):
                    clone.remove(child)
                output.append(clone)
                continue

            normalized_number = re.sub(r"\s+", "", number)
            if original_n:
                generated_id = re.sub(r"-\d+[a-z]?$", f"-{normalized_number}", original_id, flags=re.IGNORECASE)
            else:
                generated_id = f"{original_id}-{normalized_number}"
            if generated_id not in self.source_targets or generated_id in self.source_ids:
                continue
            clone = copy.deepcopy(note)
            clone.set("n", normalized_number)
            clone.set(XML_ID, generated_id)
            clone.text = piece_text
            for child in list(clone):
                clone.remove(child)
            output.append(clone)
        return output

    def output_items(self, element: ET.Element) -> list[ET.Element]:
        clone = copy_without_page_breaks(element)
        if clone is None:
            return []
        apply_text_replacements(clone)
        if local_name(clone.tag) == "note" and attr(clone, "type") == "apparatus":
            notes = self.split_apparatus_note(clone)
            output = []
            for note in notes:
                note_id = attr(note, "xml:id")
                match = re.match(r"(.+-)(\d+)[a-z]$", note_id, flags=re.IGNORECASE)
                if match:
                    alias_id = f"{match.group(1)}{match.group(2)}"
                    if alias_id in self.source_targets and alias_id not in self.source_ids:
                        alias = copy.deepcopy(note)
                        alias.set(XML_ID, alias_id)
                        alias.set("n", match.group(2))
                        output.append(self.normalize_note(alias))
                output.append(self.normalize_note(note))
            return output
        self.normalize_refs_in_tree(clone)
        return [clone]

    def collect_body(self) -> None:
        body = self.root.find(f".//{NS}body")
        if body is None:
            return
        for div in body.findall(f"{NS}div"):
            div_type = attr(div, "type")
            lang = attr(div, "xml:lang")
            if div_type == "edition" and lang == "grc":
                self.collect_body_language(div, "grc")
            elif div_type == "translation" and lang == "la":
                self.collect_body_language(div, "la")
        self.resolve_missing_apparatus_targets()
        self.attach_book_opening_commentary()

    def attach_book_opening_commentary(self) -> None:
        if not self.book_opening_commentary:
            return
        first_book_page = next(
            (
                self.pages[facs]
                for facs in self.page_order
                if self.pages[facs].book == "1" and self.pages[facs].n == "1"
            ),
            None,
        )
        if first_book_page is None:
            return
        first_book_page.zones["commentary"].extend(copy.deepcopy(self.book_opening_commentary))

    def resolve_missing_apparatus_targets(self) -> None:
        known_ids = set(self.source_ids)
        for page in self.pages.values():
            for items in page.zones.values():
                for item in items:
                    if isinstance(item, ET.Element):
                        item_id = attr(item, "xml:id")
                        if item_id:
                            known_ids.add(item_id)
                        for child in item.iter():
                            child_id = attr(child, "xml:id")
                            if child_id:
                                known_ids.add(child_id)

        created: set[str] = set()
        for page in self.pages.values():
            for items in page.zones.values():
                missing_for_zone = []
                seen_missing_for_zone = set()
                for item in items:
                    if not isinstance(item, ET.Element):
                        continue
                    for ref in item.iter(f"{NS}ref"):
                        target = attr(ref, "target")
                        if not target.startswith("#"):
                            continue
                        target_id = target[1:]
                        if (
                            target_id in known_ids
                            or target_id in created
                            or target_id in seen_missing_for_zone
                            or not target_id.startswith("spr-app-")
                        ):
                            continue
                        missing_for_zone.append((target_id, text_content(ref).strip("[] ")))
                        seen_missing_for_zone.add(target_id)
                for target_id, label in missing_for_zone:
                    note = ET.Element(
                        f"{NS}note",
                        {
                            "type": "footnote",
                            "subtype": "missing-source-note",
                            "place": "bottom",
                        },
                    )
                    if label:
                        note.set("n", label)
                    note.set(XML_ID, target_id)
                    ref_ids = self.ref_ids_by_target.get(target_id) or []
                    if ref_ids:
                        note.set("corresp", " ".join(f"#{ref_id}" for ref_id in ref_ids))
                    note.text = "Apparatus note missing from source import."
                    items.append(note)
                    created.add(target_id)

    def marker_element(self, marker: ChapterMarker) -> ET.Element:
        chapter = self.chapters[marker.key]
        other_lang = "la" if marker.lang == "grc" else "grc"
        id_base = f"spr-ch-{chapter.key}-{marker.lang}"
        marker_count = self.marker_counts.get(id_base, 0) + 1
        self.marker_counts[id_base] = marker_count
        element = ET.Element(f"{NS}milestone")
        element.set("unit", "chapter")
        element.set("type", "chapterStart")
        element.set("n", chapter.key)
        element.set(XML_ID, id_base if marker_count == 1 else f"{id_base}-{marker_count}")
        element.set(XML_LANG, marker.lang)
        label = marker.label or chapter.labels.get(marker.lang, "")
        raw_label = marker.raw_label or chapter.raw_labels.get(marker.lang, "")
        if label:
            element.set("label", label)
        if raw_label:
            element.set("sourceLabel", raw_label)
        if chapter.labels.get(other_lang):
            element.set("pairedLabel", chapter.labels[other_lang])
        if chapter.raw_labels.get(other_lang):
            element.set("pairedSourceLabel", chapter.raw_labels[other_lang])
        if chapter.pages.get(other_lang):
            element.set("corresp", f"#spr-ch-{chapter.key}-{other_lang}")
        return element

    def append_front_page(self, parent: ET.Element, page: Page) -> None:
        page_div = ET.SubElement(parent, f"{NS}div", {"type": "page", "subtype": "diplomatic-page", "n": page.n})
        page_div.set("facs", page.facs)
        page_div.set(XML_ID, f"spr-page-{page.index:04d}")
        pb = ET.SubElement(page_div, f"{NS}pb")
        if page.n:
            pb.set("n", page.n)
        pb.set("facs", page.facs)
        pb.set(XML_ID, page.xml_id)
        zone = ET.SubElement(page_div, f"{NS}ab", {"type": "pageZone", "place": "full"})
        zone.set(XML_LANG, "la")
        self.append_zone_items(zone, page.zones["front"])

    def append_zone_items(self, parent: ET.Element, items: list[ET.Element | ChapterMarker]) -> None:
        for item in items:
            if isinstance(item, ChapterMarker):
                parent.append(self.marker_element(item))
            else:
                parent.append(item)

    def append_body_page(self, parent: ET.Element, page: Page) -> None:
        page_div = ET.SubElement(parent, f"{NS}div", {"type": "page", "subtype": "diplomatic-page", "n": page.n})
        page_div.set("facs", page.facs)
        page_div.set(XML_ID, f"spr-page-{page.index:04d}")
        pb = ET.SubElement(page_div, f"{NS}pb")
        if page.n:
            pb.set("n", page.n)
        pb.set("facs", page.facs)
        pb.set(XML_ID, page.xml_id)
        for lang, place in (("grc", "top"), ("commentary", "commentary"), ("la", "bottom")):
            if not page.zones[lang]:
                continue
            zone = ET.SubElement(page_div, f"{NS}ab", {"type": "pageZone", "place": place})
            zone.set(XML_LANG, "la" if lang == "commentary" else lang)
            if page.book == "1" and page.n == "1" and lang == "grc":
                ET.SubElement(zone, f"{NS}head").text = BOOK_1_GREEK_TITLE
                ET.SubElement(zone, f"{NS}head").text = BOOK_1_PROEM_TITLE
            elif page.book == "1" and page.n == "1" and lang == "la":
                ET.SubElement(zone, f"{NS}head").text = BOOK_1_LATIN_TITLE
            self.renumber_zone_lines(page.zones[lang])
            self.append_zone_items(zone, page.zones[lang])

    def renumber_zone_lines(self, items: list[ET.Element | ChapterMarker]) -> None:
        line_number = 1

        def renumber_element(element: ET.Element, in_note: bool = False) -> None:
            nonlocal line_number
            element_in_note = in_note or local_name(element.tag) == "note"
            if local_name(element.tag) == "lb" and not element_in_note:
                element.set("n", str(line_number))
                line_number += 1
            for child in list(element):
                renumber_element(child, element_in_note)

        for item in items:
            if not isinstance(item, ET.Element):
                continue
            renumber_element(item)

    def build_tei(self) -> ET.ElementTree:
        self.collect_front()
        self.collect_body()
        self.marker_counts = {}

        tei = ET.Element(f"{NS}TEI")
        header = self.root.find(f"{NS}teiHeader")
        if header is not None:
            tei.append(copy.deepcopy(header))

        text = ET.SubElement(tei, f"{NS}text")
        front = ET.SubElement(text, f"{NS}front")
        for section, label in FRONT_LABELS.items():
            section_pages = [self.pages[facs] for facs in self.page_order if self.pages[facs].front_section == section]
            unpaged_items = self.front_unpaged.get(section, [])
            if not section_pages and not unpaged_items:
                continue
            div = ET.SubElement(front, f"{NS}div", {"type": section, "n": section})
            div.set(XML_ID, f"spr-front-{class_token(section)}")
            ET.SubElement(div, f"{NS}head").text = label
            current_subsection = ""
            subsection_div: ET.Element | None = None
            for page in section_pages:
                if page.front_subsection:
                    if page.front_subsection != current_subsection:
                        subsection_n = page.front_subsection.replace(f"{section}-", "", 1)
                        subsection_div = ET.SubElement(
                            div,
                            f"{NS}div",
                            {"type": section, "subtype": "front-subsection", "n": subsection_n},
                        )
                        subsection_div.set(XML_ID, f"spr-front-{page.front_subsection}")
                        ET.SubElement(subsection_div, f"{NS}head").text = page.front_subsection_title
                        current_subsection = page.front_subsection
                    self.append_front_page(subsection_div if subsection_div is not None else div, page)
                else:
                    current_subsection = ""
                    subsection_div = None
                    self.append_front_page(div, page)
            if unpaged_items:
                ab = ET.SubElement(div, f"{NS}ab", {"type": "unpaged"})
                self.append_zone_items(ab, unpaged_items)

        body = ET.SubElement(text, f"{NS}body")
        edition = ET.SubElement(
            body,
            f"{NS}div",
            {
                "type": "edition",
                "subtype": "diplomatic",
                "n": "urn:cts:greekLit:tlg0656.tlg001.sprengel-diplomatic",
            },
        )
        body_pages = [self.pages[facs] for facs in self.page_order if self.pages[facs].book]
        for book in ["1", "2", "3", "4", "5"]:
            book_pages = [page for page in body_pages if page.book == book]
            if not book_pages:
                continue
            book_div = ET.SubElement(edition, f"{NS}div", {"type": "textpart", "subtype": "book", "n": book})
            ET.SubElement(book_div, f"{NS}head").text = (
                f"{BOOK_1_GREEK_TITLE} {BOOK_1_LATIN_TITLE}" if book == "1" else f"Book {book}"
            )
            for page in book_pages:
                if book == "1" and page.n == "1":
                    proem_div = ET.SubElement(
                        book_div,
                        f"{NS}div",
                        {"type": "textpart", "subtype": "proem", "n": "prooimion"},
                    )
                    proem_div.set(XML_ID, "spr-book-1-prooimion")
                    ET.SubElement(proem_div, f"{NS}head").text = BOOK_1_PROEM_TITLE
                    self.append_body_page(proem_div, page)
                else:
                    self.append_body_page(book_div, page)

        ET.indent(tei, space="  ")
        return ET.ElementTree(tei)

    def build_manifest(self) -> dict:
        pages = []
        for fallback_index, facs in enumerate(self.page_order, start=1):
            page = self.pages[facs]
            scan_number = archive_scan_number(facs, fallback_index)
            section = page.front_section or (f"book {page.book}" if page.book else "")
            chapter_keys = sorted(
                {key for starts in page.chapter_starts.values() for key in starts},
                key=chapter_key_sort_key,
            )
            pages.append(
                {
                    "pdf_page": scan_number,
                    "archive_page_n": max(0, scan_number - 1),
                    "book_page": page.n,
                    "section": section,
                    "front_section": page.front_section,
                    "front_section_title": page.front_section_title,
                    "front_subsection": page.front_subsection,
                    "front_subsection_title": page.front_subsection_title,
                    "book": page.book,
                    "chapter_starts": chapter_keys,
                    "tei_facs": facs,
                    "facs": archive_page_url(self.archive_id, scan_number),
                    "remoteImage": archive_iiif_image_url(self.archive_id, scan_number, self.iiif_width),
                    "image": image_name(facs, fallback_index),
                    "xml_id": page.xml_id,
                }
            )
        return {
            "total_pages": len(pages),
            "source": "Sprengel 1829/1830 diplomatic TEI normalized as page-first EpiDoc",
            "source_url": f"https://archive.org/details/{self.archive_id}/page/n5/mode/2up",
            "iiif_manifest": f"https://iiif.archive.org/iiif/{self.archive_id}/manifest.json",
            "image_root": f"https://iiif.archive.org/image/iiif/3/{self.archive_id}/",
            "iiif_width": self.iiif_width,
            "pages": pages,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--archive-id", default=ARCHIVE_ID)
    parser.add_argument("--iiif-width", type=int, default=1200)
    parser.add_argument(
        "--heading-decisions",
        type=Path,
        default=Path("output/sprengel_heading_audit/heading_decisions.csv"),
        help="Optional reviewed heading decisions CSV.",
    )
    args = parser.parse_args()

    builder = SprengelBuilder(args.source, args.archive_id, args.iiif_width, args.heading_decisions)
    tei = builder.build_tei()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    tei.write(args.output, encoding="utf-8", xml_declaration=True)
    args.manifest.write_text(
        json.dumps(builder.build_manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
