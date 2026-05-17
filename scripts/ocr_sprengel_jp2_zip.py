#!/usr/bin/env python3
"""Compatibility wrapper for scripts/sprengel/ocr_sprengel_jp2_zip.py."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("sprengel") / "ocr_sprengel_jp2_zip.py"),
        run_name="__main__",
    )
