from pharmacopoeia.lemmas.slugs import slugify


def test_german_diacritics():
    assert slugify("Ingwer") == "ingwer"
    assert slugify("Süßholz") == "suessholz"
    assert slugify("Mörser") == "moerser"


def test_greek_transliteration():
    assert slugify("Ζιγγίβερις") == "zingiberis"
    assert slugify("Περὶ Ζιγγιβέρεως") == "zingibereos"
    assert slugify("Ἶρις") == "iris"


def test_latin_passthrough():
    assert slugify("De Zingibere") == "zingibere"
    assert slugify("Zingiber officinale") == "zingiber-officinale"


def test_empty_returns_unknown():
    assert slugify("") == "unknown"
    assert slugify("...") == "unknown"


def test_punctuation_stripped():
    assert slugify("Ingwer.") == "ingwer"
    assert slugify("Cap. 189") == "cap-189"
