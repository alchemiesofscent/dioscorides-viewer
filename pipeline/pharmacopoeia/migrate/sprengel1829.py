"""Sprengel 1829 migration: page-major -> chapter-major restructure.

The existing edition has page-major structure with two parallel pageZones per
page (`<ab type="pageZone" xml:lang="grc|la">`) and chapter milestones
embedded as `<milestone unit="chapter" n="B.C" xml:lang corresp="#..."/>`.

This migration walks the milestones in document order per language and
rebrackets content into per-language `<div type="textpart" subtype="chapter">`
trees. Greek and Latin become parallel siblings under
`<div type="textpart" subtype="edition" xml:lang>`. `<pb/>` milestones are
preserved inside chapter divs at page boundaries. `<pb>` xml:ids are suffixed
with `-grc`/`-la` because the same source pb appears in both language streams.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy

from lxml import etree

from pharmacopoeia.normalize.facs import rewrite_pb_facs
from pharmacopoeia.normalize.lb import (
    drop_unnumbered_lb_outside_notes,
    strip_bloat_attrs,
)
from pharmacopoeia.paths import edition_tei, legacy_edition_tei

LEGACY_ID = "sprengel1829"
NEW_ID = "sprengel1829"

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS = {"t": TEI_NS}
TEI = f"{{{TEI_NS}}}"
XID = f"{{{XML_NS}}}id"
XLANG = f"{{{XML_NS}}}lang"


def _is_chapter_milestone(elem: etree._Element) -> bool:
    return (
        elem.tag == TEI + "milestone"
        and elem.get("unit") == "chapter"
        and elem.get("n") is not None
    )


def _collect_pageZones(root: etree._Element) -> list[etree._Element]:
    # Skip pageZones inside <front>; those stay in the front section verbatim.
    return root.xpath(
        ".//t:body//t:ab[@type='pageZone']", namespaces=NS,
    )


def _walk_chapter_segments(
    pageZones: list[etree._Element],
    lang: str,
) -> list[tuple[dict, list]]:
    """For one language, walk pageZones in order and collect per-chapter content.

    Returns ordered list of (chapter_meta, content_list) where content_list
    holds tuples ("node", element) or ("pb", element) preserving order.
    """
    chapters: dict[str, dict] = {}
    chapter_order: list[str] = ["_prelude"]
    chapters_seen: set[str] = {"_prelude"}
    chapters["_prelude"] = {
        "id": "_prelude", "n": None, "lang": lang,
        "label": "Front matter", "sourceLabel": None, "corresp": None,
    }
    chapter_contents: dict[str, list] = defaultdict(list)
    last_pb: etree._Element | None = None
    for pz in pageZones:
        if pz.get(XLANG) != lang:
            continue
        # Find the immediately preceding <pb/> for this pageZone.
        pb = None
        prev = pz.getprevious()
        while prev is not None:
            if prev.tag == TEI + "pb":
                pb = prev
                break
            prev = prev.getprevious()
        if pb is None:
            parent = pz.getparent()
            if parent is not None:
                pb_el = parent.find(TEI + "pb")
                if pb_el is not None:
                    pb = pb_el
        if pb is not None and pb is not last_pb:
            pb_copy = deepcopy(pb)
            old_id = pb_copy.get(XID)
            if old_id:
                pb_copy.set(XID, f"{old_id}-{lang}")
            chapter_contents[chapter_order[-1]].append(("pb", pb_copy))
            last_pb = pb
        for child in list(pz):
            ms_in_subtree = list(child.iter(TEI + "milestone"))
            if not ms_in_subtree and not _is_chapter_milestone(child):
                chapter_contents[chapter_order[-1]].append(("node", deepcopy(child)))
                continue
            _split_at_milestones(
                child, lang, chapters, chapter_order, chapters_seen,
                chapter_contents,
            )
    ordered = []
    for cid in chapter_order:
        meta = chapters.get(cid)
        if meta is None:
            continue
        ordered.append((meta, chapter_contents[cid]))
    return ordered


def _split_at_milestones(
    elem: etree._Element,
    lang: str,
    chapters: dict,
    chapter_order: list,
    chapters_seen: set,
    chapter_contents: dict,
) -> None:
    """Walk elem; chunk content per chapter milestone. Heuristic: if a milestone
    appears inside an inline block, split the block into per-chapter fragments.
    """
    if _is_chapter_milestone(elem) and elem.get(XLANG) == lang:
        ch_id = elem.get(XID) or f"spr-ch-{elem.get('n')}-{lang}"
        if ch_id not in chapters_seen:
            chapters[ch_id] = {
                "id": ch_id, "n": elem.get("n"), "lang": lang,
                "label": elem.get("label"),
                "sourceLabel": elem.get("sourceLabel"),
                "corresp": elem.get("corresp"),
            }
            chapters_seen.add(ch_id)
            chapter_order.append(ch_id)
        return

    has_ms = any(
        _is_chapter_milestone(m) and m.get(XLANG) == lang
        for m in elem.iter(TEI + "milestone")
    )
    if not has_ms:
        chapter_contents[chapter_order[-1]].append(("node", deepcopy(elem)))
        return

    tag = elem.tag
    attrib = dict(elem.attrib)

    def _new_shell() -> etree._Element:
        return etree.Element(tag, attrib=attrib, nsmap={None: TEI_NS})

    shell = _new_shell()
    shell.text = elem.text

    def _flush(target_id: str) -> None:
        nonlocal shell
        if shell.text or len(shell):
            chapter_contents[target_id].append(("node", shell))
        shell = _new_shell()

    active = chapter_order[-1]
    for child in elem:
        if _is_chapter_milestone(child) and child.get(XLANG) == lang:
            _flush(active)
            ch_id = child.get(XID) or f"spr-ch-{child.get('n')}-{lang}"
            if ch_id not in chapters_seen:
                chapters[ch_id] = {
                    "id": ch_id, "n": child.get("n"), "lang": lang,
                    "label": child.get("label"),
                    "sourceLabel": child.get("sourceLabel"),
                    "corresp": child.get("corresp"),
                }
                chapters_seen.add(ch_id)
                chapter_order.append(ch_id)
            active = ch_id
            if child.tail and child.tail.strip():
                seg = etree.Element(TEI + "seg", nsmap={None: TEI_NS})
                seg.text = child.tail
                shell.append(seg)
            continue
        copy = deepcopy(child)
        shell.append(copy)
    _flush(active)


def _build_output(
    src_root: etree._Element,
    grc_chapters: list,
    lat_chapters: list,
) -> etree._Element:
    tei = etree.Element(TEI + "TEI", nsmap={None: TEI_NS})
    src_header = src_root.find(TEI + "teiHeader")
    if src_header is not None:
        tei.append(deepcopy(src_header))

    text = etree.SubElement(tei, TEI + "text")
    src_text = src_root.find(TEI + "text")
    if src_text is not None:
        front = src_text.find(TEI + "front")
        if front is not None:
            text.append(deepcopy(front))

    body = etree.SubElement(text, TEI + "body")

    for lang, chapters in (("grc", grc_chapters), ("la", lat_chapters)):
        edition_div = etree.SubElement(
            body, TEI + "div",
            attrib={"type": "textpart", "subtype": "edition", XLANG: lang,
                    XID: f"spr-edition-{lang}"},
        )

        by_book: dict[str, list] = defaultdict(list)
        prelude_chapters: list = []
        for meta, content in chapters:
            n = meta.get("n")
            if not n:
                prelude_chapters.append((meta, content))
                continue
            book = n.split(".")[0]
            by_book[book].append((meta, content))

        if prelude_chapters:
            prelude_div = etree.SubElement(
                edition_div, TEI + "div",
                attrib={"type": "textpart", "subtype": "front",
                        XLANG: lang, XID: f"spr-front-{lang}"},
            )
            for _, content in prelude_chapters:
                _append_content(prelude_div, content)

        for book in sorted(by_book.keys(),
                           key=lambda s: int(s) if s.isdigit() else 99):
            book_div = etree.SubElement(
                edition_div, TEI + "div",
                attrib={"type": "textpart", "subtype": "book",
                        "n": book, XLANG: lang,
                        XID: f"spr-book-{book}-{lang}"},
            )
            for meta, content in by_book[book]:
                ch = etree.SubElement(
                    book_div, TEI + "div",
                    attrib={"type": "textpart", "subtype": "chapter",
                            "n": meta["n"], XLANG: lang},
                )
                if meta.get("id"):
                    ch.set(XID, meta["id"])
                if meta.get("corresp"):
                    ch.set("corresp", meta["corresp"])
                if meta.get("label"):
                    head = etree.SubElement(ch, TEI + "head")
                    if lang == "grc":
                        foreign = etree.SubElement(
                            head, TEI + "foreign", attrib={XLANG: "grc"},
                        )
                        foreign.text = meta["label"]
                    else:
                        head.text = meta["label"]
                _append_content(ch, content)
    return tei


def _append_content(parent: etree._Element, content: list) -> None:
    for _, node in content:
        parent.append(node)


def run() -> None:
    src_path = legacy_edition_tei(LEGACY_ID)
    if not src_path.exists():
        raise FileNotFoundError(f"Source Sprengel 1829 TEI not found: {src_path}")

    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(str(src_path), parser)
    root = tree.getroot()

    pageZones = _collect_pageZones(root)
    grc = _walk_chapter_segments(pageZones, "grc")
    lat = _walk_chapter_segments(pageZones, "la")

    new_root = _build_output(root, grc, lat)

    strip_bloat_attrs(new_root)
    rewrite_pb_facs(new_root)
    drop_unnumbered_lb_outside_notes(new_root)

    etree.indent(new_root, space="  ")
    out_path = edition_tei(NEW_ID)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    etree.ElementTree(new_root).write(
        str(out_path), pretty_print=True, xml_declaration=True, encoding="utf-8",
    )

    grc_count = sum(1 for m, _ in grc if m.get("n"))
    lat_count = sum(1 for m, _ in lat if m.get("n"))
    out_lines = out_path.read_text(encoding="utf-8").count("\n")
    print(
        f"sprengel1829: grc={grc_count} la={lat_count} chapters, "
        f"{out_lines} lines  ({out_path})"
    )
