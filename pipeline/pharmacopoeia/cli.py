"""pharmacopoeia CLI: migrate, lemmas, validate, viewer."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

EDITIONS = ("berendes1902", "sprengel1829", "beck2020", "sprengel1830-comm")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pharmacopoeia")
    subs = parser.add_subparsers(dest="command", required=True)

    p_migrate = subs.add_parser("migrate", help="Run a per-edition migration")
    p_migrate.add_argument("edition", choices=[*EDITIONS, "all"])

    p_lemmas = subs.add_parser("lemmas", help="Extract or link lemmas")
    p_lemmas_sub = p_lemmas.add_subparsers(dest="lemmas_command", required=True)
    p_lemmas_extract = p_lemmas_sub.add_parser("extract")
    p_lemmas_extract.add_argument("edition")
    p_lemmas_seed = p_lemmas_sub.add_parser("seed-links")
    p_lemmas_seed.add_argument("from_edition")
    p_lemmas_seed.add_argument("to_edition")

    p_validate = subs.add_parser("validate", help="Validate one or all editions")
    p_validate.add_argument("edition", nargs="?", default="all")
    p_validate.add_argument("--profile", default="working",
                            choices=["working", "archival"])

    args = parser.parse_args(argv)

    if args.command == "migrate":
        return _do_migrate(args.edition)
    if args.command == "lemmas":
        if args.lemmas_command == "extract":
            return _do_lemmas_extract(args.edition)
        if args.lemmas_command == "seed-links":
            return _do_lemmas_seed(args.from_edition, args.to_edition)
    if args.command == "validate":
        return _do_validate(args.edition, args.profile)

    parser.print_help()
    return 1


def _do_migrate(edition: str) -> int:
    import importlib
    module_map = {
        "berendes1902": "pharmacopoeia.migrate.berendes1902",
        "sprengel1829": "pharmacopoeia.migrate.sprengel1829",
        "beck2020": "pharmacopoeia.migrate.beck2020",
        "sprengel1830-comm": "pharmacopoeia.migrate.sprengel1830_comm",
    }
    if edition == "all":
        for ed in module_map:
            importlib.import_module(module_map[ed]).run()
        return 0
    importlib.import_module(module_map[edition]).run()
    return 0


def _do_lemmas_extract(edition: str) -> int:
    from pharmacopoeia.lemmas import extract
    extract.run(edition)
    return 0


def _do_lemmas_seed(from_ed: str, to_ed: str) -> int:
    from pharmacopoeia.lemmas import seed_links
    seed_links.run(from_ed, to_ed)
    return 0


def _do_validate(edition: str, profile: str) -> int:
    from pharmacopoeia.validators import checks
    return checks.run(edition, profile=profile)


if __name__ == "__main__":
    sys.exit(main())
