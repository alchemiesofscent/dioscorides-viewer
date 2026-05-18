"""Sprengel 1830 Commentarius migration: light normalization.

The source `editions/sprengel1830-comm/tei/edition.xml` was rebuilt by an
upstream process and already has clean TEI shape (657 chapter divs, 691
heads, 328 pbs, no MediaWiki residue). If that legacy source is absent, the
current corpus TEI is normalized in place. This migration only:

- enforces the canonical `<lb/>` standard (strip bloat attrs);
- removes `<lb/>` milestones from `<fw>` page furniture;
- moves recurring bottom signatures out of body paragraphs into `<fw>`;
- inserts missing body-line `<lb/>` milestones at the start of body
  paragraphs/headings, removes empty body-line milestones, then renumbers
  main body lines page-by-page;
- rewrites `<pb @facs>` JP2 URLs to IIIF JPEG derivatives so the viewer can
  render them (browsers cannot render JPEG 2000).
- serializes with conventional EpiDoc-style hierarchy indentation and keeps
  `<lb/>` markers line-initial at their parent depth.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from os import environ
from pathlib import Path
from urllib.parse import unquote

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    lb_not_line_initial_count,
    promote_plain_id_to_xml_id,
    serialize_with_epidoc_indentation,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "sprengel1830-comm"
NEW_ID = "sprengel1830-comm"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"
MAIN_START_TAGS = {TEI + "p", TEI + "head"}
IGNORED_LINE_CONTEXTS = {TEI + "fw", TEI + "note"}
LINE_BOUNDARY_TAGS = {
    TEI + "lb",
    TEI + "pb",
    TEI + "fw",
    TEI + "note",
    TEI + "p",
    TEI + "head",
    TEI + "div",
    TEI + "cb",
}
LINE_CONTAINER_TAGS = {TEI + "p", TEI + "head", TEI + "fw", TEI + "note"}
SIGNATURE_RE = re.compile(
    r"^(?:DIOSCORIDES\s+II\.\s+[A-Za-z ]{1,3}|[A-Z][a-z]?\s+\d+)$"
)
WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
TRAILING_NOTE_MARKER_RE = re.compile(r"(?:\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)$")
JP2_BASENAME_RE = re.compile(r"(b23982500_0002_\d{4})\.jp2", re.IGNORECASE)
SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
LINE_END_HYPHEN_RE = re.compile(r"[-‐‑‒–—](\s*)$")
CAP_PREFIX_PATTERN = (
    r"Cap\.\s+[IVXLCDM]+(?:\s*[—–-]\s*[IVXLCDM]+|\.\s*[IVXLCDM]+(?=\.|\s|$))?\.?"
)
CAP_PREFIX_RE = re.compile(rf"^\s*({CAP_PREFIX_PATTERN})\s*", re.IGNORECASE)
CAP_PREFIX_SEARCH_RE = re.compile(rf"(?:^|\s)({CAP_PREFIX_PATTERN})\s*", re.IGNORECASE)
FRAGMENT_RELATIVE_PATH = Path(
    "ocr/tlg0656.tlg001.sprengel1830-comm/v1-llm-fragments"
)
HYPHENATION_AUDIT = (
    Path("corpus")
    / "dioscorides"
    / "editions"
    / "tlg0656.tlg001.sprengel1830-comm"
    / "hyphenation_audit.tsv"
)
HEADING_AUDIT = (
    Path("corpus")
    / "dioscorides"
    / "editions"
    / "tlg0656.tlg001.sprengel1830-comm"
    / "heading_audit.tsv"
)
CLEANUP_LEDGER = (
    Path("corpus")
    / "dioscorides"
    / "editions"
    / "tlg0656.tlg001.sprengel1830-comm"
    / "cleanup_ledger.tsv"
)
CLEANUP_SUMMARY = (
    Path("corpus")
    / "dioscorides"
    / "editions"
    / "tlg0656.tlg001.sprengel1830-comm"
    / "cleanup_summary.md"
)


@dataclass
class HyphenationImportStats:
    pages_seen: int = 0
    pages_with_fragments: int = 0
    pages_missing_fragments: int = 0
    existing_cleared: int = 0
    candidates: int = 0
    matched: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    unresolved: list[dict[str, str]] = field(default_factory=list)


@dataclass
class HeadingReconciliationStats:
    chapters_seen: int = 0
    supplied_heads: int = 0
    prefixes_restored: int = 0
    already_present: int = 0
    missing_fragments: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    no_first_line: int = 0
    duplicate_head_tails_removed: int = 0
    unresolved: list[dict[str, str]] = field(default_factory=list)


@dataclass
class PageFurnitureStats:
    pages_seen: int = 0
    page_numbers_inserted: int = 0
    page_numbers_split: int = 0
    page_numbers_normalized: int = 0
    running_heads_normalized: int = 0
    empty_fws_removed: int = 0
    leaked_page_numbers_removed: int = 0
    leaked_headers_removed: int = 0
    review_rows: list[dict[str, str]] = field(default_factory=list)


def _source_path(out_path: Path) -> tuple[Path, bool]:
    legacy_path = legacy_edition_tei(LEGACY_ID)
    if legacy_path.exists():
        return legacy_path, False
    if out_path.exists():
        return out_path, True
    raise FileNotFoundError(
        f"Source Sprengel-comm TEI not found: {legacy_path} or {out_path}"
    )


def _fragment_dir() -> Path:
    data_root = environ.get("TEI_MAKER_DATA")
    if data_root:
        return Path(data_root).expanduser() / FRAGMENT_RELATIVE_PATH
    return (
        Path.home()
        / "Projects"
        / "tei-maker-data"
        / FRAGMENT_RELATIVE_PATH
    )


def _require_fragment_dir(fragment_dir: Path | None = None) -> Path:
    path = fragment_dir or _fragment_dir()
    if not path.is_dir():
        raise FileNotFoundError(
            "Sprengel Commentarius v1 LLM fragments not found. "
            f"Expected: {path}"
        )
    return path


def _pb_key(pb: etree._Element) -> tuple[str, str, str]:
    return (pb.get(XID) or "", pb.get("n") or "", pb.get("facs") or "")


def _preserve_pb_sources(root: etree._Element) -> dict[tuple[str, str, str], str]:
    sources: dict[tuple[str, str, str], str] = {}
    for pb in root.iter(TEI + "pb"):
        source = pb.get("source")
        if source:
            sources[_pb_key(pb)] = source
    return sources


def _restore_pb_sources(
    root: etree._Element,
    sources: dict[tuple[str, str, str], str],
) -> int:
    restored = 0
    for pb in root.iter(TEI + "pb"):
        if pb.get("source"):
            continue
        source = sources.get(_pb_key(pb))
        if source:
            pb.set("source", source)
            restored += 1
    return restored


def _inside(elem: etree._Element, tags: set[str]) -> bool:
    parent = elem.getparent()
    while parent is not None:
        if parent.tag in tags:
            return True
        parent = parent.getparent()
    return False


def _inside_body(elem: etree._Element) -> bool:
    return _inside(elem, {TEI + "body"})


def _is_supplied_head(elem: etree._Element) -> bool:
    return elem.tag == TEI + "head" and elem.get("type") == "supplied"


def _inside_ignored_line_context(elem: etree._Element) -> bool:
    if _inside(elem, IGNORED_LINE_CONTEXTS):
        return True
    current: etree._Element | None = elem
    while current is not None:
        if _is_supplied_head(current):
            return True
        current = current.getparent()
    return False


def _new_lb() -> etree._Element:
    return etree.Element(TEI + "lb")


def _remove_lb_preserving_text(lb: etree._Element) -> None:
    parent = lb.getparent()
    if parent is None:
        return
    replacement = (lb.text or "") + (lb.tail or "")
    prev = lb.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + replacement
    else:
        parent.text = (parent.text or "") + replacement
    parent.remove(lb)


def _unwrap_fw_lbs(root: etree._Element) -> int:
    removed = 0
    for fw in root.iter(TEI + "fw"):
        for lb in list(fw.iter(TEI + "lb")):
            _remove_lb_preserving_text(lb)
            removed += 1
    return removed


def _normalized_text(elem: etree._Element) -> str:
    return " ".join("".join(elem.itertext()).split())


def _move_signature_paragraphs_to_fw(root: etree._Element) -> int:
    moved = 0
    for p in list(root.iter(TEI + "p")):
        if not _inside_body(p) or _inside(p, IGNORED_LINE_CONTEXTS):
            continue
        text = _normalized_text(p)
        if not SIGNATURE_RE.match(text):
            continue
        parent = p.getparent()
        if parent is None:
            continue
        fw = etree.Element(TEI + "fw")
        fw.set("type", "sig")
        fw.set("place", "bottom")
        fw.text = text
        fw.tail = p.tail
        parent[parent.index(p)] = fw
        moved += 1
    return moved


def _insert_lb_after_child(
    elem: etree._Element,
    child: etree._Element,
    index: int,
) -> bool:
    tail = child.tail or ""
    if not tail.strip():
        return False
    lb = _new_lb()
    lb.tail = tail
    child.tail = None
    elem.insert(index + 1, lb)
    return True


def _insert_missing_leading_lb(elem: etree._Element) -> bool:
    if elem.tag not in MAIN_START_TAGS:
        return False
    if _is_supplied_head(elem):
        return False
    if not _inside_body(elem) or _inside_ignored_line_context(elem):
        return False

    if elem.text and elem.text.strip():
        lb = _new_lb()
        lb.tail = elem.text
        elem.text = None
        elem.insert(0, lb)
        return True

    for index, child in enumerate(list(elem)):
        if not isinstance(child.tag, str):
            continue
        if child.tag == TEI + "lb":
            return False
        if child.tag in IGNORED_LINE_CONTEXTS or child.tag == TEI + "pb":
            if _insert_lb_after_child(elem, child, index):
                return True
            continue
        lb = _new_lb()
        elem.insert(index, lb)
        return True
    return False


def _insert_missing_leading_lbs(root: etree._Element) -> int:
    inserted = 0
    for elem in root.iter():
        if _insert_missing_leading_lb(elem):
            inserted += 1
    return inserted


def _split_literal_line_breaks_in_element(elem: etree._Element) -> int:
    inserted = 0
    if elem.text and "\n" in elem.text:
        parts = elem.text.split("\n")
        elem.text = parts[0]
        insert_at = 0
        for part in parts[1:]:
            if not part.strip():
                continue
            lb = _new_lb()
            lb.tail = part.lstrip()
            elem.insert(insert_at, lb)
            insert_at += 1
            inserted += 1

    for child in list(elem):
        if child.tag != TEI + "lb":
            inserted += _split_literal_line_breaks_in_element(child)
        if not child.tail or "\n" not in child.tail:
            continue
        parts = child.tail.split("\n")
        child.tail = parts[0]
        insert_at = elem.index(child) + 1
        for part in parts[1:]:
            if not part.strip():
                continue
            lb = _new_lb()
            lb.tail = part.lstrip()
            elem.insert(insert_at, lb)
            insert_at += 1
            inserted += 1
    return inserted


def normalize_literal_body_line_breaks(root: etree._Element) -> int:
    """Convert raw text newlines in body paragraphs into line milestones."""
    inserted = 0
    for p in root.iter(TEI + "p"):
        if _inside_ignored_line_context(p):
            continue
        inserted += _split_literal_line_breaks_in_element(p)
    return inserted


def _line_text_from_element(elem: etree._Element) -> tuple[str, bool]:
    if elem.tag in LINE_BOUNDARY_TAGS:
        return "", True

    parts = [elem.text or ""]
    for child in elem:
        child_text, stopped = _line_text_from_element(child)
        parts.append(child_text)
        if stopped:
            return "".join(parts), True
        parts.append(child.tail or "")
    return "".join(parts), False


def _line_text_after_lb(lb: etree._Element) -> str:
    parts = [lb.tail or ""]
    current = lb
    while True:
        for sibling in current.itersiblings():
            if not isinstance(sibling.tag, str):
                parts.append(sibling.tail or "")
                continue
            text, stopped = _line_text_from_element(sibling)
            parts.append(text)
            if stopped:
                return "".join(parts)
            parts.append(sibling.tail or "")

        parent = current.getparent()
        if parent is None or parent.tag in LINE_CONTAINER_TAGS:
            return "".join(parts)
        parts.append(parent.tail or "")
        current = parent


def _word_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    for word in WORD_RE.findall(text):
        normalized = word.translate(SUPERSCRIPT_DIGITS)
        normalized = TRAILING_NOTE_MARKER_RE.sub("", normalized)
        if normalized and not normalized.isdigit():
            fragments.append(normalized)
    return fragments


def _last_word_fragment(text: str) -> str:
    words = _word_fragments(text)
    return words[-1] if words else ""


def _first_word_fragment(text: str) -> str:
    words = _word_fragments(text)
    return words[0] if words else ""


def _hyphenation_key(before_text: str, after_text: str) -> tuple[str, str] | None:
    before = _last_word_fragment(before_text)
    after = _first_word_fragment(after_text)
    if not before or not after:
        return None
    return (before.casefold(), after.casefold())


def _fragment_filename_from_pb(pb: etree._Element) -> str | None:
    source = pb.get("source") or pb.get("facs") or ""
    match = JP2_BASENAME_RE.search(unquote(source))
    if not match:
        return None
    return f"{match.group(1)}.xml"


def _page_body_lbs(root: etree._Element) -> dict[etree._Element, list[etree._Element]]:
    pages: dict[etree._Element, list[etree._Element]] = {}
    current_pb: etree._Element | None = None
    for elem in root.iter():
        if elem.tag == TEI + "pb":
            current_pb = elem
            pages.setdefault(elem, [])
            continue
        if elem.tag != TEI + "lb" or current_pb is None:
            continue
        if not _inside_body(elem) or _inside_ignored_line_context(elem):
            continue
        pages[current_pb].append(elem)
    return pages


def _target_lbs_by_key(
    lbs: list[etree._Element],
) -> dict[tuple[str, str], list[etree._Element]]:
    matches: dict[tuple[str, str], list[etree._Element]] = defaultdict(list)
    for index, lb in enumerate(lbs):
        if index == 0:
            continue
        key = _hyphenation_key(_line_text_after_lb(lbs[index - 1]), _line_text_after_lb(lb))
        if key:
            matches[key].append(lb)
    return matches


def _local_name(elem: etree._Element) -> str:
    if not isinstance(elem.tag, str):
        return ""
    return etree.QName(elem).localname


def _flatten_text_and_milestones(root: etree._Element) -> list[tuple[str, str | None]]:
    items: list[tuple[str, str | None]] = []

    def walk(elem: etree._Element) -> None:
        if elem.text:
            items.append(("text", elem.text))
        for child in elem:
            if _local_name(child) in {"lb", "pb"}:
                items.append((_local_name(child), child.get("break")))
                if child.text:
                    items.append(("text", child.text))
            else:
                walk(child)
            if child.tail:
                items.append(("text", child.tail))

    walk(root)
    return items


def _neighbor_text(
    items: list[tuple[str, str | None]],
    index: int,
    direction: int,
) -> str:
    parts: list[str] = []
    cursor = index + direction
    while 0 <= cursor < len(items):
        kind, value = items[cursor]
        if kind in {"lb", "pb"}:
            break
        if value:
            if direction < 0:
                parts.insert(0, value)
            else:
                parts.append(value)
        cursor += direction
    return "".join(parts)


def _fragment_candidates(fragment_path: Path) -> list[dict[str, str]]:
    parser = etree.XMLParser(remove_blank_text=False)
    text = fragment_path.read_text(encoding="utf-8")
    root = etree.fromstring(f"<fragment>{text}</fragment>".encode("utf-8"), parser)
    items = _flatten_text_and_milestones(root)
    candidates: list[dict[str, str]] = []
    for index, (kind, value) in enumerate(items):
        if kind != "lb" or value != "no":
            continue
        before_text = _neighbor_text(items, index, -1)
        after_text = _neighbor_text(items, index, 1)
        key = _hyphenation_key(before_text, after_text)
        if not key:
            continue
        candidates.append(
            {
                "before": _last_word_fragment(before_text),
                "after": _first_word_fragment(after_text),
                "key_before": key[0],
                "key_after": key[1],
            }
        )
    return candidates


def _fragment_lines(fragment_path: Path) -> list[str]:
    parser = etree.XMLParser(remove_blank_text=False)
    text = fragment_path.read_text(encoding="utf-8")
    root = etree.fromstring(f"<fragment>{text}</fragment>".encode("utf-8"), parser)
    lines: list[str] = []
    current: list[str] = []
    for kind, value in _flatten_text_and_milestones(root):
        if kind in {"lb", "pb"}:
            line = "".join(current)
            if line.strip():
                lines.append(line)
            current = []
            continue
        current.append(value or "")
    line = "".join(current)
    if line.strip():
        lines.append(line)
    return lines


def _match_words(text: str) -> list[str]:
    return [word.casefold() for word in WORD_RE.findall(text)]


def _line_starts_with_same_words(fragment_suffix: str, body_line: str) -> bool:
    fragment_words = _match_words(fragment_suffix)
    body_words = _match_words(body_line)
    if len(fragment_words) < 2 or len(body_words) < 2:
        return False
    compare_count = min(len(fragment_words), len(body_words), 8)
    return fragment_words[:compare_count] == body_words[:compare_count]


def _cap_prefix_matches_fragment_line(
    fragment_line: str,
    body_line: str,
) -> str | None:
    if CAP_PREFIX_RE.match(body_line):
        return None
    for match in CAP_PREFIX_SEARCH_RE.finditer(fragment_line):
        suffix = fragment_line[match.end():]
        if _line_starts_with_same_words(suffix, body_line):
            return _normalize_cap_prefix(match.group(1))
    return None


def _normalize_cap_prefix(prefix: str) -> str:
    text = " ".join(prefix.split())
    text = re.sub(r"\s*([—–-])\s*", r" \1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text.endswith("."):
        text = f"{text}."
    return text


def _heading_prefix_candidates(fragment_path: Path, body_line: str) -> list[str]:
    candidates: list[str] = []
    for line in _fragment_lines(fragment_path):
        prefix = _cap_prefix_matches_fragment_line(_normalized_fragment_text(line), body_line)
        if prefix and prefix not in candidates:
            candidates.append(prefix)
    return candidates


def _normalized_fragment_text(text: str) -> str:
    return " ".join(text.split())


def _write_heading_audit(stats: HeadingReconciliationStats) -> None:
    audit_path = Path(__file__).resolve().parents[3] / HEADING_AUDIT
    if not stats.unresolved:
        if audit_path.exists():
            audit_path.unlink()
        return
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["chapter\tpage\tfragment\tstatus\thead\tbody_line\tcandidates\n"]
    for item in stats.unresolved:
        lines.append(
            "\t".join(
                [
                    _audit_cell(item.get("chapter", "")),
                    _audit_cell(item.get("page", "")),
                    _audit_cell(item.get("fragment", "")),
                    _audit_cell(item.get("status", "")),
                    _audit_cell(item.get("head", "")),
                    _audit_cell(item.get("body_line", "")),
                    _audit_cell(item.get("candidates", "")),
                ]
            )
            + "\n"
        )
    audit_path.write_text("".join(lines), encoding="utf-8")


def _audit_cell(value: str) -> str:
    return " ".join(value.split()) or "-"


def _write_hyphenation_audit(stats: HyphenationImportStats) -> None:
    audit_path = Path(__file__).resolve().parents[3] / HYPHENATION_AUDIT
    if not stats.unresolved:
        if audit_path.exists():
            audit_path.unlink()
        return
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["page\tfragment\tstatus\tbefore\tafter\tmatches\n"]
    for item in stats.unresolved:
        lines.append(
            "\t".join(
                [
                    _audit_cell(item.get("page", "")),
                    _audit_cell(item.get("fragment", "")),
                    _audit_cell(item.get("status", "")),
                    _audit_cell(item.get("before", "")),
                    _audit_cell(item.get("after", "")),
                    _audit_cell(item.get("matches", "")),
                ]
            )
            + "\n"
        )
    audit_path.write_text("".join(lines), encoding="utf-8")


def _write_cleanup_outputs(
    heading_stats: HeadingReconciliationStats,
    hyphen_stats: HyphenationImportStats,
    page_stats: PageFurnitureStats,
) -> None:
    ledger_path = Path(__file__).resolve().parents[3] / CLEANUP_LEDGER
    summary_path = Path(__file__).resolve().parents[3] / CLEANUP_SUMMARY
    rows: list[dict[str, str]] = []

    for item in heading_stats.unresolved:
        status = item.get("status", "")
        rows.append(
            {
                "issue_type": "heading",
                "status": "needs-image-review" if status == "missing-fragment" else "needs-review",
                "page": item.get("page", ""),
                "fragment": item.get("fragment", ""),
                "xml_id": item.get("chapter", ""),
                "line": "",
                "current": item.get("body_line", ""),
                "evidence": item.get("head", ""),
                "proposed_action": "restore printed prefix only if fragment or page image confirms it",
                "note": status,
            }
        )

    for item in hyphen_stats.unresolved:
        status = item.get("status", "")
        rows.append(
            {
                "issue_type": "hyphenation",
                "status": "needs-image-review" if status == "ambiguous" else "needs-review",
                "page": item.get("page", ""),
                "fragment": item.get("fragment", ""),
                "xml_id": "",
                "line": "",
                "current": f"{item.get('before', '')}|{item.get('after', '')}",
                "evidence": item.get("matches", ""),
                "proposed_action": "set lb@break='no' only when the page-local split is unique",
                "note": status,
            }
        )

    rows.extend(page_stats.review_rows)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "issue_type",
        "status",
        "page",
        "fragment",
        "xml_id",
        "line",
        "current",
        "evidence",
        "proposed_action",
        "note",
    ]
    lines = ["\t".join(columns) + "\n"]
    for row in rows:
        lines.append("\t".join(_audit_cell(row.get(column, "")) for column in columns) + "\n")
    ledger_path.write_text("".join(lines), encoding="utf-8")

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        counts[(row.get("issue_type", ""), row.get("status", ""))] += 1
    summary_lines = [
        "# Sprengel Commentarius Cleanup Summary\n",
        "\n",
        f"- Heading audit review rows: {len(heading_stats.unresolved)}\n",
        f"- Hyphenation audit review rows: {len(hyphen_stats.unresolved)}\n",
        f"- Page furniture review/action rows: {len(page_stats.review_rows)}\n",
        f"- Pages scanned for page furniture: {page_stats.pages_seen}\n",
        f"- Page numbers inserted: {page_stats.page_numbers_inserted}\n",
        f"- Page numbers split from running heads: {page_stats.page_numbers_split}\n",
        f"- Page-number furniture normalized: {page_stats.page_numbers_normalized}\n",
        f"- Running heads normalized: {page_stats.running_heads_normalized}\n",
        f"- Empty page-furniture elements removed: {page_stats.empty_fws_removed}\n",
        f"- Leaked page-number body paragraphs removed: {page_stats.leaked_page_numbers_removed}\n",
        f"- Leaked running-head text removed: {page_stats.leaked_headers_removed}\n",
        "\n",
        "## Review Counts\n",
    ]
    for (issue_type, status), count in sorted(counts.items()):
        summary_lines.append(f"- {issue_type} / {status}: {count}\n")
    summary_path.write_text("".join(summary_lines), encoding="utf-8")


def import_line_end_hyphenation(
    root: etree._Element,
    fragment_dir: Path | None = None,
    *,
    write_audit: bool = False,
) -> HyphenationImportStats:
    """Import page-local line-end hyphenation from v1 LLM fragments.

    The fragments preserve visible line-end hyphenation as ``<lb break="no"/>``.
    Current Commentarius TEI keeps the line-numbered page contract, so this pass
    only transfers the marker when the before/after word fragments identify a
    unique current body-line break on the same page.
    """
    resolved_fragment_dir = _require_fragment_dir(fragment_dir)
    stats = HyphenationImportStats()
    for pb, lbs in _page_body_lbs(root).items():
        stats.pages_seen += 1
        for lb in lbs:
            if lb.get("break") == "no":
                del lb.attrib["break"]
                stats.existing_cleared += 1
        fragment_filename = _fragment_filename_from_pb(pb)
        fragment_path = (
            resolved_fragment_dir / fragment_filename
            if fragment_filename
            else None
        )
        if fragment_path is None or not fragment_path.exists():
            stats.pages_missing_fragments += 1
            continue
        stats.pages_with_fragments += 1
        target_matches = _target_lbs_by_key(lbs)
        for candidate in _fragment_candidates(fragment_path):
            stats.candidates += 1
            key = (candidate["key_before"], candidate["key_after"])
            matches = target_matches.get(key, [])
            if len(matches) == 1:
                matches[0].set("break", "no")
                stats.matched += 1
                continue
            status = "ambiguous" if len(matches) > 1 else "unmatched"
            if status == "ambiguous":
                stats.ambiguous += 1
            else:
                stats.unmatched += 1
            stats.unresolved.append(
                {
                    "page": pb.get("n") or "",
                    "fragment": fragment_path.name,
                    "status": status,
                    "before": candidate["before"],
                    "after": candidate["after"],
                    "matches": str(len(matches)),
                }
            )
    if write_audit:
        _write_hyphenation_audit(stats)
    return stats


def _direct_child(elem: etree._Element, tag: str) -> etree._Element | None:
    for child in elem:
        if child.tag == tag:
            return child
    return None


def _first_body_lb(div: etree._Element) -> etree._Element | None:
    for child in div:
        if child.tag in {TEI + "p", TEI + "ab"}:
            lb = child.find(f".//{TEI}lb")
            if lb is not None and not _inside_ignored_line_context(lb):
                return lb
    for lb in div.iter(TEI + "lb"):
        if not _inside_ignored_line_context(lb):
            return lb
    return None


def _pb_before_element(elem: etree._Element) -> etree._Element | None:
    current: etree._Element | None = elem
    while current is not None:
        for sibling in reversed(list(current.itersiblings(preceding=True))):
            for candidate in reversed(list(sibling.iter())):
                if candidate.tag == TEI + "pb":
                    return candidate
            if sibling.tag == TEI + "pb":
                return sibling
        current = current.getparent()
    return None


def _lb_page_map(root: etree._Element) -> dict[etree._Element, etree._Element]:
    pages: dict[etree._Element, etree._Element] = {}
    current_pb: etree._Element | None = None
    for elem in root.iter():
        if elem.tag == TEI + "pb":
            current_pb = elem
        elif elem.tag == TEI + "lb" and current_pb is not None:
            pages[elem] = current_pb
    return pages


def _normalize_supplied_label(text: str) -> str:
    label = " ".join(text.split()).strip()
    label = label.strip("[] ")
    return f"[{label}]" if label else ""


def _set_head_supplied(head: etree._Element) -> bool:
    label = _normalize_supplied_label(_normalized_text(head))
    changed = head.get("type") != "supplied"
    head.set("type", "supplied")
    for child in list(head):
        head.remove(child)
        changed = True
    if head.text != label:
        head.text = label
        changed = True
    return changed


def _remove_duplicate_head_tail(head: etree._Element, body_line: str) -> bool:
    tail_text = " ".join((head.tail or "").split())
    if not tail_text:
        return False
    if not _match_words(body_line)[: len(_match_words(tail_text))] == _match_words(tail_text):
        return False
    head.tail = "\n          "
    return True


def _insert_prefix_after_lb(lb: etree._Element, prefix: str) -> None:
    tail = lb.tail or ""
    lb.tail = f"{prefix} {tail.lstrip()}"


def reconcile_inline_chapter_headings(
    root: etree._Element,
    fragment_dir: Path | None = None,
    *,
    write_audit: bool = False,
) -> HeadingReconciliationStats:
    """Move generated chapter labels out of the diplomatic line stream.

    Chapter heads in this commentary are useful navigation labels inherited
    from the 1829 edition, but the printed Commentarius page usually carries
    only an inline ``Cap.`` prefix in the first body line. The v1 fragments are
    the source of evidence for that printed prefix.
    """
    resolved_fragment_dir = _require_fragment_dir(fragment_dir)
    stats = HeadingReconciliationStats()
    lb_pages = _lb_page_map(root)
    for div in root.iter(TEI + "div"):
        if div.get("subtype") != "chapter":
            continue
        stats.chapters_seen += 1
        head = _direct_child(div, TEI + "head")
        first_lb = _first_body_lb(div)
        head_label = _normalized_text(head) if head is not None else ""
        body_line = _line_text_after_lb(first_lb).strip() if first_lb is not None else ""
        if first_lb is None or not body_line:
            stats.no_first_line += 1
        elif head is not None and _remove_duplicate_head_tail(head, body_line):
            stats.duplicate_head_tails_removed += 1

        if head is not None and _set_head_supplied(head):
            stats.supplied_heads += 1

        if first_lb is None or not body_line:
            continue
        if CAP_PREFIX_RE.match(body_line):
            stats.already_present += 1
            continue

        pb = lb_pages.get(first_lb)
        if pb is None:
            pb = _pb_before_element(first_lb)
        fragment_filename = _fragment_filename_from_pb(pb) if pb is not None else None
        fragment_path = (
            resolved_fragment_dir / fragment_filename
            if fragment_filename
            else None
        )
        page = pb.get("n") if pb is not None else ""
        if fragment_path is None or not fragment_path.exists():
            stats.missing_fragments += 1
            stats.unresolved.append(
                {
                    "chapter": div.get("n") or div.get(XID) or "",
                    "page": page or "",
                    "fragment": fragment_filename or "",
                    "status": "missing-fragment",
                    "head": head_label,
                    "body_line": body_line,
                    "candidates": "",
                }
            )
            continue
        candidates = _heading_prefix_candidates(fragment_path, body_line)
        if len(candidates) == 1:
            _insert_prefix_after_lb(first_lb, candidates[0])
            stats.prefixes_restored += 1
            continue
        status = "ambiguous" if candidates else "unmatched"
        if candidates:
            stats.ambiguous += 1
        else:
            stats.unmatched += 1
        stats.unresolved.append(
            {
                "chapter": div.get("n") or div.get(XID) or "",
                "page": page or "",
                "fragment": fragment_path.name,
                "status": status,
                "head": head_label,
                "body_line": body_line,
                "candidates": " | ".join(candidates),
            }
        )
    if write_audit:
        _write_heading_audit(stats)
    return stats


def _page_number_place(page_n: str) -> str:
    try:
        return "top-left" if int(page_n) % 2 == 0 else "top-right"
    except ValueError:
        return "top-left"


def _running_head_place(page_n: str) -> str:
    return "top-right" if _page_number_place(page_n) == "top-left" else "top-left"


def _set_fw_text(fw: etree._Element, text: str) -> None:
    for child in list(fw):
        fw.remove(child)
    fw.text = text


def _top_furniture_after_pb(pb: etree._Element) -> list[etree._Element]:
    fws: list[etree._Element] = []
    for sibling in pb.itersiblings():
        if sibling.tag == TEI + "fw" and (
            (sibling.get("place") or "").startswith("top")
            or sibling.get("type") in {"header", "page-number"}
        ):
            fws.append(sibling)
            continue
        break
    return fws


def _page_before_element_in_stream(elem: etree._Element) -> etree._Element | None:
    current: etree._Element | None = elem
    while current is not None:
        for sibling in reversed(list(current.itersiblings(preceding=True))):
            if sibling.tag == TEI + "pb":
                return sibling
            for candidate in reversed(list(sibling.iter())):
                if candidate.tag == TEI + "pb":
                    return candidate
        current = current.getparent()
    return None


def _remove_leaked_page_furniture(root: etree._Element, stats: PageFurnitureStats) -> None:
    for p in list(root.iter(TEI + "p")):
        pb = _page_before_element_in_stream(p)
        if pb is None:
            continue
        page_n = pb.get("n") or ""
        if page_n and _normalized_text(p) == page_n:
            parent = p.getparent()
            if parent is not None:
                parent.remove(p)
                stats.leaked_page_numbers_removed += 1
                stats.review_rows.append(
                    {
                        "issue_type": "page-furniture",
                        "status": "applied",
                        "page": page_n,
                        "fragment": _fragment_filename_from_pb(pb) or "",
                        "xml_id": pb.get(XID) or "",
                        "line": "",
                        "current": f"body paragraph page number {page_n}",
                        "evidence": pb.get("facs") or pb.get("source") or "",
                        "proposed_action": "remove page number from body line stream",
                        "note": "deterministic",
                    }
                )

    for space in list(root.iter(TEI + "space")):
        tail = " ".join((space.tail or "").split())
        if not tail:
            continue
        next_elem = space.getnext()
        if next_elem is None or next_elem.tag != TEI + "fw":
            continue
        if tail != _normalized_text(next_elem):
            continue
        pb = _page_before_element_in_stream(space)
        parent = space.getparent()
        if parent is None:
            continue
        parent.remove(space)
        stats.leaked_headers_removed += 1
        stats.review_rows.append(
            {
                "issue_type": "page-furniture",
                "status": "applied",
                "page": pb.get("n") if pb is not None else "",
                "fragment": _fragment_filename_from_pb(pb) if pb is not None else "",
                "xml_id": pb.get(XID) if pb is not None else "",
                "line": "",
                "current": tail,
                "evidence": "space tail duplicated following fw",
                "proposed_action": "remove leaked running head from body text",
                "note": "deterministic",
            }
        )


def _split_page_number(text: str, page_n: str) -> tuple[str, bool]:
    normalized = " ".join(text.split())
    if normalized == page_n:
        return "", True
    for pattern in (rf"^(?:{re.escape(page_n)})\s+(.+)$", rf"^(.+?)\s+(?:{re.escape(page_n)})$"):
        match = re.match(pattern, normalized)
        if match:
            return match.group(1).strip(), True
    return normalized, False


def normalize_page_top_furniture(root: etree._Element) -> PageFurnitureStats:
    """Standardize page-number/running-head furniture for each page."""
    stats = PageFurnitureStats()
    _remove_leaked_page_furniture(root, stats)
    for pb in root.iter(TEI + "pb"):
        page_n = pb.get("n") or ""
        if not page_n:
            continue
        stats.pages_seen += 1
        top_fws = _top_furniture_after_pb(pb)
        page_fw: etree._Element | None = None
        running_fws: list[etree._Element] = []
        empty_fws: list[etree._Element] = []

        for fw in top_fws:
            text = _normalized_text(fw)
            if not text:
                empty_fws.append(fw)
                continue
            if fw.get("type") == "page-number" or text == page_n:
                page_fw = fw
                _set_fw_text(fw, page_n)
                continue
            running, found_page = _split_page_number(text, page_n)
            if found_page and page_fw is None:
                page_fw = etree.Element(TEI + "fw")
                page_fw.text = page_n
                fw.addprevious(page_fw)
                stats.page_numbers_split += 1
            if running:
                _set_fw_text(fw, running)
                running_fws.append(fw)
            else:
                empty_fws.append(fw)

        if page_fw is None:
            page_fw = etree.Element(TEI + "fw")
            page_fw.text = page_n
            insert_after = pb
            insert_after.addnext(page_fw)
            stats.page_numbers_inserted += 1
            stats.review_rows.append(
                {
                    "issue_type": "page-furniture",
                    "status": "applied",
                    "page": page_n,
                    "fragment": _fragment_filename_from_pb(pb) or "",
                    "xml_id": pb.get(XID) or "",
                    "line": "",
                    "current": "missing page number",
                    "evidence": pb.get("facs") or pb.get("source") or "",
                    "proposed_action": "insert page-number fw using pb@n and parity placement",
                    "note": "deterministic",
                }
            )

        desired_page_place = _page_number_place(page_n)
        if page_fw.get("type") != "page-number" or page_fw.get("place") != desired_page_place:
            page_fw.set("type", "page-number")
            page_fw.set("place", desired_page_place)
            stats.page_numbers_normalized += 1

        desired_head_place = _running_head_place(page_n)
        for fw in running_fws:
            if fw.get("type") != "header" or fw.get("place") != desired_head_place:
                fw.set("type", "header")
                fw.set("place", desired_head_place)
                stats.running_heads_normalized += 1

        for fw in empty_fws:
            parent = fw.getparent()
            if parent is not None:
                parent.remove(fw)
                stats.empty_fws_removed += 1

        ordered = [fw for fw in _top_furniture_after_pb(pb) if fw.getparent() is not None]
        if page_fw.get("place") == "top-left":
            desired = [page_fw] + [fw for fw in ordered if fw is not page_fw]
        else:
            desired = [fw for fw in ordered if fw is not page_fw] + [page_fw]
        parent = pb.getparent()
        if parent is not None and ordered != desired:
            insert_index = parent.index(pb) + 1
            for fw in desired:
                if fw.getparent() is parent:
                    parent.remove(fw)
            for offset, fw in enumerate(desired):
                parent.insert(insert_index + offset, fw)

    return stats


def normalize_footnote_ref_markers(root: etree._Element) -> int:
    """Normalize footnote reference text; rendering handles superscript style."""
    changed = 0
    for ref in root.iter(TEI + "ref"):
        if ref.get("type") != "footnote-ref" or ref.text is None:
            continue
        normalized = ref.text.translate(SUPERSCRIPT_DIGITS)
        if normalized == ref.text:
            continue
        ref.text = normalized
        changed += 1
    return changed


def repair_known_missing_line_breaks(root: etree._Element) -> int:
    """Restore checked line breaks that are present in page evidence."""
    repaired = 0
    for foreign in root.iter(TEI + "foreign"):
        if "Πελεθρόνιον νάπος ἴσχει." not in _normalized_text(foreign):
            continue
        tail = foreign.tail or ""
        if not tail.lstrip().startswith("Quaenam sit planta"):
            continue
        parent = foreign.getparent()
        if parent is None:
            continue
        lb = _new_lb()
        lb.tail = tail.lstrip()
        foreign.tail = "\n"
        parent.insert(parent.index(foreign) + 1, lb)
        repaired += 1
    repaired += _repair_page_596_line_breaks(root)
    return repaired


def _element_page_n(elem: etree._Element) -> str:
    pb = _pb_before_element(elem)
    return pb.get("n") if pb is not None else ""


def _insert_lb_before_element(elem: etree._Element) -> bool:
    parent = elem.getparent()
    if parent is None:
        return False
    previous = elem.getprevious()
    if (
        previous is not None
        and previous.tag == TEI + "lb"
        and not (previous.tail or "").strip()
    ):
        return False
    lb = _new_lb()
    lb.tail = ""
    parent.insert(parent.index(elem), lb)
    return True


def _remove_empty_lb_before_element(elem: etree._Element) -> bool:
    previous = elem.getprevious()
    if previous is None or previous.tag != TEI + "lb":
        return False
    if previous.get("break") == "no" or (previous.tail or "").strip():
        return False
    previous.tail = " "
    _remove_lb_preserving_text(previous)
    return True


def _repair_page_596_line_breaks(root: etree._Element) -> int:
    """Restore checked page 596 lines that start with inline markup."""
    repaired = 0
    for hi in root.iter(TEI + "hi"):
        if _element_page_n(hi) != "596":
            continue
        text = _normalized_text(hi)
        if text.startswith("Cladium potius germanicum") and _insert_lb_before_element(hi):
            repaired += 1
        elif text == "acutum" and _insert_lb_before_element(hi):
            repaired += 1

    for foreign in root.iter(TEI + "foreign"):
        if _element_page_n(foreign) != "596":
            continue
        if _normalized_text(foreign) == "Ὁλόσχοινος" and _remove_empty_lb_before_element(foreign):
            repaired += 1
    return repaired


def repair_known_text_errors(root: etree._Element) -> int:
    """Apply small, user-checked corrections where fragment OCR is wrong."""
    repaired = 0
    div = root.find(f".//{TEI}div[@{XID}='spr-ch-3.21-la']")
    if div is None:
        return repaired

    for foreign in div.iter(TEI + "foreign"):
        if foreign.get(f"{{{XML_NS}}}lang") != "grc":
            continue
        first_child = foreign[0] if len(foreign) else None
        foreign_text = (foreign.text or "").strip()
        if (
            first_child is not None
            and first_child.tag == TEI + "lb"
            and foreign_text in {"σίσσε", "σίσερ"}
            and (first_child.tail or "").startswith(("ρος", "τος"))
        ):
            if foreign.text != "σίσερ":
                foreign.text = "σίσερ"
                repaired += 1
            if not (first_child.tail or "").startswith("τος"):
                first_child.tail = "τος" + (first_child.tail or "")[3:]
                repaired += 1
            if first_child.get("break") != "no":
                first_child.set("break", "no")
                repaired += 1
            continue
        if foreign.text == "σετέσσο":
            foreign.text = "σετέσρο"
            repaired += 1
    return repaired


def _direct_head(div: etree._Element) -> etree._Element | None:
    for child in div:
        if child.tag == TEI + "head":
            return child
    return None


def _first_line_text(elem: etree._Element) -> str:
    lb = elem.find(f".//{TEI}lb")
    return _line_text_after_lb(lb) if lb is not None else _normalized_text(elem)


def repair_page_342_book_boundary(root: etree._Element) -> int:
    """Fix checked page 342 paragraph/book boundary after the preface."""
    repaired = 0
    preface = root.find(f".//{TEI}div[@{XID}='spr-comm-praefatio']")
    if preface is not None:
        page_342_seen = False
        for child in list(preface):
            if child.tag == TEI + "pb" and child.get("n") == "342":
                page_342_seen = True
                continue
            if not page_342_seen or child.tag != TEI + "p":
                continue
            if _first_line_text(child).lstrip().startswith("monio firmatur"):
                if child.get("type") != "continued":
                    child.set("type", "continued")
                    repaired += 1
                for index, item in enumerate(list(child)):
                    if (
                        item.tag == TEI + "lb"
                        and (item.tail or "").lstrip().startswith("P. 7.")
                    ):
                        new_p = etree.Element(TEI + "p")
                        new_p.tail = child.tail
                        child.tail = "\n        "
                        for moving in list(child)[index:]:
                            child.remove(moving)
                            new_p.append(moving)
                        preface.insert(preface.index(child) + 1, new_p)
                        repaired += 1
                        break
            break

    book = root.find(f".//{TEI}div[@subtype='book'][@n='1']")
    head = _direct_head(book) if book is not None else None
    if head is not None and _normalized_text(head) == "LIB. I.":
        if _set_head_supplied(head):
            repaired += 1
    return repaired


def normalize_german_opening_quotes(root: etree._Element) -> int:
    """Use the printed German opening quote glyph instead of OCR double comma."""
    changed = 0
    for elem in root.iter():
        if elem.text and ",," in elem.text:
            elem.text = elem.text.replace(",,", "„")
            changed += 1
        if elem.tail and ",," in elem.tail:
            elem.tail = elem.tail.replace(",,", "„")
            changed += 1
    return changed


def _remove_terminal_hyphen(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    normalized, count = LINE_END_HYPHEN_RE.subn(r"\1", text, count=1)
    return normalized, bool(count)


def _remove_terminal_text_hyphen(elem: etree._Element) -> bool:
    """Remove the visible hyphen immediately before a line-join milestone."""
    prev = elem.getprevious()
    if prev is not None:
        prev.tail, changed = _remove_terminal_hyphen(prev.tail)
        if changed:
            return True
        current = prev
        while len(current):
            last = current[-1]
            last.tail, changed = _remove_terminal_hyphen(last.tail)
            if changed:
                return True
            current = last
        current.text, changed = _remove_terminal_hyphen(current.text)
        return changed

    parent = elem.getparent()
    if parent is None:
        return False
    parent.text, changed = _remove_terminal_hyphen(parent.text)
    return changed


def remove_line_end_hyphen_glyphs(root: etree._Element) -> int:
    """Let ``lb@break='no'`` carry line-end hyphenation without text glyphs."""
    removed = 0
    for lb in root.iter(TEI + "lb"):
        if lb.get("break") != "no":
            continue
        if _remove_terminal_text_hyphen(lb):
            removed += 1
    return removed


def _remove_empty_main_lbs(root: etree._Element) -> int:
    removed = 0
    for lb in list(root.iter(TEI + "lb")):
        if _inside_ignored_line_context(lb):
            continue
        if _line_text_after_lb(lb).strip():
            continue
        _remove_lb_preserving_text(lb)
        removed += 1
    return removed


def _renumber_main_lbs_by_page(root: etree._Element) -> int:
    changed = 0
    next_n: int | None = None
    for elem in root.iter():
        if elem.tag == TEI + "pb":
            next_n = 1
            continue
        if elem.tag != TEI + "lb" or next_n is None:
            continue
        if _inside_ignored_line_context(elem):
            continue
        new_n = str(next_n)
        if elem.get("n") != new_n:
            changed += 1
        elem.set("n", new_n)
        next_n += 1
    return changed


def normalize_page_line_numbering(root: etree._Element) -> dict[str, int]:
    """Normalize Sprengel commentary body line numbering page-by-page.

    `<fw>` and `<note>` are outside the body-line stream. Notes keep their
    internal `<lb/>` values as encoded visual breaks.
    """
    signature_paragraphs_moved = _move_signature_paragraphs_to_fw(root)
    fw_lbs_removed = _unwrap_fw_lbs(root)
    leading_lbs_inserted = _insert_missing_leading_lbs(root)
    empty_main_lbs_removed = _remove_empty_main_lbs(root)
    main_lbs_renumbered = _renumber_main_lbs_by_page(root)
    return {
        "signature_paragraphs_moved": signature_paragraphs_moved,
        "fw_lbs_removed": fw_lbs_removed,
        "leading_lbs_inserted": leading_lbs_inserted,
        "empty_main_lbs_removed": empty_main_lbs_removed,
        "main_lbs_renumbered": main_lbs_renumbered,
    }


def run() -> None:
    out_path = edition_tei(NEW_ID)
    src_path, used_corpus_source = _source_path(out_path)

    parser = etree.XMLParser(remove_blank_text=False)
    in_text = src_path.read_text(encoding="utf-8")
    in_lines = in_text.count("\n")
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    preserved_sources = _preserve_pb_sources(root) if used_corpus_source else {}
    promote_plain_id_to_xml_id(root)
    strip_bloat_attrs(root)
    literal_line_breaks_normalized = normalize_literal_body_line_breaks(root)
    heading_stats = reconcile_inline_chapter_headings(root, write_audit=True)
    footnote_refs_normalized = normalize_footnote_ref_markers(root)
    missing_line_breaks_repaired = repair_known_missing_line_breaks(root)
    page_342_boundary_repairs = repair_page_342_book_boundary(root)
    page_furniture_stats = normalize_page_top_furniture(root)
    line_stats = normalize_page_line_numbering(root)
    hyphen_stats = import_line_end_hyphenation(root, write_audit=True)
    text_errors_repaired = repair_known_text_errors(root)
    opening_quotes_normalized = normalize_german_opening_quotes(root)
    line_end_hyphens_removed = remove_line_end_hyphen_glyphs(root)
    facs_rewritten = rewrite_pb_facs(root)
    sources_restored = _restore_pb_sources(root, preserved_sources)
    _write_cleanup_outputs(heading_stats, hyphen_stats, page_furniture_stats)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    xml_text, indent_stats = serialize_with_epidoc_indentation(tree)
    out_path.write_text(xml_text, encoding="utf-8")

    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    remaining_midline_lbs = lb_not_line_initial_count(xml_text)
    output_state = "changed" if in_text != xml_text else "unchanged"
    print(
        f"sprengel1830-comm: {in_lines} -> {out_lines} lines, "
        f"output {output_state}, "
        f"{line_stats['signature_paragraphs_moved']} signature paragraphs moved to <fw>, "
        f"{line_stats['fw_lbs_removed']} <fw> <lb> tags unwrapped, "
        f"{heading_stats.prefixes_restored}/{heading_stats.chapters_seen} printed chapter prefixes restored, "
        f"{heading_stats.supplied_heads} chapter heads marked supplied "
        f"({heading_stats.ambiguous} ambiguous, {heading_stats.unmatched} unmatched, "
        f"{heading_stats.missing_fragments} missing fragments), "
        f"{footnote_refs_normalized} superscript footnote ref markers normalized, "
        f"{missing_line_breaks_repaired} known missing line breaks repaired, "
        f"{page_342_boundary_repairs} page 342 paragraph/book boundary repairs, "
        f"{page_furniture_stats.page_numbers_inserted} page numbers inserted, "
        f"{page_furniture_stats.page_numbers_split} page numbers split from running heads, "
        f"{page_furniture_stats.page_numbers_normalized} page-number fw tags normalized, "
        f"{page_furniture_stats.running_heads_normalized} running-head fw tags normalized, "
        f"{page_furniture_stats.leaked_page_numbers_removed} leaked page-number paragraphs removed, "
        f"{page_furniture_stats.leaked_headers_removed} leaked running heads removed, "
        f"{text_errors_repaired} known text errors repaired, "
        f"{opening_quotes_normalized} German opening quote markers normalized, "
        f"{line_end_hyphens_removed} line-end hyphen glyphs removed before break=no, "
        f"{line_stats['leading_lbs_inserted']} leading body <lb> tags inserted, "
        f"{line_stats['empty_main_lbs_removed']} empty main body <lb> tags removed, "
        f"{line_stats['main_lbs_renumbered']} main body <lb> tags renumbered, "
        f"{hyphen_stats.matched}/{hyphen_stats.candidates} line-end hyphenation breaks imported "
        f"({hyphen_stats.ambiguous} ambiguous, {hyphen_stats.unmatched} unmatched, "
        f"{hyphen_stats.pages_missing_fragments} pages missing fragments, "
        f"{hyphen_stats.existing_cleared} existing break markers rederived), "
        f"{facs_rewritten} JP2 facs URLs rewritten to IIIF JPEG, "
        f"{sources_restored} pb @source attrs restored, "
        f"{literal_line_breaks_normalized} literal body line breaks converted to <lb>, "
        f"{indent_stats['line_start_moved']} <lb> tags moved to line starts, "
        f"{indent_stats['tail_lines_joined']} <lb> tail lines joined, "
        f"{indent_stats['lb_lines_indented']} <lb> lines reindented, "
        f"{indent_stats['trailing_ws_stripped']} trailing line spaces stripped, "
        f"{remaining_midline_lbs} mid-line <lb> tags remain  ({out_path})"
    )
