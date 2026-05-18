"""Repository-relative paths for the pharmacopoeia corpus."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "corpus" / "dioscorides"
EDITIONS_ROOT = CORPUS_ROOT / "editions"
LEMMAS_ROOT = CORPUS_ROOT / "lemmas"
LEMMA_LINKS_ROOT = CORPUS_ROOT / "lemma-links"
SCHEMAS_ROOT = REPO_ROOT / "schemas"
LEGACY_EDITIONS_ROOT = REPO_ROOT / "editions"


def edition_dir(edition_id: str) -> Path:
    return EDITIONS_ROOT / edition_id


def edition_tei(edition_id: str) -> Path:
    return edition_dir(edition_id) / "tei" / "edition.xml"


def legacy_edition_tei(legacy_id: str) -> Path:
    return LEGACY_EDITIONS_ROOT / legacy_id / "tei" / "edition.xml"


def lemma_file(edition_id: str, lang: str) -> Path:
    return LEMMAS_ROOT / f"{edition_id}-{lang}.xml"


def lemma_link_file(from_ns: str, to_ns: str) -> Path:
    def _clean(ns: str) -> str:
        return ns.removeprefix("lemma:").replace(":", "_")
    return LEMMA_LINKS_ROOT / f"{_clean(from_ns)}--{_clean(to_ns)}.xml"
