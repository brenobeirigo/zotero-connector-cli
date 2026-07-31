from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from zotero_connector_cli.cli import (
    _child_failed_operationally,
    _single_batch_instance,
    _write_csv_atomic,
    _write_json_atomic,
    build_parser,
)
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
                "--keep-tab",
                "--json",
            ]
        )
        self.assertEqual(args.command, "save")
        self.assertEqual(args.browser, "edge")
        self.assertEqual(args.parent_key, "ABCD1234")
        self.assertEqual(args.url, "https://example.com/article")
        self.assertTrue(args.keep_tab)
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

    def test_parse_attach_file_command(self) -> None:
        args = build_parser().parse_args(
            [
                "attach-file",
                "--parent-key",
                "ABCD1234",
                "--file",
                r"C:\Downloads\paper.pdf",
            ]
        )
        self.assertEqual(args.command, "attach-file")
        self.assertEqual(args.parent_key, "ABCD1234")
        self.assertEqual(args.file, r"C:\Downloads\paper.pdf")

    def test_parse_batch_csv_command(self) -> None:
        args = build_parser().parse_args(
            [
                "batch-csv",
                "--csv",
                r"C:\Downloads\pdf-status.csv",
                "--update-csv",
                "--reconcile-only",
            ]
        )
        self.assertEqual(args.command, "batch-csv")
        self.assertEqual(args.browser, "edge")
        self.assertTrue(args.update_csv)
        self.assertTrue(args.reconcile_only)
        self.assertEqual(args.retries, 2)
        self.assertEqual(args.limit, 0)
        self.assertIsNone(args.report_file)
        self.assertIsNone(args.log_file)

    def test_atomic_checkpoint_writers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            status = root / "status.csv"
            _write_json_atomic(report, {"ok": True, "processed": 1})
            _write_csv_atomic(
                status,
                [{"zotero_key": "ABCD1234", "status": "in_zotero"}],
            )
            report_data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(report_data["processed"], 1)
            with status.open("r", encoding="utf-8", newline="") as stream:
                self.assertEqual(next(csv.DictReader(stream))["status"], "in_zotero")

    def test_batch_lock_rejects_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "status.csv"
            with _single_batch_instance(csv_path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with _single_batch_instance(csv_path):
                        pass

    def test_batch_distinguishes_unavailable_from_operational_failure(self) -> None:
        self.assertFalse(
            _child_failed_operationally(
                {"route": "connector-no-pdf"},
                [{"exitCode": 3}],
                reconcile_only=False,
            )
        )
        self.assertTrue(
            _child_failed_operationally(
                {"route": "command-timeout"},
                [{"exitCode": None}],
                reconcile_only=False,
            )
        )
        self.assertFalse(
            _child_failed_operationally(
                {"route": "reconcile-only"},
                [],
                reconcile_only=True,
            )
        )

    def test_browser_candidates_have_expected_executable_names(self) -> None:
        self.assertTrue(
            all(path.name == "msedge.exe" for path in executable_candidates("edge"))
        )
        self.assertTrue(
            all(path.name == "brave.exe" for path in executable_candidates("brave"))
        )


if __name__ == "__main__":
    unittest.main()
