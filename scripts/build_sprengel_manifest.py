#!/usr/bin/env python3
"""Compatibility wrapper for scripts/sprengel/build_sprengel_manifest.py."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("sprengel") / "build_sprengel_manifest.py"),
        run_name="__main__",
    )
