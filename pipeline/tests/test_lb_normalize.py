from io import BytesIO

from lxml import etree

from pharmacopoeia.normalize.lb import (
    assert_lb_n_required,
    drop_unnumbered_lb_outside_notes,
    indent_lb_lines_to_parent_depth,
    is_inside_note,
    join_split_lb_tail_lines,
    lb_not_line_initial_count,
    put_lbs_at_line_start,
    serialize_with_epidoc_indentation,
    strip_bloat_attrs,
    strip_trailing_line_whitespace,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def test_strip_bloat_attrs():
    root = _parse(
        f'<TEI xmlns="{TEI_NS}"><ab><lb n="1" bbox="0 0 10 10" cert="0.9"/>'
        "</ab></TEI>"
    )
    n = strip_bloat_attrs(root)
    assert n == 2
    lb = root.find(f"{{{TEI_NS}}}ab/{{{TEI_NS}}}lb")
    assert "bbox" not in lb.attrib
    assert "cert" not in lb.attrib
    assert lb.get("n") == "1"


def test_is_inside_note_true():
    root = _parse(f'<TEI xmlns="{TEI_NS}"><note><lb/></note></TEI>')
    lb = root.find(f".//{{{TEI_NS}}}lb")
    assert is_inside_note(lb) is True


def test_is_inside_note_false():
    root = _parse(f'<TEI xmlns="{TEI_NS}"><ab><lb/></ab></TEI>')
    lb = root.find(f".//{{{TEI_NS}}}lb")
    assert is_inside_note(lb) is False


def test_assert_lb_n_required():
    root = _parse(
        f'<TEI xmlns="{TEI_NS}"><ab><lb/><lb n="2"/></ab>'
        '<note><lb/></note></TEI>'
    )
    errs = assert_lb_n_required(root)
    assert len(errs) == 1
    assert "without @n" in errs[0]


def test_drop_unnumbered_lb_outside_notes():
    root = _parse(
        f'<TEI xmlns="{TEI_NS}"><ab>before<lb/>after<lb n="2"/>more</ab>'
        '<note>x<lb/>y</note></TEI>'
    )
    n = drop_unnumbered_lb_outside_notes(root)
    assert n == 1
    # Tail "after" should have been merged into ab.text.
    ab = root.find(f"{{{TEI_NS}}}ab")
    assert ab.text == "beforeafter"
    # <note>'s <lb/> stays (it's inside a note).
    note = root.find(f"{{{TEI_NS}}}note")
    assert note.find(f"{{{TEI_NS}}}lb") is not None


def test_put_lbs_at_line_start_handles_mixed_content():
    xml = (
        f'<TEI xmlns="{TEI_NS}"><text><body>'
        '<p>ma-<lb n="1"/>iorum <foreign xml:lang="grc">μεταπο'
        '<lb n="2"/>ροποι</foreign><hi rend="italic">Tu<lb n="3"/>laíov</hi></p>'
        '<head><lb n="4"/>Title</head><fw type="header"><lb n="5"/>Header</fw>'
        '<note>note<lb/>tail</note></body></text></TEI>'
    )

    out, moved = put_lbs_at_line_start(xml)

    assert moved == 6
    assert lb_not_line_initial_count(out) == 0
    assert "\n<lb n=\"1\"/>iorum" in out
    assert "μεταπο\n<lb n=\"2\"/>ροποι" in out
    assert "<head>\n<lb n=\"4\"/>Title" in out
    parsed = _parse(out)
    assert len(parsed.xpath(".//*[local-name()='lb']")) == 6


def test_put_lbs_at_line_start_is_idempotent():
    xml = f'<TEI xmlns="{TEI_NS}"><p>alpha\n<lb n="1"/>beta</p></TEI>'

    first, moved_first = put_lbs_at_line_start(xml)
    second, moved_second = put_lbs_at_line_start(first)

    assert moved_first == 0
    assert moved_second == 0
    assert second == first


def test_put_lbs_at_line_start_removes_lb_indentation():
    xml = f'<TEI xmlns="{TEI_NS}"><p>alpha\n          <lb n="1"/>beta</p></TEI>'

    out, moved = put_lbs_at_line_start(xml)

    assert moved == 0
    assert out == f'<TEI xmlns="{TEI_NS}"><p>alpha\n<lb n="1"/>beta</p></TEI>'


def test_join_split_lb_tail_lines():
    xml = (
        '<p>\n<lb n="1"/>\nalpha\n<lb n="2"/>\n<foreign>β</foreign>\n'
        '<lb n="3"/>\n<lb n="4"/>\n</p>'
    )

    out, joined = join_split_lb_tail_lines(xml)

    assert joined == 2
    assert '<lb n="1"/>alpha' in out
    assert '<lb n="2"/><foreign>β</foreign>' in out
    assert '<lb n="3"/>\n<lb n="4"/>' in out


def test_indent_lb_lines_to_parent_depth():
    xml = (
        f'<TEI xmlns="{TEI_NS}">\n'
        "<text>\n"
        "<body>\n"
        "<p>alpha\n"
        '<lb n="1"/>beta\n'
        "</p>\n"
        "</body>\n"
        "</text>\n"
        "</TEI>\n"
    )

    out, changed = indent_lb_lines_to_parent_depth(xml)

    assert changed == 1
    assert "\n        <lb n=\"1\"/>beta\n" in out


def test_serialize_with_epidoc_indentation_mixed_content():
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<?xml-model href="epidoc.rng"?>'
        + (
            f'<TEI xmlns="{TEI_NS}"><text><body><div>'
            '<head><lb n="1"/>Title</head>'
            '<p>ma-<lb n="2"/>ior <foreign xml:lang="grc">με'
            '<lb n="3"/>τα</foreign><lb n="4"/>\ntext</p>'
            '</div></body></text></TEI>'
        ).encode("utf-8")
    )
    tree = etree.parse(BytesIO(xml))

    out, stats = serialize_with_epidoc_indentation(tree)

    assert "\n<?xml-model href=\"epidoc.rng\"?>\n<TEI" in out
    assert "\n          <lb n=\"1\"/>Title</head>" in out
    assert "\n          <lb n=\"2\"/>ior <foreign" in out
    assert "\n            <lb n=\"3\"/>τα</foreign>" in out
    assert "\n          <lb n=\"4\"/>text</p>" in out
    assert stats["line_start_moved"] == 2
    assert stats["tail_lines_joined"] == 1
    assert lb_not_line_initial_count(out) == 0
    assert etree.fromstring(out.encode("utf-8")).xpath("count(.//*[local-name()='lb'])") == 4.0


def test_strip_trailing_line_whitespace():
    out, stripped = strip_trailing_line_whitespace("alpha \n<lb n=\"1\"/>beta\t\n")

    assert stripped == 2
    assert out == "alpha\n<lb n=\"1\"/>beta\n"
