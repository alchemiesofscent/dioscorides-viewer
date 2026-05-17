import unittest


class ImportTests(unittest.TestCase):
    def test_import_package_and_cli(self) -> None:
        import tei_maker
        from tei_maker import cli

        self.assertEqual(tei_maker.__version__, "0.1.0")
        self.assertTrue(callable(cli.main))


if __name__ == "__main__":
    unittest.main()
