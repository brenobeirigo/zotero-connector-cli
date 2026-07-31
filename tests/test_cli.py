from __future__ import annotations

from contextlib import redirect_stderr
import csv
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from zotero_connector_cli.cli import (
    _batch_retrieval_attempt,
    _child_failed_operationally,
    _child_route,
    _close_temporary_browser_window,
    _interactive_block_reason,
    _open_url,
    _single_batch_instance,
    _write_csv_atomic,
    _write_json_atomic,
    build_parser,
    command_batch_csv,
)
from zotero_connector_cli.windows import Window, executable_candidates


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
        self.assertIsNone(args.report_file)
        self.assertIsNone(args.log_file)

    def test_batch_rejects_model_driven_limit_loop(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "batch-csv",
                    "--csv",
                    r"C:\Downloads\pdf-status.csv",
                    "--limit",
                    "1",
                ]
            )

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
        self.assertFalse(
            _child_failed_operationally(
                {"route": "interactive-required"},
                [{"exitCode": 9}],
                reconcile_only=False,
            )
        )

    def test_batch_promotes_nested_adoption_route(self) -> None:
        self.assertEqual(
            _child_route({"adoption": {"route": "connector-mismatch"}}),
            "connector-mismatch",
        )

    def test_interactive_challenge_titles_are_detected(self) -> None:
        self.assertEqual(
            _interactive_block_reason("Just a moment... - Microsoft Edge"),
            "anti-bot challenge",
        )
        self.assertEqual(
            _interactive_block_reason("Sign in | Taylor & Francis"),
            "sign-in page",
        )
        self.assertIsNone(_interactive_block_reason("Robust Optimization"))

    @patch("zotero_connector_cli.cli.foreground_window")
    @patch("zotero_connector_cli.cli.list_windows")
    @patch("zotero_connector_cli.cli.subprocess.Popen")
    @patch("zotero_connector_cli.cli.find_browser_executable")
    @patch("zotero_connector_cli.cli.time.monotonic", side_effect=[0.0, 0.1])
    def test_open_url_creates_one_isolated_window(
        self,
        _monotonic: Mock,
        executable: Mock,
        popen: Mock,
        windows: Mock,
        foreground: Mock,
    ) -> None:
        existing = Window(1, 10, r"C:\Edge\msedge.exe", "Existing")
        temporary = Window(2, 11, r"C:\Edge\msedge.exe", "Article")
        executable.return_value = Path(r"C:\Edge\msedge.exe")
        windows.side_effect = [[existing], [existing, temporary]]
        foreground.return_value = temporary

        opened = _open_url("edge", "https://example.com/article")

        self.assertEqual(opened, temporary)
        self.assertIn("--new-window", popen.call_args.args[0])
        self.assertNotIn("--new-tab", popen.call_args.args[0])

    @patch("zotero_connector_cli.cli.list_windows", return_value=[])
    @patch("zotero_connector_cli.cli.close_window")
    def test_close_targets_the_exact_temporary_window(
        self,
        close: Mock,
        _windows: Mock,
    ) -> None:
        temporary = Window(2, 11, r"C:\Edge\msedge.exe", "Article")
        _close_temporary_browser_window(temporary)
        close.assert_called_once_with(temporary)

    @patch("zotero_connector_cli.cli._execute_save")
    def test_batch_attempt_uses_internal_serial_save(self, execute: Mock) -> None:
        execute.return_value = (3, {"ok": False, "route": "connector-no-changes"})
        args = SimpleNamespace(
            browser="edge",
            load_wait=0,
            timeout=1,
            settle=0,
            skip_native=True,
            native_wait=0,
        )
        code, _result = _batch_retrieval_attempt(
            "ABCD1234", "https://example.com/article", args
        )
        self.assertEqual(code, 3)
        save_args = execute.call_args.args[0]
        self.assertFalse(save_args.keep_tab)
        self.assertNotIn("subprocess.run", inspect.getsource(command_batch_csv))

    def test_browser_candidates_have_expected_executable_names(self) -> None:
        self.assertTrue(
            all(path.name == "msedge.exe" for path in executable_candidates("edge"))
        )
        self.assertTrue(
            all(path.name == "brave.exe" for path in executable_candidates("brave"))
        )


if __name__ == "__main__":
    unittest.main()
