from lxml import etree
import pytest

from pharmacopoeia.migrate.sprengel1830_comm import (
    import_line_end_hyphenation,
    normalize_page_line_numbering,
    normalize_footnote_ref_markers,
    repair_known_missing_line_breaks,
    repair_known_text_errors,
    reconcile_inline_chapter_headings,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"


def _parse(body: str) -> etree._Element:
    return etree.fromstring(
        (
            f'<TEI xmlns="{TEI_NS}"><text><body>{body}</body></text></TEI>'
        ).encode("utf-8")
    )


def _write_fragment(fragment_dir, name: str, text: str) -> None:
    fragment_dir.mkdir(exist_ok=True)
    (fragment_dir / name).write_text(text, encoding="utf-8")


def _flat_text(elem) -> str:
    return " ".join("".join(elem.itertext()).replace(" .", ".").split())


def test_fw_lb_is_unwrapped_and_body_starts_at_one():
    root = _parse(
        '<pb n="1"/><fw type="header"><lb n="1"/>HEADER</fw><p>Body line</p>'
    )

    stats = normalize_page_line_numbering(root)

    fw = root.find(f".//{TEI}fw")
    p_lb = root.find(f".//{TEI}p/{TEI}lb")
    assert stats["fw_lbs_removed"] == 1
    assert fw.text == "HEADER"
    assert fw.find(f".//{TEI}lb") is None
    assert p_lb.get("n") == "1"
    assert p_lb.tail == "Body line"


def test_paragraph_start_text_gets_page_line_number():
    root = _parse(
        '<pb n="1"/>'
        '<p><lb n="1"/>one<lb n="2"/>two<lb n="3"/>three'
        '<lb n="4"/>four<lb n="5"/>five</p>'
        '<p>Andreas medicus<lb n="6"/>ab Herophilo</p>'
    )

    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p[2]/{TEI}lb")
    assert [lb.get("n") for lb in lbs] == ["6", "7"]
    assert lbs[0].tail == "Andreas medicus"


def test_leading_inline_content_gets_page_line_number():
    root = _parse(
        '<pb n="1"/><fw type="header"><lb n="1"/>340 COMMENTARIUS</fw>'
        '<p><foreign xml:lang="grc">miko</foreign> effigies<lb n="2"/>cerpsit</p>'
    )

    normalize_page_line_numbering(root)

    p = root.find(f".//{TEI}p")
    assert p[0].tag == TEI + "lb"
    assert p[0].get("n") == "1"
    assert p[1].tag == TEI + "foreign"
    assert p.findall(f"{TEI}lb")[1].get("n") == "2"


def test_line_numbers_reset_at_every_page_break():
    root = _parse(
        '<pb n="1"/><p>First page</p>'
        '<pb n="2"/><fw type="header"><lb n="1"/>HEADER</fw><p>Second page</p>'
    )

    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}lb")
    assert [lb.get("n") for lb in lbs] == ["1", "1"]


def test_note_internal_lbs_are_not_renumbered_or_removed():
    root = _parse(
        '<pb n="1"/><p>Body</p>'
        '<note place="bottom">note<lb/>tail<lb n="99"/>kept</note>'
    )

    normalize_page_line_numbering(root)

    note_lbs = root.findall(f".//{TEI}note/{TEI}lb")
    assert [lb.get("n") for lb in note_lbs] == [None, "99"]
    assert root.find(f".//{TEI}p/{TEI}lb").get("n") == "1"


def test_terminal_empty_body_lb_is_removed_and_page_renumbered():
    root = _parse(
        '<pb n="1"/><p><lb n="1"/>videtur.<lb n="2"/></p>'
        '<head><lb n="3"/>Cap. XV.</head>'
    )

    stats = normalize_page_line_numbering(root)

    assert stats["empty_main_lbs_removed"] == 1
    lbs = root.findall(f".//{TEI}lb")
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert root.find(f".//{TEI}head/{TEI}lb").tail == "Cap. XV."


def test_empty_body_lb_before_next_lb_is_removed():
    root = _parse('<pb n="1"/><p><lb n="1"/>one<lb n="2"/><lb n="3"/>two</p>')

    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}lb")
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert lbs[1].tail == "two"


def test_inline_text_after_lb_is_not_treated_as_empty():
    root = _parse(
        '<pb n="1"/><p><lb n="1"/><foreign xml:lang="grc">miko</foreign>'
        '<lb n="2"/><hi rend="italic">Costus</hi><lb n="3"/></p>'
    )

    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert root.find(f".//{TEI}foreign").text == "miko"
    assert root.find(f".//{TEI}hi").text == "Costus"


def test_signature_paragraph_moves_to_bottom_fw():
    root = _parse(
        '<pb n="353"/><p><lb n="1"/>Body</p>'
        '<p><lb n="2"/>DIOSCORIDES II. Z</p>'
        '<p><lb n="3"/>Next body</p>'
    )

    stats = normalize_page_line_numbering(root)

    fw = root.find(f".//{TEI}fw")
    body_lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert stats["signature_paragraphs_moved"] == 1
    assert fw.get("type") == "sig"
    assert fw.get("place") == "bottom"
    assert fw.text == "DIOSCORIDES II. Z"
    assert fw.find(f".//{TEI}lb") is None
    assert [lb.get("n") for lb in body_lbs] == ["1", "2"]


def test_zea_heading_becomes_supplied_and_printed_range_moves_to_body(tmp_path):
    root = _parse(
        '<pb n="455" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0461.jp2"/>'
        '<div type="textpart" subtype="chapter" n="2.111" next="2.115" '
        'xml:id="spr-ch-2.111-la" corresp="sprengel1829_epidoc.xml#spr-ch-2.111-la">'
        '<head><lb n="31"/>Cap. CXI. De Zea. <foreign xml:lang="grc">Περὶ Ζειᾶς</foreign></head>'
        '<p><lb n="32"/><hi rend="italic"><foreign xml:lang="grc">Ζειά</foreign></hi> duplex est, altera '
        '<hi rend="italic"><foreign xml:lang="grc">ἁπλῆ</foreign></hi>,<lb n="33"/>altera</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0461.xml",
        '<pb n="455"/>Cap. CXI — CXV. <hi rend="italic"><foreign xml:lang="grc">Ζειά</foreign></hi> '
        'duplex est, altera <hi rend="italic"><foreign xml:lang="grc">ἁπλῆ</foreign></hi>,<lb/>altera<lb/>',
    )

    stats = reconcile_inline_chapter_headings(root, tmp_path)
    normalize_page_line_numbering(root)

    div = root.find(f".//{TEI}div")
    head = root.find(f".//{TEI}head")
    body_lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert stats.prefixes_restored == 1
    assert div.get("next") == "2.115"
    assert head.get("type") == "supplied"
    assert head.text == "[Cap. CXI. De Zea. Περὶ Ζειᾶς]"
    assert head.find(f".//{TEI}lb") is None
    assert [lb.get("n") for lb in body_lbs] == ["1", "2"]
    assert "Cap. CXI — CXV. Ζειά duplex est" in _flat_text(root)


def test_common_heading_restores_cap_prefix_without_duplicating_title(tmp_path):
    root = _parse(
        '<pb n="342" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0350.jp2"/>'
        '<div type="textpart" subtype="chapter" n="1.1">'
        '<head><lb n="9"/>Cap. I. De Iride. <foreign xml:lang="grc">Περὶ Ἴριδος</foreign></head>'
        '<p><lb n="10"/><hi rend="italic">De Iride</hi>. <foreign xml:lang="grc">Ἶρις, ἴριν</foreign> scribunt Aldina</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0350.xml",
        '<pb n="342"/>Cap. I. <hi rend="italic">De Iride</hi>. '
        '<foreign xml:lang="grc">Ἶρις, ἴριν</foreign> scribunt Aldina<lb/>',
    )

    stats = reconcile_inline_chapter_headings(root, tmp_path)

    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert stats.prefixes_restored == 1
    assert line_text.startswith("Cap. I. De Iride. Ἶρις")
    assert line_text.count("De Iride") == 1


def test_heading_prefix_uses_current_page_fragment_not_earlier_page(tmp_path):
    root = _parse(
        '<pb n="1" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0001.jp2"/>'
        '<p><lb n="1"/>Earlier page text</p>'
        '<pb n="2" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0002.jp2"/>'
        '<div type="textpart" subtype="chapter" n="1.1">'
        '<head><lb n="2"/>Cap. I. Example</head>'
        '<p><lb n="3"/>Foo bar baz</p>'
        '</div>'
    )
    _write_fragment(tmp_path, "b23982500_0002_0001.xml", '<pb n="1"/>Cap. X. Foo bar baz<lb/>')
    _write_fragment(tmp_path, "b23982500_0002_0002.xml", '<pb n="2"/>Cap. I. Foo bar baz<lb/>')

    stats = reconcile_inline_chapter_headings(root, tmp_path)

    assert stats.prefixes_restored == 1
    assert _flat_text(root.find(f".//{TEI}div/{TEI}p")).startswith("Cap. I. Foo")


def test_ambiguous_heading_prefix_is_skipped_and_reported(tmp_path):
    root = _parse(
        '<pb n="1" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0001.jp2"/>'
        '<div type="textpart" subtype="chapter" n="1.1">'
        '<head><lb n="1"/>Cap. I. Example</head>'
        '<p><lb n="2"/>Foo bar baz</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0001.xml",
        '<pb n="1"/>Cap. I. Foo bar baz<lb/>Cap. II. Foo bar baz<lb/>',
    )

    stats = reconcile_inline_chapter_headings(root, tmp_path)

    assert stats.prefixes_restored == 0
    assert stats.ambiguous == 1
    assert stats.unresolved[0]["status"] == "ambiguous"
    assert not " ".join(root.find(f".//{TEI}p").itertext()).startswith("Cap.")


def test_superscript_footnote_refs_are_normalized_without_touching_other_superscripts():
    root = _parse(
        '<p>body<ref target="#fn1" type="footnote-ref" xml:id="ref-fn1">¹²</ref>'
        '<ref target="#fn2" type="footnote-ref" xml:id="ref-fn2">31a</ref>'
        '<hi rend="superscript">b</hi></p>'
    )

    changed = normalize_footnote_ref_markers(root)

    refs = root.findall(f".//{TEI}ref")
    assert changed == 1
    assert refs[0].text == "12"
    assert refs[0].get("target") == "#fn1"
    assert refs[0].get(f"{{http://www.w3.org/XML/1998/namespace}}id") == "ref-fn1"
    assert refs[1].text == "31a"
    assert root.find(f".//{TEI}hi").text == "b"


def test_page_519_chiron_quote_tail_gets_missing_line_break():
    root = _parse(
        '<pb n="519"/><p><foreign xml:lang="grc"><lb n="6"/>ῥίζα, καὶ οὐ βυθόωσα '
        'Πελεθρόνιον νάπος ἴσχει.</foreign>\nQuaenam sit planta, haud ausim '
        'certo pronunciare. He-<lb n="7" break="no"/>lianthemum</p>'
    )

    changed = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}lb")
    assert changed == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2", "3"]
    assert lbs[1].tail.startswith("Quaenam sit planta")
    assert lbs[2].get("break") == "no"


def test_page_502_eryngium_greek_correction_preserves_split_line_break():
    root = _parse(
        '<pb n="502"/>'
        '<div type="textpart" subtype="chapter" n="3.21" xml:id="spr-ch-3.21-la">'
        '<head type="supplied">[Cap. XXI. De Eryngio. Περὶ Ἠρυγγίου]</head>'
        '<p><lb n="8"/>Cap. XXI. Eryngii cognomen apud prophetas '
        '<foreign xml:lang="grc">σίσσε\n              <lb n="9"/>ρος</foreign> '
        'transpositume esse e <foreign xml:lang="grc">σετέσσο</foreign>, '
        'menses ciens, emmenago-<lb n="10" break="no"/>gum</p>'
        '</div>'
    )

    changed = repair_known_text_errors(root)
    normalize_page_line_numbering(root)
    second_changed = repair_known_text_errors(root)

    foreign_words = root.findall(f".//{TEI}foreign")
    split_lb = foreign_words[0].find(f"{TEI}lb")
    body_lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert changed == 4
    assert second_changed == 0
    assert foreign_words[0].text == "σίσερ"
    assert split_lb.tail == "τος"
    assert split_lb.get("break") == "no"
    assert foreign_words[1].text == "σετέσρο"
    assert [lb.get("n") for lb in body_lbs] == ["1", "2", "3"]


def test_page_fragment_hyphenation_sets_break_no_on_matching_lb(tmp_path):
    root = _parse(
        '<pb n="423" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0431.jp2"/>'
        '<p><lb n="1"/>Galenus fructum cum par'
        '<lb n="2"/>va ficu alba comparat: facultatem mediam esse moro'
        '<lb n="3"/>rum ficorumque: unde nomen sortita sit arbor.</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0431.xml",
        '<pb n="423"/>Galenus fructum cum par<lb break="no"/>'
        'va ficu alba comparat: facultatem mediam esse moro<lb break="no"/>'
        "rum ficorumque: unde nomen sortita sit arbor.<lb/>",
    )

    stats = import_line_end_hyphenation(root, tmp_path)

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert stats.candidates == 2
    assert stats.matched == 2
    assert [lb.get("break") for lb in lbs] == [None, "no", "no"]


def test_hyphenation_import_matches_across_inline_markup(tmp_path):
    root = _parse(
        '<pb n="481" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0481.jp2"/>'
        '<p><lb n="1"/>confirmatur et a Galeno, qui '
        '<foreign xml:lang="grc">ἔνθλασμά τι μι</foreign>'
        '<lb n="2"/><foreign xml:lang="grc">κρὸν</foreign> in fructu adesse asserit</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0481.xml",
        '<pb n="481"/>confirmatur et a Galeno, qui '
        '<foreign xml:lang="grc">ἔνθλασμά τι μι-</foreign>'
        '<lb break="no"/><foreign xml:lang="grc">κρὸν</foreign> in fructu adesse asserit<lb/>',
    )

    stats = import_line_end_hyphenation(root, tmp_path)

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert stats.matched == 1
    assert lbs[1].get("break") == "no"


def test_ambiguous_hyphenation_pair_is_skipped_and_reported(tmp_path):
    root = _parse(
        '<pb n="1" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0001.jp2"/>'
        '<p><lb n="1"/>first dupli<lb n="2"/>cate line'
        '<lb n="3"/>second dupli<lb n="4"/>cate line</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0001.xml",
        '<pb n="1"/>first dupli<lb break="no"/>cate line<lb/>',
    )

    stats = import_line_end_hyphenation(root, tmp_path)

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert stats.matched == 0
    assert stats.ambiguous == 1
    assert stats.unresolved[0]["status"] == "ambiguous"
    assert all(lb.get("break") is None for lb in lbs)


def test_missing_fragment_directory_raises_clear_error(tmp_path):
    root = _parse("<pb n=\"1\"/><p><lb n=\"1\"/>line</p>")

    with pytest.raises(FileNotFoundError, match="v1 LLM fragments not found"):
        import_line_end_hyphenation(root, tmp_path / "missing")
