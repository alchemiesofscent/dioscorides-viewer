from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from tei_maker.config import ENV_DATA_ROOT, MissingDataRootError, configured_data_root, data_root, default_data_root
from tei_maker.io.paths import PIPELINE_STAGES, external_root, repo_root


def _require_data_root() -> int:
    try:
        root = data_root(require_env=True)
    except MissingDataRootError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{ENV_DATA_ROOT}={root}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    status = _require_data_root()
    if status:
        return status
    start = args.from_stage or PIPELINE_STAGES[0]
    end = args.to_stage or PIPELINE_STAGES[-1]
    print(f"run stub: slug={args.slug} from={start} to={end}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target = "--all" if args.all else args.slug
    if not target:
        print("error: provide a slug or --all", file=sys.stderr)
        return 2
    print(f"validate stub: target={target}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    status = _require_data_root()
    if status:
        return status
    target = "--all" if args.all else args.slug
    if not target:
        print("error: provide a slug or --all", file=sys.stderr)
        return 2
    print(f"audit stub: target={target}")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    status = _require_data_root()
    if status:
        return status
    print(f"ocr stub: slug={args.slug} backend={args.backend}")
    return 0


def cmd_editions_export_json(args: argparse.Namespace) -> int:
    root = repo_root()
    toml_path = root / "editions" / "editions.toml"
    json_path = root / "editions" / "editions.json"
    mode = "check" if args.check else "write"
    print(f"editions export-json stub: mode={mode} source={toml_path} target={json_path}")
    return 0


def cmd_data_doctor(_args: argparse.Namespace) -> int:
    configured = configured_data_root()
    root = configured or default_data_root()
    source = ENV_DATA_ROOT if configured else "default"
    print(f"data root ({source}): {root}")
    print(f"exists: {root.exists()}")
    print(f"repo root: {repo_root()}")
    if configured is None:
        print(f"warning: {ENV_DATA_ROOT} is not set; generation commands will fail", file=sys.stderr)
    return 0


def cmd_baseline_capture(_args: argparse.Namespace) -> int:
    status = _require_data_root()
    if status:
        return status
    print(f"baseline capture stub: root={external_root(require_env=True)}")
    return 0


def cmd_baseline_diff(_args: argparse.Namespace) -> int:
    status = _require_data_root()
    if status:
        return status
    print(f"baseline diff stub: root={external_root(require_env=True)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tei-maker",
        description="Build, validate, audit, and package TEI/EpiDoc editions.",
    )
    parser.add_argument("--version", action="version", version="tei-maker 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    run_p = subparsers.add_parser("run", help="Run the canonical pipeline for an edition.")
    run_p.add_argument("slug")
    run_p.add_argument("--from", dest="from_stage", choices=PIPELINE_STAGES)
    run_p.add_argument("--to", dest="to_stage", choices=PIPELINE_STAGES)
    run_p.set_defaults(func=cmd_run)

    validate_p = subparsers.add_parser("validate", help="Validate committed TEI and manifests.")
    validate_target = validate_p.add_mutually_exclusive_group()
    validate_target.add_argument("slug", nargs="?")
    validate_target.add_argument("--all", action="store_true")
    validate_p.set_defaults(func=cmd_validate)

    audit_p = subparsers.add_parser("audit", help="Generate audit reports for an edition.")
    audit_target = audit_p.add_mutually_exclusive_group()
    audit_target.add_argument("slug", nargs="?")
    audit_target.add_argument("--all", action="store_true")
    audit_p.set_defaults(func=cmd_audit)

    ocr_p = subparsers.add_parser("ocr", help="Run OCR for an edition.")
    ocr_p.add_argument("slug")
    ocr_p.add_argument("--backend", choices=("tesseract", "gemini"), required=True)
    ocr_p.set_defaults(func=cmd_ocr)

    editions_p = subparsers.add_parser("editions", help="Manage edition registries.")
    editions_sub = editions_p.add_subparsers(dest="editions_command")
    export_p = editions_sub.add_parser("export-json", help="Generate the viewer edition registry.")
    export_p.add_argument("--check", action="store_true", help="Check whether generated JSON is fresh.")
    export_p.set_defaults(func=cmd_editions_export_json)

    data_p = subparsers.add_parser("data", help="Inspect external data configuration.")
    data_sub = data_p.add_subparsers(dest="data_command")
    doctor_p = data_sub.add_parser("doctor", help="Report external data root status.")
    doctor_p.set_defaults(func=cmd_data_doctor)

    baseline_p = subparsers.add_parser("baseline", help="Capture and compare baseline artifacts.")
    baseline_sub = baseline_p.add_subparsers(dest="baseline_command")
    capture_p = baseline_sub.add_parser("capture", help="Capture baseline artifacts.")
    capture_p.set_defaults(func=cmd_baseline_capture)
    diff_p = baseline_sub.add_parser("diff", help="Compare current artifacts against a baseline.")
    diff_p.set_defaults(func=cmd_baseline_diff)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
