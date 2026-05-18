"""Stable slug generation for lemma ids.

NFKD-normalize, drop combining marks, transliterate Greek to Latin (with the
nasal-gamma rule), lowercase, keep [a-z0-9-]+. ASCII-only slugs are portable
across operating systems and filesystems.
"""
from __future__ import annotations

import re
import unicodedata

_GREEK_MAP = {
    "α": "a", "β": "b", "γ": "g", "δ": "d", "ε": "e", "ζ": "z",
    "η": "e", "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m",
    "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s",
    "ς": "s", "τ": "t", "υ": "y", "φ": "ph", "χ": "ch", "ψ": "ps",
    "ω": "o",
}

_GERMAN_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
}

_PREFIX_STRIP = re.compile(r"^(?:Περ[ὶί]|περ[ὶί]|De|de)\s+")


def slugify(text: str) -> str:
    if not text:
        return "unknown"
    text = _PREFIX_STRIP.sub("", text.strip())
    text = text.translate(str.maketrans(_GERMAN_MAP))
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Apply nasal-gamma rule first: γγ→ng, γκ→nk, γχ→nch, γξ→nx.
    no_marks_lower = (
        no_marks.lower()
        .replace("γγ", "ng")
        .replace("γκ", "nk")
        .replace("γχ", "nch")
        .replace("γξ", "nx")
    )
    transliterated = "".join(_GREEK_MAP.get(c, c) for c in no_marks_lower)
    transliterated = transliterated.lower()
    transliterated = re.sub(r"[^a-z0-9]+", "-", transliterated)
    transliterated = re.sub(r"-+", "-", transliterated).strip("-")
    return transliterated or "unknown"
