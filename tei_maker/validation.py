from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from tei_maker.editions import iter_editions
from tei_maker.io.paths import repo_root


@dataclass
class EditionValidation:
    edition_id: str
    registry: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def repo_relative_path(value: str) -> Path:
    if value.startswith(("http://", "https://", "data:", "blob:")):
        raise ValueError("remote path")
    return repo_root() / value


def validate_edition(registry_path: Path, edition: dict[str, object]) -> EditionValidation:
    edition_id = str(edition.get("id") or "<missing-id>")
    result = EditionValidation(edition_id=edition_id, registry=registry_path)

    tei_value = edition.get("tei")
    if not isinstance(tei_value, str) or not tei_value:
        result.errors.append("missing tei path")
    else:
        try:
            tei_path = repo_relative_path(tei_value)
        except ValueError:
            result.warnings.append(f"remote tei path not parsed: {tei_value}")
        else:
            if not tei_path.exists():
                result.errors.append(f"tei path missing: {tei_value}")
            else:
                try:
                    ET.parse(tei_path)
                except ET.ParseError as exc:
                    result.errors.append(f"tei XML parse error: {tei_value}: {exc}")

    manifest_value = edition.get("manifest")
    if not isinstance(manifest_value, str) or not manifest_value:
        result.errors.append("missing manifest path")
    else:
        try:
            manifest_path = repo_relative_path(manifest_value)
        except ValueError:
            result.warnings.append(f"remote manifest path not parsed: {manifest_value}")
        else:
            if not manifest_path.exists():
                result.errors.append(f"manifest path missing: {manifest_value}")
            else:
                try:
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    result.errors.append(f"manifest JSON parse error: {manifest_value}: {exc}")

    return result


def validate_registered_editions(target: str | None = None) -> list[EditionValidation]:
    results: list[EditionValidation] = []
    for registry_path, edition in iter_editions(include_private=True):
        edition_id = str(edition.get("id") or "")
        if target and edition_id != target:
            continue
        results.append(validate_edition(registry_path, edition))
    if target and not results:
        missing = EditionValidation(edition_id=target, registry=repo_root())
        missing.errors.append("edition id not found in available registries")
        results.append(missing)
    return results
