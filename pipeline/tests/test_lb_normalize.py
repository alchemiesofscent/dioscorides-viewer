from lxml import etree

from pharmacopoeia.normalize.lb import (
    assert_lb_n_required,
    drop_unnumbered_lb_outside_notes,
    is_inside_note,
    strip_bloat_attrs,
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
