from lxml import etree

from pharmacopoeia.lemmas import seed_links
from pharmacopoeia.lemmas.extract import _extract_from_heads
from pharmacopoeia.migrate.sprengel1829 import (
    is_chapter_major_split,
    is_page_first_diplomatic,
    normalize_page_first_root,
    paired_chapter_milestone_count,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml.encode("utf-8"))


def _page_first_xml() -> str:
    return f'''
    <TEI xmlns="{TEI_NS}">
      <text>
        <body>
          <div type="edition" subtype="diplomatic">
            <div type="textpart" subtype="book" n="1">
              <div type="textpart" subtype="proem" n="prooimion">
                <div type="page" subtype="diplomatic-page" n="9">
                  <pb n="9" facs="page_images/page-0041.png" xml:id="spr-pb-0041"/>
                  <ab type="pageZone" place="top" xml:lang="grc">
                    <milestone unit="chapter" type="chapterStart" n="1.1"
                      xml:id="spr-ch-1.1-grc" xml:lang="grc"
                      label="Περὶ Ἴριδος" corresp="#spr-ch-1.1-la"/>
                    <p><lb n="6"/><seg type="chapterTitle">Κεφ. α΄.</seg> Ἶρις</p>
                  </ab>
                  <ab type="pageZone" place="bottom" xml:lang="la">
                    <milestone unit="chapter" type="chapterStart" n="1.1"
                      xml:id="spr-ch-1.1-la" xml:lang="la"
                      label="De Iride" corresp="#spr-ch-1.1-grc"/>
                    <p><lb n="6"/>Iris</p>
                  </ab>
                </div>
              </div>
            </div>
          </div>
        </body>
      </text>
    </TEI>
    '''


def test_sprengel1829_normalizer_preserves_page_first_zones():
    root = _parse(_page_first_xml())

    stats = normalize_page_first_root(root)

    assert is_page_first_diplomatic(root) is True
    assert is_chapter_major_split(root) is False
    assert stats["paired_chapters"] == 1
    assert len(root.xpath(".//*[local-name()='div' and @subtype='edition' and @xml:lang]")) == 0
    page = root.xpath(".//*[local-name()='div' and @subtype='diplomatic-page']")[0]
    zones = page.xpath("./*[local-name()='ab' and @type='pageZone']")
    assert [zone.get("place") for zone in zones] == ["top", "bottom"]


def test_sprengel1829_normalizer_rejects_chapter_major_split():
    root = _parse(
        f'''<TEI xmlns="{TEI_NS}"><text><body>
        <div type="textpart" subtype="edition" xml:lang="grc"/>
        <div type="textpart" subtype="edition" xml:lang="la"/>
        </body></text></TEI>'''
    )

    try:
        normalize_page_first_root(root)
    except ValueError as exc:
        assert "chapter-major" in str(exc)
    else:
        raise AssertionError("expected chapter-major Sprengel TEI to be rejected")


def test_sprengel1829_lemmas_extract_from_chapter_milestones():
    root = _parse(_page_first_xml())

    records = _extract_from_heads(root, "sprengel1829")

    assert "lemma:sprengel1829-grc:iridos" in records["grc"]
    assert "lemma:sprengel1829-la:iride" in records["la"]
    assert paired_chapter_milestone_count(root) == 1
    milestones = root.xpath(".//*[local-name()='milestone' and @unit='chapter']")
    assert milestones[0].get("corresp") == "lemma:sprengel1829-grc:iridos"
    assert milestones[1].get("corresp") == "lemma:sprengel1829-la:iride"


def test_sprengel1829_seed_links_pair_milestones(tmp_path, monkeypatch):
    path = tmp_path / "sprengel.xml"
    path.write_text(_page_first_xml(), encoding="utf-8")
    monkeypatch.setattr(seed_links, "edition_tei", lambda _edition: path)

    pairs = seed_links._sprengel_grc_la_pairs()

    assert pairs == [{
        "from": "lemma:sprengel1829-grc:iridos",
        "to": "lemma:sprengel1829-la:iride",
        "cert": "high",
        "resp": "#sprengel_himself",
        "evidence": (
            "Sprengel's parallel Greek/Latin printing pairs chapter 1.1 "
            "(Περὶ Ἴριδος) with (De Iride)."
        ),
    }]
