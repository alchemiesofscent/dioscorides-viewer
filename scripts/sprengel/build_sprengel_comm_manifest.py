#!/usr/bin/env python3
"""Populate `editions/sprengel1830-comm/manifest.json` with per-page entries.

Reads `<pb>` elements from the viewer-targeted TEI and emits one manifest
entry per page containing the IIIF JPG URL the viewer's renderImage() expects
in `page.manifest.remoteImage`. Without this, the viewer falls back to the
raw `.jp2` URL in `<pb facs>`, which modern browsers can't render.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Reuse the URL templates and leaf-number logic from the builder so the
# manifest stays in lock-step with the TEI's `<pb facs>` values.
sys.path.insert(0, str(Path(__file__).parent))
from build_sprengel_comm_epidoc import PRIMARY_FACS, BIU_FACS, facs_url  # noqa: E402


IIIF_TEMPLATE = (
    "https://iiif.archive.org/image/iiif/3/"
    "{item}%2F{item}_jp2.zip%2F{item}_jp2%2F{item}_{leaf:04d}.jp2"
    "/full/1200,/0/default.jpg"
)
IIIF_WIDTH = 1200
SOURCE_URL = "https://archive.org/details/b23982500_0002/page/n346/mode/2up"
IIIF_MANIFEST_URL = "https://iiif.archive.org/iiif/b23982500_0002/manifest.json"
IMAGE_ROOT = "https://iiif.archive.org/image/iiif/3/b23982500_0002/"

PRIMARY_ITEM = "b23982500_0002"
BIU_ITEM = "BIUSante_dioscsprengelx02"
BIU_PAGES = {436, 437}


def leaf_for_page(page: int) -> tuple[str, int]:
    """Return (IA item id, leaf number) for a printed page, matching facs_url.

    Pages 436 and 437 are missing from the primary IA scan (the digitized copy
    has those leaves torn out / damaged) and come from the BIU Santé fallback
    at leaves 0437 and 0438. Because the primary scan has no leaves for those
    two pages, its leaf-to-page offset drops from +8 (pages 339–435) to +6
    from page 438 onward.
    """
    if page in BIU_PAGES:
        return BIU_ITEM, page + 1
    if page >= 438:
        return PRIMARY_ITEM, page + 6
    return PRIMARY_ITEM, page + 8


def iiif_url(page: int) -> str:
    item, leaf = leaf_for_page(page)
    return IIIF_TEMPLATE.format(item=item, leaf=leaf)


def page_entry(page: int, pb_facs: str) -> dict:
    item, leaf = leaf_for_page(page)
    return {
        "book_page": str(page),
        "tei_facs": pb_facs,
        "facs": f"https://archive.org/details/{item}/page/n{leaf - 1}/mode/1up",
        "remoteImage": IIIF_TEMPLATE.format(item=item, leaf=leaf),
        "xml_id": f"spr-comm-pb-{leaf:04d}",
        "archive_page_n": leaf - 1,
    }


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def build(source: Path) -> dict:
    tree = ET.parse(source)
    pbs = [el for el in tree.iter() if _local(el.tag) == "pb"]
    pages: list[dict] = []
    for pb in pbs:
        n_raw = pb.attrib.get("n")
        if not n_raw:
            continue
        try:
            n = int(n_raw)
        except ValueError:
            continue
        # Always rebuild facs from the canonical template — the input TEI may
        # have been generated against an older (buggy) offset model.
        pages.append(page_entry(n, facs_url(n)))

    return {
        "total_pages": len(pages),
        "source": "Sprengel 1830 Commentarius OCR-derived viewer XML",
        "source_url": SOURCE_URL,
        "iiif_manifest": IIIF_MANIFEST_URL,
        "image_root": IMAGE_ROOT,
        "iiif_width": IIIF_WIDTH,
        "pages": pages,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build(args.source)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.manifest}: {manifest['total_pages']} pages",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
