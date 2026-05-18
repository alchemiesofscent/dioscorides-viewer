"""Canonical `<pb @facs>` enforcement: JP2 URLs are rewritten to renderable
IIIF JPEG derivatives; the original JP2 URL is preserved on `@source`.

Browsers cannot render JPEG 2000, so any TEI we serve to the static viewer
must reference JPEG or PNG. See docs/TEI_STANDARD.md.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
TEI = f"{{{TEI_NS}}}"

# Pattern: archive.org/download/<item>/<item>_jp2.zip/<item>_jp2%2F<item>_NNNN.jp2
# or with URL-escaped %2F sequences.
_ARCHIVE_JP2_RE = re.compile(
    r"^https?://archive\.org/download/"
    r"(?P<item>[^/]+)/"
    r"(?P<zip>[^/]+_jp2\.zip)/"
    r"(?P<inner>.+\.jp2)$"
)

# IIIF Image API 3 derivative URL pattern for archive.org-hosted JP2s.
# Image identifier is `<item>%2F<zip>%2F<inner>` (URL-encoded slashes).
_IIIF_BASE = "https://iiif.archive.org/image/iiif/3/"
_IIIF_PARAMS = "/full/1200,/0/default.jpg"


def jp2_to_iiif_jpeg(jp2_url: str) -> str | None:
    """Rewrite an archive.org JP2 URL to an IIIF JPEG derivative URL.

    Returns ``None`` if the URL does not match the archive.org JP2 pattern.
    """
    m = _ARCHIVE_JP2_RE.match(jp2_url)
    if not m:
        return None
    item = m.group("item")
    zip_name = m.group("zip")
    inner = m.group("inner")
    # Inner may already be URL-escaped (with %2F). Decode first.
    inner = inner.replace("%2F", "/")
    # Build the IIIF image identifier with %2F separators.
    identifier_parts = [item, zip_name, *inner.split("/")]
    identifier = "%2F".join(quote(part, safe="") for part in identifier_parts)
    return f"{_IIIF_BASE}{identifier}{_IIIF_PARAMS}"


def rewrite_pb_facs(root: etree._Element) -> int:
    """Rewrite every <pb @facs="...jp2"> to its IIIF JPEG derivative.

    Original JP2 URL is preserved on @source so archival provenance survives.
    Returns count rewritten.
    """
    n = 0
    for pb in root.iter(TEI + "pb"):
        facs = pb.get("facs")
        if not facs or ".jp2" not in facs:
            continue
        rewritten = jp2_to_iiif_jpeg(facs)
        if rewritten is None:
            continue
        pb.set("source", facs)
        pb.set("facs", rewritten)
        n += 1
    return n


def assert_no_jp2_in_facs(root: etree._Element) -> list[str]:
    """Return error messages for any @facs still ending in .jp2."""
    errors: list[str] = []
    for elem in root.iter():
        facs = elem.get("facs")
        if facs and ".jp2" in facs:
            errors.append(f"@facs still references .jp2: {facs}")
    return errors
