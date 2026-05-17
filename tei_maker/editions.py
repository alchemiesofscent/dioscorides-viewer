from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from tei_maker.io.paths import repo_root

PUBLIC_REGISTRY_SOURCE = Path("editions/editions.toml")
PUBLIC_REGISTRY_JSON = Path("editions/editions.json")
LOCAL_PRIVATE_REGISTRIES = (
    Path("editions/beck2020_fresh_diplomatic/private_registry.json"),
)


def public_registry_source_path() -> Path:
    return repo_root() / PUBLIC_REGISTRY_SOURCE


def public_registry_json_path() -> Path:
    return repo_root() / PUBLIC_REGISTRY_JSON


def load_registry_source(path: Path | None = None) -> dict[str, Any]:
    source_path = path or public_registry_source_path()
    with source_path.open("rb") as handle:
        data = tomllib.load(handle)
    return normalize_registry(data)


def normalize_registry(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "defaultEdition": data.get("defaultEdition", ""),
        "editions": data.get("editions", []),
    }


def registry_json_text(registry: dict[str, Any]) -> str:
    return json.dumps(normalize_registry(registry), indent=2, ensure_ascii=False) + "\n"


def write_public_registry() -> Path:
    target = public_registry_json_path()
    target.write_text(registry_json_text(load_registry_source()), encoding="utf-8")
    return target


def public_registry_is_fresh() -> bool:
    target = public_registry_json_path()
    if not target.exists():
        return False
    expected = registry_json_text(load_registry_source())
    return target.read_text(encoding="utf-8") == expected


def load_json_registry(path: Path) -> dict[str, Any]:
    return normalize_registry(json.loads(path.read_text(encoding="utf-8")))


def load_public_registry() -> dict[str, Any]:
    return load_json_registry(public_registry_json_path())


def load_available_registries(*, include_private: bool = True) -> list[tuple[Path, dict[str, Any]]]:
    root = repo_root()
    registries = [(public_registry_json_path(), load_public_registry())]
    if include_private:
        for rel_path in LOCAL_PRIVATE_REGISTRIES:
            path = root / rel_path
            if path.exists():
                registries.append((path, load_json_registry(path)))
    return registries


def iter_editions(*, include_private: bool = True) -> list[tuple[Path, dict[str, Any]]]:
    editions: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for registry_path, registry in load_available_registries(include_private=include_private):
        for edition in registry.get("editions", []):
            edition_id = edition.get("id")
            if not edition_id or edition_id in seen:
                continue
            seen.add(edition_id)
            editions.append((registry_path, edition))
    return editions
