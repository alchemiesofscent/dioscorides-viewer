"""Repository-relative paths for the pharmacopoeia corpus.

Edition identifiers come in three forms:
- **short alias** (``berendes1902``): used in CLI args, lemma URI prefixes,
  and human-facing references.
- **CTS work-version** (``tlg0656.tlg001.berendes1902-ger1``): used as the
  edition directory name and TEI file basename, so the basename is globally
  unique.
- **CTS URN** (``urn:cts:greekLit:tlg0656.tlg001.berendes1902-ger1``):
  recorded in the manifest and TEI header.

The mapping is the single source of truth here in ``EDITION_REGISTRY``.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "corpus" / "dioscorides"
EDITIONS_ROOT = CORPUS_ROOT / "editions"
LEMMAS_ROOT = CORPUS_ROOT / "lemmas"
LEMMA_LINKS_ROOT = CORPUS_ROOT / "lemma-links"
SCHEMAS_ROOT = REPO_ROOT / "schemas"
LEGACY_EDITIONS_ROOT = REPO_ROOT / "editions"

CTS_NAMESPACE = "greekLit"

EDITION_REGISTRY: dict[str, dict[str, str]] = {
    "berendes1902": {
        "cts": "tlg0656.tlg001.berendes1902-ger1",
        "urn": "urn:cts:greekLit:tlg0656.tlg001.berendes1902-ger1",
        "label": "Berendes 1902 (German translation)",
        "legacy_dir": "berendes1902",
    },
    "sprengel1829": {
        "cts": "tlg0656.tlg001.sprengel1829-grclat1",
        "urn": "urn:cts:greekLit:tlg0656.tlg001.sprengel1829-grclat1",
        "label": "Sprengel 1829/1830 (Greek + Latin parallel)",
        "legacy_dir": "sprengel1829",
    },
    "sprengel1830-comm": {
        "cts": "tlg0656.tlg001.sprengel1830-comm-lat1",
        "urn": "urn:cts:greekLit:tlg0656.tlg001.sprengel1830-comm-lat1",
        "label": "Sprengel 1830 Commentarius (Latin commentary)",
        "legacy_dir": "sprengel1830-comm",
    },
    "beck2020": {
        "cts": "tlg0656.tlg001.beck2020-eng1",
        "urn": "urn:cts:greekLit:tlg0656.tlg001.beck2020-eng1",
        "label": "Beck 2020 (English translation; local PDF source)",
        "legacy_dir": "beck2020_fresh_diplomatic",
    },
}


def cts_id(edition_id: str) -> str:
    """Return the CTS work-version form (``tlg0656.tlg001.<version>``)."""
    return EDITION_REGISTRY[edition_id]["cts"]


def cts_urn(edition_id: str) -> str:
    """Return the full CTS URN (``urn:cts:greekLit:...``)."""
    return EDITION_REGISTRY[edition_id]["urn"]


def edition_dir(edition_id: str) -> Path:
    """Edition directory, named for the CTS work-version."""
    return EDITIONS_ROOT / cts_id(edition_id)


def edition_tei(edition_id: str) -> Path:
    """TEI file path. Basename is the CTS work-version so the file is unique."""
    return edition_dir(edition_id) / "tei" / f"{cts_id(edition_id)}.xml"


def edition_tei_relpath(edition_id: str) -> str:
    """Repo-relative POSIX path to the TEI file, for inclusion in URIs."""
    return f"corpus/dioscorides/editions/{cts_id(edition_id)}/tei/{cts_id(edition_id)}.xml"


def legacy_edition_dir(edition_id: str) -> Path:
    return LEGACY_EDITIONS_ROOT / EDITION_REGISTRY[edition_id]["legacy_dir"]


def legacy_edition_tei(edition_id: str) -> Path:
    return legacy_edition_dir(edition_id) / "tei" / "edition.xml"


def lemma_file(edition_id: str, lang: str) -> Path:
    """Lemma taxonomy file path: ``<lemmas>/<short-alias>-<lang>.xml``.

    Short alias rather than CTS form keeps lemma URIs readable
    (e.g. ``lemma:berendes1902-grc:zingiberis``). The CTS URN is still
    recorded in each lemma file's teiHeader.
    """
    return LEMMAS_ROOT / f"{edition_id}-{lang}.xml"


def lemma_link_file(from_ns: str, to_ns: str) -> Path:
    def _clean(ns: str) -> str:
        return ns.removeprefix("lemma:").replace(":", "_")
    return LEMMA_LINKS_ROOT / f"{_clean(from_ns)}--{_clean(to_ns)}.xml"
