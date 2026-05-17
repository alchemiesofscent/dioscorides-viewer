import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tei_maker.cli import KNOWN_SOURCE_FILES, main
from tei_maker.config import ENV_DATA_ROOT


class CliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_does_not_require_data_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            code, stdout, stderr = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("tei-maker", stdout)
        self.assertEqual(stderr, "")

    def test_validate_does_not_require_data_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            code, stdout, stderr = self.run_cli("validate", "--all")
        self.assertEqual(code, 0)
        self.assertIn("validate stub", stdout)
        self.assertEqual(stderr, "")

    def test_generation_command_requires_data_root(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            code, stdout, stderr = self.run_cli("run", "tlg0656.tlg001.berendes1902-ger1")
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("TEI_MAKER_DATA is required", stderr)

    def test_data_doctor_missing_generated_paths_are_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for slug, filenames in KNOWN_SOURCE_FILES.items():
                source_dir = root / "sources" / slug
                source_dir.mkdir(parents=True)
                for filename in filenames:
                    (source_dir / filename).write_text("fixture\n", encoding="utf-8")

            with patch.dict(os.environ, {ENV_DATA_ROOT: str(root)}, clear=True):
                code, stdout, stderr = self.run_cli("data", "doctor")

        self.assertEqual(code, 0)
        self.assertIn("source ok:", stdout)
        self.assertIn("warning: generated missing:", stderr)


if __name__ == "__main__":
    unittest.main()
