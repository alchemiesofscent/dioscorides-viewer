#!/usr/bin/env python3
"""Extract private Beck PDF pages as beck-1.jpg through beck-710.jpg."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_PAGES = 710
POPPLER_IMAGE_RE = re.compile(r"^beck-(0*\d+)\.jpg$")


def normalize_poppler_names(outdir: Path) -> None:
    for image in sorted(outdir.glob("beck-*.jpg")):
        match = POPPLER_IMAGE_RE.match(image.name)
        if not match:
            continue
        page = int(match.group(1))
        normalized = outdir / f"beck-{page}.jpg"
        if image == normalized:
            continue
        if normalized.exists():
            image.unlink()
        else:
            image.rename(normalized)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the local Beck PDF")
    parser.add_argument(
        "--outdir",
        default="editions/beck2020/page_images",
        help="Directory for ignored local page images",
    )
    parser.add_argument("--pages", type=int, default=EXPECTED_PAGES, help="Number of pages to extract")
    parser.add_argument("--resolution", type=int, default=180, help="Image resolution for pdftoppm")
    parser.add_argument("--normalize-only", action="store_true", help="Only normalize existing Poppler image names")
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    if not args.normalize_only:
        pdf = Path(args.pdf)
        if not pdf.exists():
            raise SystemExit(f"Beck PDF not found: {pdf}. Pass the exact local Beck PDF filename.")
        if not pdf.is_file():
            raise SystemExit(f"Beck PDF path is not a file: {pdf}")

        pdftoppm = shutil.which("pdftoppm")
        if not pdftoppm:
            raise SystemExit("pdftoppm is required to extract Beck page images; install poppler-utils and rerun.")

        prefix = outdir / "beck"
        command = [
            pdftoppm,
            "-jpeg",
            "-r",
            str(args.resolution),
            "-f",
            "1",
            "-l",
            str(args.pages),
            str(pdf),
            str(prefix),
        ]
        subprocess.run(command, check=True)

    normalize_poppler_names(outdir)

    missing = [outdir / f"beck-{i}.jpg" for i in range(1, args.pages + 1) if not (outdir / f"beck-{i}.jpg").exists()]
    if missing:
        print(f"Missing {len(missing)} expected image(s); first missing: {missing[0]}", file=sys.stderr)
        return 1

    print(f"Wrote {args.pages} images to {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
