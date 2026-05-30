from lxml import etree
import pytest

from pharmacopoeia.migrate.sprengel1830_comm import (
    import_line_end_hyphenation,
    normalize_literal_body_line_breaks,
    normalize_beta_symbol,
    normalize_german_closing_quotes,
    normalize_german_opening_quotes,
    normalize_page_line_numbering,
    normalize_page_top_furniture,
    normalize_footnote_ref_markers,
    recover_fragment_paragraphs,
    repair_fragment_confirmed_inline_footnote_breaks,
    repair_page_342_book_boundary,
    remove_line_end_hyphen_glyphs,
    repair_known_missing_line_breaks,
    repair_known_markup_errors,
    repair_known_text_errors,
    reconcile_inline_chapter_headings,
    restore_reviewed_missing_cap_prefixes,
    repair_reviewed_inline_heads_and_labels,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XID = f"{{{XML_NS}}}id"


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


def test_short_signature_paragraph_moves_to_bottom_fw():
    root = _parse(
        '<pb n="339"/><p><lb n="1"/>Body</p>'
        '<p><lb n="2"/>Y 2</p>'
        '<p><lb n="3"/>Next body</p>'
    )

    stats = normalize_page_line_numbering(root)

    fw = root.find(f".//{TEI}fw")
    body_lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert stats["signature_paragraphs_moved"] == 1
    assert fw.get("type") == "sig"
    assert fw.get("place") == "bottom"
    assert fw.text == "Y 2"
    assert [lb.get("n") for lb in body_lbs] == ["1", "2"]


def test_page_top_furniture_splits_and_aligns_page_numbers():
    root = _parse(
        '<pb n="341"/><fw type="header" place="top">IN DIOSCORIDIS. PRAEF. 341</fw>'
        '<p>body</p>'
        '<pb n="342"/><fw type="header" place="top">COMMENTARIUS</fw><p>body</p>'
    )

    stats = normalize_page_top_furniture(root)

    pbs = root.findall(f".//{TEI}pb")
    page_341 = [sibling for sibling in pbs[0].itersiblings() if sibling.tag == TEI + "fw"][:2]
    page_342 = [sibling for sibling in pbs[1].itersiblings() if sibling.tag == TEI + "fw"][:2]
    assert stats.page_numbers_split == 1
    assert stats.page_numbers_inserted == 1
    assert [(fw.get("type"), fw.get("place"), _flat_text(fw)) for fw in page_341] == [
        ("header", "top-left", "IN DIOSCORIDIS. PRAEF."),
        ("page-number", "top-right", "341"),
    ]
    assert [(fw.get("type"), fw.get("place"), _flat_text(fw)) for fw in page_342] == [
        ("page-number", "top-left", "342"),
        ("header", "top-right", "COMMENTARIUS"),
    ]


def test_page_top_furniture_removes_leaked_body_page_number_and_header():
    root = _parse(
        '<pb n="540"/>'
        '<p><lb n="1"/>540</p>'
        '<space dim="horizontal" quantity="30" unit="char"/>COMMENTARIUS'
        '<fw type="header" place="top">COMMENTARIUS</fw>'
        '<p><lb n="2"/>facilis erat</p>'
    )

    stats = normalize_page_top_furniture(root)
    normalize_page_line_numbering(root)

    fws = root.findall(f".//{TEI}fw")
    paragraphs = root.findall(f".//{TEI}p")
    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert stats.leaked_page_numbers_removed == 1
    assert stats.leaked_headers_removed == 1
    assert [(fw.get("type"), fw.get("place"), _flat_text(fw)) for fw in fws] == [
        ("page-number", "top-left", "540"),
        ("header", "top-right", "COMMENTARIUS"),
    ]
    assert len(paragraphs) == 1
    assert _flat_text(paragraphs[0]) == "facilis erat"
    assert [lb.get("n") for lb in lbs] == ["1"]


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


def test_heading_restores_cap_prefix_when_fragment_omits_roman_period(tmp_path):
    root = _parse(
        '<pb n="349" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0357.jp2"/>'
        '<div type="textpart" subtype="chapter" n="1.12">'
        '<head><lb n="3"/>Cap. XII. De Cassia. <foreign xml:lang="grc">Περὶ Κασσίας</foreign></head>'
        '<p><lb n="4"/><hi rend="italic">De Cassia</hi>. '
        '<foreign xml:lang="grc">Κασσία</foreign> aut <foreign xml:lang="grc">κασία</foreign> quibusdam</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0357.xml",
        '<pb n="349"/>Cap. XII <hi rend="italic">De Cassia</hi>. '
        '<foreign xml:lang="grc">Κασσία</foreign> aut <foreign xml:lang="grc">κασία</foreign> quibusdam<lb/>',
    )

    stats = reconcile_inline_chapter_headings(root, tmp_path)

    head = root.find(f".//{TEI}head")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert stats.prefixes_restored == 1
    assert head.get("type") == "supplied"
    assert head.find(f".//{TEI}lb") is None
    assert line_text.startswith("Cap. XII. De Cassia. Κασσία")
    assert line_text.count("De Cassia") == 1


def test_heading_restores_cap_prefix_after_previous_fragment_text(tmp_path):
    root = _parse(
        '<pb n="348" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0356.jp2"/>'
        '<div type="textpart" subtype="chapter" n="1.11">'
        '<head><lb n="20"/>Cap. XI. De Malabathro. '
        '<foreign xml:lang="grc">Περὶ Μαλαβάθρου</foreign></head>'
        '<p><lb n="21"/><hi rend="italic">De Malabathro.</hi> Obscuro huic loco lucem</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0356.xml",
        '<pb n="348"/>mari. Cap. XI. <hi rend="italic">De Malabathro.</hi> '
        'Obscuro huic loco lucem<lb/>',
    )

    stats = reconcile_inline_chapter_headings(root, tmp_path)

    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert stats.prefixes_restored == 1
    assert line_text.startswith("Cap. XI. De Malabathro. Obscuro")
    assert line_text.count("De Malabathro") == 1


def test_literal_body_newlines_become_numbered_lines_and_enable_heading(tmp_path):
    root = _parse(
        '<pb n="596" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0602.jp2"/>'
        '<p><lb n="1"/>niger, rotundus, cuiusque culmi crassiores et carnosiores\n'
        'sunt, forte Scirpus lacustris\n'
        'sunt, sed pallida, aut Sc. maritimus. Tertia multo car\n'
        '<lb n="2" break="no"/>nosior, ὁλόσχοινος\n'
        'ob hanc ipsam caussam Sc. Holoschoenus esse nequit.\n'
        '<hi rend="italic">Cladium potius germanicum</hi></p>'
        '<div type="textpart" subtype="chapter" n="4.53">'
        '<head><lb n="3"/>Cap. LIII. De Lichene. '
        '<foreign xml:lang="grc">Περὶ Λειχῆνος</foreign></head>'
        '<p><lb n="4"/>De lichene in roscidis petris nascente\n'
        'aliter Plinius<ref target="#fn53" type="footnote-ref">53</ref>: „Nascitur in saxosis</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0602.xml",
        '<pb n="596"/>Cap. LIII. De lichene in roscidis petris nascente\n'
        'aliter Plinius<ref target="#fn53">⁵³</ref>: ,,Nascitur in saxosis<lb/>',
    )

    inserted = normalize_literal_body_line_breaks(root)
    repaired = repair_known_missing_line_breaks(root)
    stats = reconcile_inline_chapter_headings(root, tmp_path)
    normalize_page_line_numbering(root)

    lines = root.findall(f".//{TEI}p//{TEI}lb")
    chapter_text = _flat_text(root.findall(f".//{TEI}div/{TEI}p")[0])
    assert inserted == 4
    assert repaired == 1
    assert stats.prefixes_restored == 1
    assert [lb.get("n") for lb in lines] == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert lines[5].tail == ""
    assert lines[6].tail.startswith("Cap. LIII. De lichene")
    assert chapter_text.startswith("Cap. LIII. De lichene in roscidis petris nascente")


def test_page_596_removes_false_line_break_before_holoschoenus():
    root = _parse(
        '<pb n="596"/>'
        '<p><lb n="7"/>id et in paludibus Peloponnesi.'
        '<ref target="#fn596_49" type="footnote-ref">49</ref>'
        '<lb n="8"/><foreign xml:lang="grc">Ὁλόσχοινος</foreign> Theophra'
        '<lb n="9" break="no"/>sti</p>'
    )

    repaired = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    first_line = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert "Peloponnesi.49 Ὁλόσχοινος Theophrasti" in first_line


def test_page_576_heading_matches_note_marker_and_repairs_ref_line(tmp_path):
    root = _parse(
        '<pb n="576" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0582.jp2"/>'
        '<div type="textpart" subtype="chapter" n="4.11">'
        '<head><lb n="2"/>Cap. XI. De Holosteo. <foreign xml:lang="grc">Περὶ Ὁλοστέου</foreign></head>'
        '<p><lb n="3"/><hi rend="italic">Holosteum</hi>, inquit <hi rend="italic">Plinius</hi>'
        '<lb n="4"/><ref target="#fn576_64" type="footnote-ref" xml:id="ref-fn576_64">64</ref>, '
        'sine duritia<lb n="5"/>est herba</p>'
        '</div>'
        '<div type="textpart" subtype="chapter" n="4.12">'
        '<head><lb n="6"/>Cap. XII. De Stoebe.</head>'
        '<p><lb n="7"/>Cap. XII. <foreign xml:lang="grc">Στοιϐὴ</foreign> adnumeratur.'
        '<ref target="#fn576_71" type="footnote-ref" xml:id="ref-fn576_71">71</ref>'
        '<lb n="8"/><foreign xml:lang="grc">ὁ φλεὼς (φέως)</foreign>'
        '<lb n="9"/>appellata</p>'
        '</div>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0582.xml",
        '<pb n="576"/>Cap. XI. <hi rend="italic">Holosteum</hi>, inquit '
        '<hi rend="italic">Plinius</hi><ref target="#fn64">⁶⁴</ref>, sine duritia<lb/>',
    )

    repaired = repair_known_missing_line_breaks(root)
    stats = reconcile_inline_chapter_headings(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 2
    assert stats.prefixes_restored == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2", "3", "4"]
    assert line_text.startswith("Cap. XI. Holosteum, inquit Plinius 64, sine duritia")
    assert "adnumeratur.71 ὁ φλεὼς (φέως)" in _flat_text(root.findall(f".//{TEI}div/{TEI}p")[1])


def test_beta_symbol_is_normalized_in_text_and_tail():
    root = _parse(
        '<p><foreign xml:lang="grc">Στοιϐὴ</foreign> and '
        '<foreign xml:lang="grc">ἀστοίϐη</foreign></p>'
    )

    changed = normalize_beta_symbol(root)

    assert changed == 2
    assert "ϐ" not in "".join(root.itertext())
    assert "Στοιβὴ" in "".join(root.itertext())
    assert "ἀστοίβη" in "".join(root.itertext())


def test_page_370_mendesium_heading_text_is_not_italic():
    root = _parse(
        '<div type="textpart" subtype="chapter" n="1.72" xml:id="spr-ch-1.72-la">'
        '<head type="supplied">[Cap. LXXII. De Mendesio.]</head>'
        '<p><lb n="29"/>Cap. LXXII. <hi rend="italic">Mendesium unguentum nomen habet</hi>'
        '<lb n="30"/>ab urbe Mendes</p>'
        '</div>'
    )

    repaired = repair_known_markup_errors(root)

    p = root.find(f".//{TEI}p")
    assert repaired == 1
    assert p.find(f".//{TEI}hi") is None
    assert _flat_text(p).startswith("Cap. LXXII. Mendesium unguentum nomen habet")


def test_fragment_confirmed_line_break_after_footnote_ref_is_removed(tmp_path):
    root = _parse(
        '<pb n="520" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0526.jp2"/>'
        '<p><lb n="7" break="no"/>git<ref target="#fn520_16" type="footnote-ref" '
        'xml:id="ref-fn520_16">16</ref>'
        '<lb n="8"/><foreign xml:lang="grc">πὰ βεβίρε</foreign>, quod signet</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0526.xml",
        '<pb n="520"/>Cap. LII. <foreign xml:lang="grc">Σταφυλίνου</foreign> '
        'nomen aegyptium Rossius le<lb break="no"/>git<ref target="#fn16">¹⁶</ref> '
        '<foreign xml:lang="grc">πὰ βεβίρε</foreign>, quod signet bryoniae similis.<lb/>',
    )

    repaired = repair_fragment_confirmed_inline_footnote_breaks(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 1
    assert [lb.get("n") for lb in lbs] == ["1"]
    assert "git16 πὰ βεβίρε" in line_text


def test_fragment_confirmed_line_break_before_footnote_ref_is_removed(tmp_path):
    root = _parse(
        '<pb n="384" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0392.jp2"/>'
        '<p><lb n="5"/>asphaltites a Iudaeis medii aevi dicitur '
        '<foreign xml:lang="he">אגם החמר</foreign>'
        '<lb n="6"/><ref target="#fn384_10" type="footnote-ref" '
        'xml:id="ref-fn384_10">10</ref>, a no'
        '<lb n="7" break="no"/>strae aetatis Arabibus</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0392.xml",
        '<pb n="384"/>asphaltites a Iudaeis medii aevi dicitur '
        '<foreign xml:lang="he">אגם החמר</foreign><ref target="#fn10">10</ref>, a no'
        '<lb break="no"/>strae aetatis Arabibus<lb/>',
    )

    repaired = repair_fragment_confirmed_inline_footnote_breaks(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert lbs[1].get("break") == "no"
    assert "אגם החמר 10, a nostrae" in line_text


def test_fragment_confirmed_line_break_before_ref_after_foreign_is_removed(tmp_path):
    root = _parse(
        '<pb n="440" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0446.jp2"/>'
        '<p><foreign xml:lang="grc"><lb n="1"/>χρηστὸν αἷμα γεννῶντες.</foreign>'
        '<lb n="2"/><ref target="#fn440_30" type="footnote-ref" '
        'xml:id="ref-fn440_30">30</ref> Paullus aliter, '
        '<foreign xml:lang="grc">ἐπικρατητικός.</foreign>'
        '<lb n="3"/><ref target="#fn440_31" type="footnote-ref" '
        'xml:id="ref-fn440_31">31</ref> Si vera est lectio</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0446.xml",
        '<pb n="440"/><foreign xml:lang="grc">χρηστὸν αἷμα γεννῶντες.</foreign> '
        '<ref target="#fn30">30</ref> Paullus aliter, imo haud satis recte '
        '<foreign xml:lang="grc">ἐπικρατητικός.</foreign> '
        '<ref target="#fn31">31</ref> Si vera est lectio<lb/>',
    )

    repaired = repair_fragment_confirmed_inline_footnote_breaks(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 2
    assert [lb.get("n") for lb in lbs] == ["1"]
    assert "γεννῶντες. 30 Paullus" in line_text
    assert "ἐπικρατητικός. 31 Si vera" in line_text


def test_fragment_confirmed_footnote_ref_on_own_line_is_joined(tmp_path):
    root = _parse(
        '<pb n="411" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0419.jp2"/>'
        '<p><foreign xml:lang="grc"><lb n="1"/>σκληρότερος δ᾽ ὁ θηβαϊκός.</foreign>'
        '<lb n="2"/><ref target="#fn411_98" type="footnote-ref" '
        'xml:id="ref-fn411_98">98</ref>'
        '<lb n="3"/> Caryoton vocat palmam thebaicam, quo nomine praestan'
        '<lb n="4" break="no"/>tior ceteris varietatibus insigniebatur.</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0419.xml",
        '<pb n="411"/><foreign xml:lang="grc">σκληρότερος δ᾽ ὁ θηβαϊκός.</foreign> '
        '<ref target="#fn98">98</ref> Caryoton vocat palmam thebaicam, quo nomine praestan'
        '<lb break="no"/>tior ceteris varietatibus insigniebatur.<lb/>',
    )

    repaired = repair_fragment_confirmed_inline_footnote_breaks(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert repaired == 2
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert lbs[1].get("break") == "no"
    assert "θηβαϊκός. 98 Caryoton" in line_text


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


def test_page_411_thebaic_palm_footnote_ref_is_inline():
    root = _parse(
        '<pb n="411"/>'
        '<p><foreign xml:lang="grc"><lb n="1"/>σκληρότερος δ᾽ ὁ θηβαϊκός, '
        'ἀλλὰ τῇ γεύσει εὐστομώτερος.</foreign>'
        '<lb n="2"/><ref target="#fn411_98" type="footnote-ref" '
        'xml:id="ref-fn411_98">98</ref>'
        '<lb n="3"/> Caryoton vocat palmam thebaicam, quo nomine praestan'
        '<lb n="4" break="no"/>tior ceteris varietatibus insigniebatur.</p>'
    )

    changed = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert changed == 2
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert lbs[1].get("break") == "no"
    assert "εὐστομώτερος. 98 Caryoton" in _flat_text(root.find(f".//{TEI}p"))


def test_page_437_garum_footnote_ref_is_inline_after_foreign():
    root = _parse(
        '<pb n="437"/>'
        '<p><lb n="13"/><foreign xml:lang="grc">Τὸ γάρον</foreign>, vel, '
        'Atticorum more, <foreign xml:lang="grc">ὁ</foreign>'
        '<lb n="14"/><foreign xml:lang="grc">γάρος</foreign>'
        '<lb n="15"/><ref target="#fn437_7" type="footnote-ref" '
        'xml:id="ref-fn437_7">13</ref>, liquor erat, secundum Plinium '
        '<ref target="#fn437_8" type="footnote-ref" xml:id="ref-fn437_8">14</ref>, '
        'expressus e pi-<lb n="16" break="no"/>scium intestinis</p>'
    )

    changed = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert changed == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2", "3"]
    assert lbs[2].get("break") == "no"
    assert "γάρος 13, liquor erat" in _flat_text(root.find(f".//{TEI}p"))


def test_page_381_dadion_starts_new_line_after_note_89(tmp_path):
    root = _parse(
        '<pb n="381" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0389.jp2"/>'
        '<p><lb n="11" break="no"/>rentur, Galenus auctor est.'
        '<ref target="#fn381_89" type="footnote-ref" xml:id="ref-fn381_89">89</ref>'
        '<foreign xml:lang="grc">Δᾳδίον</foreign> proprie est facula, qua lustrationes '
        'et <foreign xml:lang="grc">καθαρ<lb n="12" break="no"/>μοῖ</foreign> instituebantur.</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0389.xml",
        'rentur, Galenus auctor est.<ref target="#fn89">89</ref>\n'
        '<foreign xml:lang="grc">Δᾳδίον</foreign> proprie est facula, qua lustrationes '
        'et <foreign xml:lang="grc">καθαρ-<lb break="no"/>μοῖ</foreign> instituebantur.<lb/>',
    )

    changed = repair_known_missing_line_breaks(root)
    inline_changed = repair_fragment_confirmed_inline_footnote_breaks(root, tmp_path)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert changed == 1
    assert inline_changed == 0
    assert [lb.get("n") for lb in lbs] == ["1", "2", "3"]
    assert lbs[1].getnext().tag == TEI + "foreign"
    assert lbs[1].getnext().text == "Δᾳδίον"
    assert "Galenus auctor est.89 Δᾳδίον" not in _flat_text(root.find(f".//{TEI}p"))


def test_page_388_evacuatio_sive_stays_on_one_line():
    root = _parse(
        '<pb n="388"/>'
        '<p><lb n="9" break="no"/><foreign xml:lang="grc">μαϊσμός</foreign> '
        'dicebatur purgatio corporis et alvi eva'
        '<lb n="10" break="no"/>cuatio, sive'
        '<lb n="11"/> id per superiora fieret.</p>'
    )

    changed = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    assert changed == 1
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert all(not (lb.tail or "").lstrip().startswith("cuatio, sive") for lb in lbs)
    assert "evacuatio, sive" in _flat_text(root.find(f".//{TEI}p"))


def test_page_398_halimus_note_and_arabic_word_are_inline():
    root = _parse(
        '<pb n="398"/>'
        '<p><lb n="7"/>a sepibus, quas frutex constituit: '
        '<foreign xml:lang="grc">ἀσλοερὶ</foreign> et '
        '<foreign xml:lang="grc">ἀσοντρί</foreign>'
        '<lb n="8"/><ref target="#fn398_91" type="footnote-ref" '
        'xml:id="ref-fn398_91">91</ref>.'
        '<lb n="9"/>Inter Arabas <hi rend="italic">Beitarides</hi>'
        '<lb n="10"/><foreign xml:lang="ar">ملوخ</foreign> (malûch) vocat'
        '<ref target="#fn398_92" type="footnote-ref" xml:id="ref-fn398_92">92</ref>.</p>'
    )

    changed = repair_known_missing_line_breaks(root)
    normalize_page_line_numbering(root)

    lbs = root.findall(f".//{TEI}p//{TEI}lb")
    line_text = _flat_text(root.find(f".//{TEI}p"))
    assert changed == 2
    assert [lb.get("n") for lb in lbs] == ["1", "2"]
    assert "ἀσοντρί 91" in line_text
    assert "Beitarides ملوخ" in line_text


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


def test_page_342_preface_continuation_and_book_head_are_structural():
    root = _parse(
        '<div type="textpart" subtype="preface" xml:id="spr-comm-praefatio">'
        '<pb n="342"/>'
        '<fw type="header" place="top">COMMENTARIUS</fw>'
        '<p><lb n="1"/>monio firmatur, <lb n="2"/>patet.'
        '<lb n="3"/>P. 7. <foreign xml:lang="grc">Ὅτι τινὰ</foreign>'
        '<lb n="4"/> Bauhino</p>'
        '</div>'
        '<div type="textpart" subtype="book" n="1" xml:id="book_1">'
        '<head><lb n="5"/>LIB. I.</head>'
        '<div type="textpart" subtype="chapter" n="1.1">'
        '<head type="supplied">[Cap. I. De Iride.]</head>'
        '<p><lb n="6"/>Cap. I. De Iride</p>'
        '</div></div>'
    )

    changed = repair_page_342_book_boundary(root)
    normalize_page_line_numbering(root)
    second_changed = repair_page_342_book_boundary(root)

    preface_ps = root.findall(f".//{TEI}div[@{XID}='spr-comm-praefatio']/{TEI}p")
    book_head = root.find(f".//{TEI}div[@subtype='book']/{TEI}head")
    body_lbs = [
        lb
        for lb in root.findall(f".//{TEI}lb")
        if not any(parent.get("type") == "supplied" for parent in lb.iterancestors(TEI + "head"))
    ]
    assert changed == 3
    assert second_changed == 0
    assert preface_ps[0].get("type") == "continued"
    assert _flat_text(preface_ps[0]) == "monio firmatur, patet."
    assert _flat_text(preface_ps[1]).startswith("P. 7. Ὅτι τινὰ Bauhino")
    assert book_head.get("type") == "supplied"
    assert book_head.text == "[LIB. I.]"
    assert book_head.find(f".//{TEI}lb") is None
    assert [lb.get("n") for lb in body_lbs] == ["1", "2", "3", "4", "5"]


def test_german_opening_quotes_replace_double_commas_in_text_and_tail():
    root = _parse(
        '<p><lb n="1"/>,,a Paraetonii <hi rend="italic">ferme</hi>,, regione</p>'
    )

    changed = normalize_german_opening_quotes(root)

    assert changed == 2
    assert ",," not in "".join(root.itertext())
    assert "„a Paraetonii" in "".join(root.itertext())
    assert "„ regione" in "".join(root.itertext())


def test_page_374_bdellium_body_head_becomes_normal_paragraph():
    root = _parse(
        '<pb n="374"/>'
        '<head><lb n="6"/>Cap. LXXX. Bdellium esse lacrimam arboris arabi-'
        '<lb n="7"/>cae, loco saracenicae, posui.</head>'
        '<p><lb n="8"/>Avicenna disertis verbis</p>'
    )

    changed = repair_known_markup_errors(root)
    normalize_page_line_numbering(root)
    second_changed = repair_known_markup_errors(root)

    ps = root.findall(f".//{TEI}p")
    assert changed == 1
    assert second_changed == 0
    assert root.find(f".//{TEI}head") is None
    assert len(ps) == 2
    assert _flat_text(ps[0]).startswith("Cap. LXXX. Bdellium esse lacrimam")
    assert [lb.get("n") for lb in root.findall(f'.//{TEI}p//{TEI}lb')] == ["1", "2", "3"]


def test_fragment_paragraph_recovery_splits_checked_body_lines(tmp_path):
    root = _parse(
        '<pb n="342" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0350.jp2"/>'
        '<p><lb n="8"/>Cap. I. De Iride. start'
        '<lb n="9"/>continuation.'
        '<lb n="10"/><foreign xml:lang="grc">Θελπίδη</foreign>, aut cum cod. C.'
        '<lb n="11"/>lingua radix exserit.'
        '<lb n="12"/>Appellationem radicis maricae possumus</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0350.xml",
        '<pb n="342"/>Cap. I. De Iride. start<lb/>continuation.<lb/>'
        '<foreign xml:lang="grc">Θελπίδη</foreign>, aut cum cod. C.<lb/>'
        'lingua radix exserit.<lb/>'
        'Appellationem radicis maricae possumus<lb/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)
    normalize_page_line_numbering(root)

    paragraphs = root.findall(f".//{TEI}p")
    assert stats.split == 2
    assert len(paragraphs) == 3
    assert _flat_text(paragraphs[1]).startswith("Θελπίδη")
    assert _flat_text(paragraphs[2]).startswith("Appellationem")


def test_fragment_paragraph_recovery_skips_reviewed_quote_line(tmp_path):
    root = _parse(
        '<pb n="656" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0662.jp2"/>'
        '<p><lb n="1"/>Cap. CXLVI. De thracio lapide apponere libet versus:'
        '<lb n="2"/><foreign xml:lang="grc">Τὴν ἀπὸ Θρηϊκίου νομέες</foreign>'
        '<lb n="3"/>Eumdem autem Agricola habet</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0662.xml",
        '<pb n="656"/>Cap. CXLVI. De thracio lapide apponere libet versus:<lb/>'
        '<foreign xml:lang="grc">Τὴν ἀπὸ Θρηϊκίου νομέες</foreign><lb/>'
        'Eumdem autem Agricola habet<lb/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.skipped == 1
    assert len(root.findall(f".//{TEI}p")) == 1
    row = next(row for row in stats.start_rows if row["candidate_text"].startswith("Τὴν"))
    assert row["candidate_class"] == "reviewed"
    assert row["current_state"] == "skipped"


def test_fragment_paragraph_recovery_merges_page_629_continuation_line(tmp_path):
    root = _parse(
        '<pb n="629" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0635.jp2"/>'
        '<p><lb n="27"/>notat. Esse nimirum herbam latis foliis, sicut Maru,'
        '<lb n="28"/>ad tactum asperis, ramis pariter asperis, sicut pedes lo'
        '<lb n="29" break="no"/>custae (pansis); colorem eius ex viridi et flavo conspici.'
        '</p><p><lb n="30"/>Petendam autem potissimum esse e Khorassan, foliis calloso'
        '<lb n="31" break="no"/>hirsutis: namque aliam vulgarem esse Maru.</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0635.xml",
        '<pb n="629"/>notat. Esse nimirum herbam latis foliis, sicut Maru,<lb/>'
        'ad tactum asperis, ramis pariter asperis, sicut pedes lo<lb break="no"/>'
        'custae (pansis); colorem eius ex viridi et flavo conspici.<lb/>'
        'Petendam autem potissimum esse e Khorassan, foliis calloso<lb break="no"/>'
        'hirsutis: namque aliam vulgarem esse Maru.<lb/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.skipped == 1
    assert stats.merged_false_starts == 1
    assert stats.split == 0
    assert len(root.findall(f".//{TEI}p")) == 1


def test_fragment_paragraph_recovery_merges_page_634_full_line_false_start(tmp_path):
    root = _parse(
        '<pb n="634" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0640.jp2"/>'
        '<p><lb n="30"/>Cap. CXLVI. Daphnoidem habeo Daphnen alpinam,'
        '<lb n="31"/>in montibus Europae australis et Asiae mediae prove'
        '<lb n="32" break="no"/>nientem. Folia sunt laurinis similia, sed molliora et'
        '<lb n="33"/>angustiora. Flores albi in medio gerunt germen conicum.</p>'
        '<p><lb n="34"/>Tota planta, maxime cortex et folia, principio scatent acri,</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0640.xml",
        '<pb n="634"/><p>Cap. CXLVI. Daphnoidem habeo Daphnen alpinam,<lb/>'
        'in montibus Europae australis et Asiae mediae prove<lb break="no"/>'
        'nientem. Folia sunt laurinis similia, sed molliora et<lb/>'
        'angustiora. Flores albi in medio gerunt germen conicum.<lb/>'
        'Tota planta, maxime cortex et folia, principio scatent acri,</p>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.merged_false_starts == 0
    assert stats.split == 0
    assert len(root.findall(f".//{TEI}p")) == 2
    row = next(row for row in stats.start_rows if row["candidate_text"].startswith("Tota planta"))
    assert row["candidate_class"] == "review-terminal-capital"
    assert row["current_state"] == "already-paragraph"


def test_fragment_paragraph_recovery_splits_single_letter_latin_cue(tmp_path):
    root = _parse(
        '<pb n="644" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0650.jp2"/>'
        '<p><lb n="5"/>colebantur et in Tuscorum regione. Sabinum denique'
        '<lb n="6"/>ad compositiones utilissimum iudicat.'
        '<lb n="7"/>E Graecis vinis a nostro chium maxime praedicatur,</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0650.xml",
        '<pb n="643"/>colebantur et in Tuscorum regione. Sabinum denique<lb/>'
        'ad compositiones utilissimum iudicat.<lb/>'
        'E Graecis vinis a nostro chium maxime praedicatur,<lb/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.split == 1
    paragraphs = root.findall(f".//{TEI}p")
    assert len(paragraphs) == 2
    assert _flat_text(paragraphs[1]).startswith("E Graecis")


def test_fragment_paragraph_recovery_reviews_terminal_transition(tmp_path):
    root = _parse(
        '<pb n="644" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0650.jp2"/>'
        '<p><lb n="16"/>Laconia, quae Alcman apyra kai antheos odonta dixit.'
        '<lb n="17"/>De asiaticis vinis indicium diversum est. Noster vi</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0650.xml",
        '<pb n="644"/>Laconia, quae Alcman apyra kai antheos odonta dixit.<lb/>'
        'De asiaticis vinis indicium diversum est. Noster vi<lb/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.split == 0
    assert len(root.findall(f".//{TEI}p")) == 1
    assert stats.start_rows[0]["reason"] == "terminal-transition"
    assert stats.start_rows[0]["candidate_class"] == "review-transition"
    assert stats.start_rows[0]["previous_length"]
    assert stats.start_rows[0]["line_width"]
    assert stats.start_rows[0]["review_decision"] == ""
    assert stats.start_rows[0]["review_note"] == ""
    assert stats.start_rows[0]["current_state"] == "inline-candidate"
    assert stats.start_rows[0]["proposed_action"].startswith("review")


def test_fragment_paragraph_recovery_reviews_page_646_terminal_capital(tmp_path):
    root = _parse(
        '<pb n="646" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0652.jp2"/>'
        '<p><lb n="28"/>rubrum habent, quod LXX. priori loco milton, posteriori'
        '<lb n="29"/>graphida, Chaldaeus paraphrastes vero sikra vertit.'
        '<lb n="30"/>Vulgatissima est cinnabaris nostrae, hydrargyri mi</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0652.xml",
        '<pb n="646"/>rubrum habent, quod LXX. priori loco milton, posteriori<lb/>'
        'graphida, Chaldaeus paraphrastes vero sikra vertit.<lb/>'
        'Vulgatissima est cinnabaris nostrae, hydrargyri mi-<lb break="no"/>',
    )

    stats = recover_fragment_paragraphs(root, tmp_path)

    assert stats.split == 0
    assert len(root.findall(f".//{TEI}p")) == 1
    row = stats.start_rows[0]
    assert row["candidate_text"].startswith("Vulgatissima est cinnabaris")
    assert row["candidate_class"] == "review-terminal-capital"
    assert row["current_state"] == "inline-candidate"
    assert row["prev_current_sum"]
    assert row["current_next_sum"]
    assert row["prev_triple_gap"]
    assert row["boundary_triple_gap"]
    assert row["next_triple_gap"]
    assert row["gap_delta"]


def test_fragment_paragraph_recovery_splits_reviewed_page_643_starts(tmp_path):
    root = _parse(
        '<pb n="643" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0649.jp2"/>'
        '<p><lb n="5"/>colebantur et in Tuscorum regione. Sabinum denique'
        '<lb n="6"/>ad compositiones utilissimum iudicat.'
        '<lb n="7"/>E Graecis vinis a nostro chium maxime praedicatur,'
        '<lb n="16"/>Laconia, quae Alcman apyra kai antheos odonta dixit.'
        '<lb n="17"/>De asiaticis vinis indicium diversum est. Noster vi</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0649.xml",
        '<pb n="643"/>colebantur et in Tuscorum regione. Sabinum denique<lb/>'
        'ad compositiones utilissimum iudicat.<lb/>'
        'E Graecis vinis a nostro chium maxime praedicatur,<lb/>'
        'Laconia, quae Alcman apyra kai antheos odonta dixit.<lb/>'
        'De asiaticis vinis indicium diversum est. Noster vi<lb/>',
    )

    decisions = {
        "pages": {
            "643": {
                "reviewed": True,
                "acceptedStarts": [
                    {"text": "E Graecis vinis a nostro chium maxime praedicatur"},
                    {"text": "De asiaticis vinis indicium diversum est"},
                ],
            }
        }
    }

    stats = recover_fragment_paragraphs(root, tmp_path, review_decisions=decisions)

    assert stats.split == 2
    paragraphs = root.findall(f".//{TEI}p")
    assert len(paragraphs) == 3
    assert _flat_text(paragraphs[1]).startswith("E Graecis")
    assert _flat_text(paragraphs[2]).startswith("De asiaticis")
    assert [row["review_decision"] for row in stats.start_rows] == ["accepted", "accepted"]


def test_page_complete_review_rejects_omitted_review_candidates(tmp_path):
    root = _parse(
        '<pb n="345" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0353.jp2"/>'
        '<p><lb n="13"/>tum euxinum Bosporumque thracicum advehebantur.'
        '<lb n="14"/>Sed fuit etiam alia indicarum mercium via, e Babylone</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0353.xml",
        '<pb n="345"/>tum euxinum Bosporumque thracicum advehebantur.<lb/>'
        'Sed fuit etiam alia indicarum mercium via, e Babylone<lb/>',
    )
    decisions = {"pages": {"345": {"reviewed": True, "acceptedStarts": []}}}

    stats = recover_fragment_paragraphs(root, tmp_path, review_decisions=decisions)

    assert stats.split == 0
    assert stats.review_rejected == 1
    assert stats.unresolved == []
    assert len(root.findall(f".//{TEI}p")) == 1
    row = stats.start_rows[0]
    assert row["review_decision"] == "rejected"
    assert row["current_state"] == "reviewed-rejected"


def test_review_decision_accepts_custom_start_not_in_candidate_tsv(tmp_path):
    root = _parse(
        '<pb n="341" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_0349.jp2"/>'
        '<p><lb n="21"/>ordinary lower-case continuation'
        '<lb n="22"/>custom start hidden by the heuristic</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0349.xml",
        '<pb n="341"/>ordinary lower-case continuation<lb/>'
        'custom start hidden by the heuristic<lb/>',
    )
    decisions = {
        "pages": {
            "341": {
                "reviewed": True,
                "acceptedStarts": [{"text": "custom start hidden by the heuristic"}],
            }
        }
    }

    stats = recover_fragment_paragraphs(root, tmp_path, review_decisions=decisions)

    assert stats.split == 1
    paragraphs = root.findall(f".//{TEI}p")
    assert len(paragraphs) == 2
    assert _flat_text(paragraphs[1]).startswith("custom start hidden")
    row = stats.start_rows[0]
    assert row["reason"] == "review-custom"
    assert row["review_decision"] == "accepted"


def test_review_notes_are_counted_but_do_not_mutate_tei(tmp_path):
    root = _parse(
        '<pb n="359" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_0367.jp2"/>'
        '<p><lb n="1"/>De Bryo<lb n="2"/><foreign xml:lang="grc">Βρύον</foreign> varium</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0367.xml",
        '<pb n="359"/>De Bryo<lb/><foreign xml:lang="grc">Βρύον</foreign> varium<lb/>',
    )
    before = etree.tostring(root, encoding="unicode")
    decisions = {
        "pages": {
            "359": {
                "reviewed": True,
                "acceptedStarts": [],
                "layoutNotes": ["false linebreak after De Bryo. before Βρύον"],
            }
        }
    }

    stats = recover_fragment_paragraphs(root, tmp_path, review_decisions=decisions)

    assert stats.review_notes == 1
    assert etree.tostring(root, encoding="unicode") == before


def test_reviewed_inline_label_moves_into_body_line():
    root = _parse(
        '<pb n="438"/><label>Cap. XXXV.</label> Qui ad iusculum hoc suadentur pi-'
        '<p><lb n="15"/> Qui ad iusculum hoc suadentur pi'
        '<lb n="16" break="no"/>sces, sunt qui</p>'
    )

    changed = repair_reviewed_inline_heads_and_labels(root)
    normalize_page_line_numbering(root)

    assert changed == 1
    assert root.find(f".//{TEI}label") is None
    assert _flat_text(root.find(f".//{TEI}p")).startswith("Cap. XXXV. Qui ad iusculum")


def test_reviewed_printed_head_merges_with_following_body():
    root = _parse(
        '<pb n="658"/>'
        '<head><lb n="10"/>Cap. CLIII. <foreign xml:lang="grc">Θυίτην</foreign> lapidem dici,</head>'
        'Hermolai Barbari iam est sententia.'
        '<p><lb n="11"/>Hermolai Barbari iam est sententia.'
        '<ref target="#fn89" type="footnote-ref">89</ref> Neque tamen</p>'
    )

    changed = repair_reviewed_inline_heads_and_labels(root)
    normalize_page_line_numbering(root)

    paragraphs = root.findall(f".//{TEI}p")
    assert changed == 1
    assert root.find(f".//{TEI}head") is None
    assert len(paragraphs) == 1
    assert _flat_text(paragraphs[0]).count("Hermolai Barbari iam est sententia") == 1
    assert "89 Neque tamen" in _flat_text(paragraphs[0])


def test_reviewed_short_printed_head_joins_following_body_line():
    root = _parse(
        '<pb n="472"/>'
        '<head><lb n="7"/>Cap. CLXXIV.</head>'
        '<p><lb n="8"/><foreign xml:lang="grc">Ὕδνον</foreign>, quod Thraces</p>'
    )

    changed = repair_reviewed_inline_heads_and_labels(root)
    normalize_page_line_numbering(root)

    paragraph = root.find(f".//{TEI}p")
    lbs = paragraph.findall(f".//{TEI}lb")
    assert changed == 1
    assert len(lbs) == 1
    assert _flat_text(paragraph).startswith("Cap. CLXXIV. Ὕδνον")


def test_reviewed_printed_head_removes_loose_duplicate_tail():
    root = _parse(
        '<pb n="472"/>'
        '<head><lb n="29"/>Cap. CLXXVI.</head> De '
        '<p><lb n="30"/>De <foreign xml:lang="grc">μηδική</foreign>, Medicagine</p>'
    )

    changed = repair_reviewed_inline_heads_and_labels(root)
    normalize_page_line_numbering(root)

    paragraph = root.find(f".//{TEI}p")
    assert changed == 1
    assert _flat_text(paragraph).startswith("Cap. CLXXVI. De μηδική")
    assert "De De" not in _flat_text(paragraph)


def test_reviewed_prefix_with_sic_corr_preserves_printed_number():
    root = _parse(
        '<pb n="624"/><p><lb n="25"/><foreign xml:lang="grc">Ὄναγρα</foreign> nil esse potest</p>'
    )

    changed = restore_reviewed_missing_cap_prefixes(root)

    choice = root.find(f".//{TEI}choice")
    assert changed == 1
    assert choice.find(f"{TEI}sic").text == "LXVI"
    assert choice.find(f"{TEI}corr").text == "CXVI"


def test_german_closing_quotes_replace_double_backticks_in_text_and_tail():
    root = _parse('<p><lb n="1"/>utiles.`` <hi rend="italic">quoted``</hi> tail``</p>')

    changed = normalize_german_closing_quotes(root)

    assert changed == 3
    assert "``" not in "".join(root.itertext())
    assert "utiles.“" in "".join(root.itertext())
    assert "quoted“" in "".join(root.itertext())
    assert "tail“" in "".join(root.itertext())


def test_line_end_hyphen_glyphs_are_removed_before_break_no():
    root = _parse(
        '<p><lb n="1"/>Marmaridae, Mar-<lb n="2" break="no"/>cello '
        '<hi rend="italic">Syr-</hi><lb n="3" break="no"/>tin '
        '<foreign xml:lang="grc">μι-</foreign><lb n="4" break="no"/>κρὸν</p>'
    )

    removed = remove_line_end_hyphen_glyphs(root)

    text = etree.tostring(root, encoding="unicode")
    assert removed == 3
    assert "Mar-" not in text
    assert "Syr-" not in text
    assert "μι-" not in text
    assert text.count('break="no"') == 3


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


def test_hyphenation_import_ignores_fragment_footnote_marker_noise(tmp_path):
    root = _parse(
        '<pb n="341" source="https://archive.org/download/b23982500_0002/'
        'b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0349.jp2"/>'
        '<p><lb n="1"/>pius in opere μεταπο'
        '<lb n="2"/>ροποιούσῃ et de reliquis</p>'
    )
    _write_fragment(
        tmp_path,
        "b23982500_0002_0349.xml",
        '<pb n="341"/>pius in opere μεταπο<lb break="no"/>ροποιούσῃ¹⁵ et de reliquis<lb/>',
    )

    stats = import_line_end_hyphenation(root, tmp_path)

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert stats.matched == 1
    assert stats.unmatched == 0
    assert lbs[1].get("break") == "no"


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
