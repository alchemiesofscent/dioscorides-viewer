from __future__ import annotations

from pathlib import Path

from tei_maker.config import data_root

PIPELINE_STAGES = ("prepare", "ocr", "align", "chunk", "build", "merge", "validate")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def external_root(*, require_env: bool = False) -> Path:
    return data_root(require_env=require_env)


def source_dir(slug: str, *, require_env: bool = True) -> Path:
    return external_root(require_env=require_env) / "sources" / slug


def ocr_dir(slug: str, *, require_env: bool = True) -> Path:
    return external_root(require_env=require_env) / "ocr" / slug


def chunks_dir(slug: str, *, require_env: bool = True) -> Path:
    return external_root(require_env=require_env) / "chunks" / slug


def images_dir(slug: str, *, require_env: bool = True) -> Path:
    return external_root(require_env=require_env) / "images" / slug


def external_audit_dir(slug: str, *, require_env: bool = True) -> Path:
    return external_root(require_env=require_env) / "build" / "audits" / slug


def repo_audit_dir(slug: str) -> Path:
    return repo_root() / "build" / "audits" / slug


def edition_dir(slug: str) -> Path:
    return repo_root() / "editions" / slug


def edition_tei_path(slug: str) -> Path:
    return edition_dir(slug) / "tei" / "edition.xml"


def edition_manifest_path(slug: str) -> Path:
    return edition_dir(slug) / "manifest.json"
