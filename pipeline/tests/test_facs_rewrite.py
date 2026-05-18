from pharmacopoeia.normalize.facs import jp2_to_iiif_jpeg


def test_archive_jp2_rewrite_unescaped():
    jp2 = (
        "https://archive.org/download/b23982500_0002/"
        "b23982500_0002_jp2.zip/b23982500_0002_jp2/b23982500_0002_0347.jp2"
    )
    out = jp2_to_iiif_jpeg(jp2)
    assert out is not None
    assert out.startswith("https://iiif.archive.org/image/iiif/3/")
    assert "%2F" in out
    assert out.endswith("/full/1200,/0/default.jpg")


def test_archive_jp2_rewrite_url_escaped():
    jp2 = (
        "https://archive.org/download/b23982500_0002/"
        "b23982500_0002_jp2.zip/b23982500_0002_jp2%2Fb23982500_0002_0347.jp2"
    )
    out = jp2_to_iiif_jpeg(jp2)
    assert out is not None
    assert "b23982500_0002%2Fb23982500_0002_jp2.zip%2Fb23982500_0002_jp2%2Fb23982500_0002_0347.jp2" in out


def test_non_jp2_returns_none():
    assert jp2_to_iiif_jpeg("https://example.com/foo.jpg") is None
    assert jp2_to_iiif_jpeg("local:beck2020/images/beck-0001.png") is None
