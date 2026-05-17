import contextlib
import io
import os
import unittest
from unittest.mock import patch

from tei_maker.cli import main


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


if __name__ == "__main__":
    unittest.main()
