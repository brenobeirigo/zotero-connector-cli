from __future__ import annotations

import unittest

from zotero_connector_cli.cli import build_parser
from zotero_connector_cli.windows import executable_candidates


class CliTests(unittest.TestCase):
    def test_parse_save_command(self) -> None:
        args = build_parser().parse_args(
            [
                "save",
                "--browser",
                "edge",
                "--parent-key",
                "ABCD1234",
                "--url",
                "https://example.com/article",
                "--json",
            ]
        )
        self.assertEqual(args.command, "save")
        self.assertEqual(args.browser, "edge")
        self.assertEqual(args.parent_key, "ABCD1234")
        self.assertEqual(args.url, "https://example.com/article")
        self.assertTrue(args.json)

    def test_parse_save_active_command(self) -> None:
        args = build_parser().parse_args(
            ["save-active", "--browser", "brave", "--parent-key", "ABCD1234"]
        )
        self.assertEqual(args.command, "save-active")
        self.assertEqual(args.browser, "brave")
        self.assertEqual(args.parent_key, "ABCD1234")

    def test_parse_find_pdf_command(self) -> None:
        args = build_parser().parse_args(["find-pdf", "--parent-key", "ABCD1234"])
        self.assertEqual(args.command, "find-pdf")
        self.assertEqual(args.parent_key, "ABCD1234")

    def test_browser_candidates_have_expected_executable_names(self) -> None:
        self.assertTrue(
            all(path.name == "msedge.exe" for path in executable_candidates("edge"))
        )
        self.assertTrue(
            all(path.name == "brave.exe" for path in executable_candidates("brave"))
        )


if __name__ == "__main__":
    unittest.main()
