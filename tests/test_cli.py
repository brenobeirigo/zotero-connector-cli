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

from pypdf import PdfWriter

from zotero_connector_cli.ebsco import (
    activate_pdf_access,
    build_ebsco_search_url,
    matches_pdf_access_control,
)
from zotero_connector_cli.cli import (
    _batch_retrieval_attempt,
    _child_failed_operationally,
    _child_route,
    _close_temporary_browser_window,
    _execute_ebsco_pdf,
    _interactive_block_reason,
    _interactive_download_attempt,
    _open_url,
    _single_batch_instance,
    _validate_pdf_identity,
    _wait_for_verified_download,
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
        self.assertFalse(args.interactive_downloads)
        self.assertEqual(args.interactive_wait, 600.0)
        self.assertEqual(args.policy_column, "retrieval_policy")
        self.assertEqual(args.policy_value, "")
        self.assertFalse(args.skip_ebsco)
        self.assertEqual(args.ebsco_max_tabs, 220)

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

    def test_pdf_identity_validation_uses_metadata_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "download.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.add_metadata(
                {"/Title": "A survey of linear cost multicommodity network flows"}
            )
            with path.open("wb") as stream:
                writer.write(stream)
            result = _validate_pdf_identity(
                path,
                title="A survey of linear cost multicommodity network flows",
                doi="10.1287/opre.26.2.209",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["titleMatch"])

    @patch("zotero_connector_cli.cli.time.sleep")
    @patch(
        "zotero_connector_cli.cli.time.monotonic",
        side_effect=[0.0, 0.1, 0.2],
    )
    def test_download_watcher_returns_only_verified_pdf(
        self,
        _monotonic: Mock,
        _sleep: Mock,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "article.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.add_metadata({"/Title": "Robust optimization"})
            with path.open("wb") as stream:
                writer.write(stream)
            downloaded, validation, rejected = _wait_for_verified_download(
                root,
                baseline={},
                title="Robust optimization",
                doi="",
                timeout=10,
            )
            self.assertEqual(downloaded, path.resolve())
            self.assertTrue(validation["ok"])
            self.assertEqual(rejected, [])

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
            interactive_downloads=False,
            title_column="title",
            doi_column="doi",
            skip_ebsco=True,
            browser="edge",
            load_wait=0,
            timeout=1,
            settle=0,
            skip_native=True,
            native_wait=0,
        )
        code, _result = _batch_retrieval_attempt(
            "ABCD1234",
            "https://example.com/article",
            {"title": "A paper", "doi": ""},
            args,
        )
        self.assertEqual(code, 3)
        save_args = execute.call_args.args[0]
        self.assertFalse(save_args.keep_tab)
        self.assertNotIn("subprocess.run", inspect.getsource(command_batch_csv))

    def test_ebsco_search_url_uses_ut_proxy_and_exact_title(self) -> None:
        url = build_ebsco_search_url(
            "Adaptive Large Neighborhood Search with a Constant-Time Feasibility Test"
        )
        self.assertIn("research-ebsco-com.ezproxy2.utwente.nl", url)
        self.assertIn("q=Adaptive+Large+Neighborhood+Search", url)
        self.assertIn("searchMode=boolean", url)

    def test_ebsco_access_control_requires_exact_title(self) -> None:
        title = "Adaptive Large Neighborhood Search with a Constant-Time Feasibility Test"
        self.assertTrue(
            matches_pdf_access_control(
                "Button",
                f"Access now (PDF) {title}.",
                title.casefold(),
            )
        )
        self.assertFalse(
            matches_pdf_access_control(
                "Button",
                "Access now (PDF) A different paper.",
                title,
            )
        )

    @patch("zotero_connector_cli.ebsco.time.sleep")
    @patch("zotero_connector_cli.ebsco.send_keys")
    @patch("zotero_connector_cli.ebsco._focused_control")
    @patch("zotero_connector_cli.ebsco.is_foreground", return_value=True)
    @patch("zotero_connector_cli.ebsco.activate_window")
    def test_ebsco_access_navigation_is_bounded_and_exact(
        self,
        _activate: Mock,
        _foreground: Mock,
        focused: Mock,
        send_keys: Mock,
        _sleep: Mock,
    ) -> None:
        title = "Adaptive Large Neighborhood Search"
        focused.side_effect = [
            ("Button", "Search"),
            ("Button", f"Access now (PDF) {title}."),
        ]
        result = activate_pdf_access(
            Window(2, 11, r"C:\Edge\msedge.exe", "EBSCO"),
            title=title,
            max_tabs=5,
            tab_wait=0,
        )
        self.assertEqual(result["tabIndex"], 1)
        self.assertEqual(
            [call.args[0] for call in send_keys.call_args_list],
            ["{F6}", "{TAB}", "{ENTER}"],
        )

    @patch("zotero_connector_cli.cli._execute_save")
    @patch("zotero_connector_cli.cli._execute_ebsco_pdf")
    @patch("zotero_connector_cli.cli.find_available_pdf")
    def test_informs_batch_prefers_ebsco_before_publisher(
        self,
        native: Mock,
        ebsco: Mock,
        publisher: Mock,
    ) -> None:
        native.return_value = {"ok": False, "route": "native-no-pdf"}
        ebsco.return_value = (0, {"ok": True, "sourceRoute": "ebsco-access-pdf"})
        args = SimpleNamespace(
            interactive_downloads=False,
            title_column="title",
            doi_column="doi",
            skip_ebsco=False,
            skip_native=False,
            native_wait=0,
        )
        code, result = _batch_retrieval_attempt(
            "ABCD1234",
            "https://pubsonline-informs-org.ezproxy2.utwente.nl/doi/epdf/example",
            {"title": "A paper", "doi": "10.1287/trsc.2018.0837"},
            args,
        )
        self.assertEqual(code, 0)
        self.assertEqual(result["sourceRoute"], "ebsco-access-pdf")
        publisher.assert_not_called()

    @patch("zotero_connector_cli.cli._close_temporary_browser_window")
    @patch("zotero_connector_cli.cli._invoke_connector")
    @patch("zotero_connector_cli.cli.activate_pdf_access")
    @patch("zotero_connector_cli.cli.list_windows")
    @patch("zotero_connector_cli.cli.time.sleep")
    @patch("zotero_connector_cli.cli._open_url")
    @patch("zotero_connector_cli.cli.state", return_value=SimpleNamespace())
    @patch("zotero_connector_cli.cli.parent_info")
    @patch("zotero_connector_cli.cli.ping")
    def test_ebsco_route_invokes_connector_in_viewer_and_closes_window(
        self,
        _ping: Mock,
        parent: Mock,
        _state: Mock,
        open_url: Mock,
        _sleep: Mock,
        windows: Mock,
        access: Mock,
        invoke: Mock,
        close: Mock,
    ) -> None:
        search = Window(2, 11, r"C:\Edge\msedge.exe", "Search results - EBSCO")
        viewer = Window(2, 11, r"C:\Edge\msedge.exe", "A paper - EBSCO")
        parent.return_value = {
            "key": "ABCD1234",
            "attachments": [],
            "collections": [{"key": "COLL", "name": "Anticipatory control"}],
        }
        open_url.return_value = search
        windows.return_value = [viewer]
        access.return_value = {"tabIndex": 55, "controlType": "Button"}
        invoke.return_value = {"ok": True, "route": "connector-adopt"}
        args = SimpleNamespace(
            browser="edge",
            ebsco_load_wait=1,
            ebsco_max_tabs=220,
            ebsco_tab_wait=0.04,
            timeout=100,
            settle=10,
        )
        code, result = _execute_ebsco_pdf("ABCD1234", "A paper", args)
        self.assertEqual(code, 0)
        self.assertEqual(result["sourceRoute"], "ebsco-access-pdf")
        invoke.assert_called_once()
        close.assert_called_once_with(search)

    def test_interactive_download_without_url_is_classified(self) -> None:
        code, result = _interactive_download_attempt(
            parent_key="ABCD1234",
            url="",
            title="A paper",
            doi="",
            args=SimpleNamespace(),
        )
        self.assertEqual(code, 4)
        self.assertEqual(result["route"], "manual-no-url")

    def test_interactive_download_attaches_verified_file_serially(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            downloaded = Path(directory) / "article.pdf"
            window = Window(2, 11, r"C:\Edge\msedge.exe", "Article")
            args = SimpleNamespace(
                skip_native=True,
                download_dir=directory,
                browser="edge",
                load_wait=0,
                interactive_wait=10,
                native_wait=0,
            )
            with (
                redirect_stderr(io.StringIO()),
                patch("zotero_connector_cli.cli._open_url", return_value=window),
                patch("zotero_connector_cli.cli.list_windows", return_value=[window]),
                patch("zotero_connector_cli.cli.activate_window"),
                patch(
                    "zotero_connector_cli.cli._wait_for_verified_download",
                    return_value=(downloaded, {"ok": True}, []),
                ),
                patch(
                    "zotero_connector_cli.cli.attach_pdf_file",
                    return_value={"ok": True, "route": "attach-file"},
                ) as attach,
                patch("zotero_connector_cli.cli.sync_library", return_value={"ok": True}),
                patch("zotero_connector_cli.cli._close_temporary_browser_window") as close,
            ):
                code, result = _interactive_download_attempt(
                    parent_key="ABCD1234",
                    url="https://example.com/article",
                    title="A paper",
                    doi="10.1/example",
                    args=args,
                )
            self.assertEqual(code, 0)
            self.assertEqual(result["route"], "interactive-download-attach")
            attach.assert_called_once_with("ABCD1234", str(downloaded), wait_seconds=0)
            close.assert_called_once_with(window)

    def test_browser_candidates_have_expected_executable_names(self) -> None:
        self.assertTrue(
            all(path.name == "msedge.exe" for path in executable_candidates("edge"))
        )
        self.assertTrue(
            all(path.name == "brave.exe" for path in executable_candidates("brave"))
        )


if __name__ == "__main__":
    unittest.main()
