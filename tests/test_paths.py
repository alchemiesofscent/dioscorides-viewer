import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tei_maker.config import ENV_DATA_ROOT, MissingDataRootError, data_root
from tei_maker.io import paths


class PathTests(unittest.TestCase):
    def test_repo_root_is_project_root(self) -> None:
        self.assertTrue((paths.repo_root() / "README.md").exists())

    def test_missing_data_root_raises_when_required(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MissingDataRootError):
                data_root(require_env=True)

    def test_env_data_root_is_expanded(self) -> None:
        with patch.dict(os.environ, {ENV_DATA_ROOT: "~/Projects/tei-maker-data"}, clear=True):
            self.assertEqual(data_root(require_env=True), Path.home() / "Projects" / "tei-maker-data")

    def test_edition_paths_use_slug(self) -> None:
        slug = "tlg0656.tlg001.berendes1902-ger1"
        self.assertEqual(
            paths.edition_tei_path(slug),
            paths.repo_root() / "editions" / slug / "tei" / "edition.xml",
        )


if __name__ == "__main__":
    unittest.main()
