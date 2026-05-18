from lxml import etree

from pharmacopoeia.migrate.sprengel1830_comm import normalize_page_line_numbering

TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"


def _parse(body: str) -> etree._Element:
    return etree.fromstring(
        (
            f'<TEI xmlns="{TEI_NS}"><text><body>{body}</body></text></TEI>'
        ).encode("utf-8")
    )


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

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
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

    lbs = root.findall(f".//{TEI}p/{TEI}lb")
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
    body_lbs = root.findall(f".//{TEI}p/{TEI}lb")
    assert stats["signature_paragraphs_moved"] == 1
    assert fw.get("type") == "sig"
    assert fw.get("place") == "bottom"
    assert fw.text == "DIOSCORIDES II. Z"
    assert fw.find(f".//{TEI}lb") is None
    assert [lb.get("n") for lb in body_lbs] == ["1", "2"]
