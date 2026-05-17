from __future__ import annotations

import os
from pathlib import Path

ENV_DATA_ROOT = "TEI_MAKER_DATA"
DEFAULT_DATA_ROOT = Path.home() / "Projects" / "tei-maker-data"


class MissingDataRootError(RuntimeError):
    """Raised when a generation command needs TEI_MAKER_DATA."""


def configured_data_root() -> Path | None:
    value = os.environ.get(ENV_DATA_ROOT)
    if not value:
        return None
    return Path(value).expanduser()


def default_data_root() -> Path:
    return DEFAULT_DATA_ROOT


def data_root(*, require_env: bool = False) -> Path:
    configured = configured_data_root()
    if configured is not None:
        return configured
    if require_env:
        raise MissingDataRootError(
            f"{ENV_DATA_ROOT} is required for generation commands; "
            "set it to the external tei-maker data root."
        )
    return default_data_root()
