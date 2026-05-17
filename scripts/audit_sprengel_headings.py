#!/usr/bin/env python3
"""Compatibility wrapper for scripts/sprengel/audit_sprengel_headings.py."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).with_name("sprengel") / "audit_sprengel_headings.py"),
        run_name="__main__",
    )
