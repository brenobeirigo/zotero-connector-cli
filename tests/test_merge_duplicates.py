from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from zotero_core.dedup import MERGE, REVIEW, TRASH
from zotero_core.identity import LibraryItem

from zotero_connector_cli.cli import command_merge_duplicates
from zotero_connector_cli.merge_duplicates import (
    apply_duplicates_plan,
    load_plan,
    save_plan,
    scan_duplicates,
    summarize,
)


def library():
    """Three copies of one conference paper, plus an unrelated title pair."""
    return [
        LibraryItem(
            key="B7WKDLMX",
            title="ASyMTRe",
            year="2005",
            doi="10.1109/ROBOT.2005.1570327",
            first_creator="Tang",
            citation_key="tang2005asymtre",
            collection_keys=("INTERACT1",),
        ),
        LibraryItem(
            key="AMV7KCYM",
            title="ASyMTRe",
            year="2005",
            doi="10.1109/ROBOT.2005.1570327",
            first_creator="Tang",
        ),
        LibraryItem(
            key="N8Y8RF82",
            title="ASyMTRe",
            year="2005",
            doi="10.1109/ROBOT.2005.1570327",
            first_creator="Tang",
            collection_keys=("COALITION1",),
        ),
        LibraryItem(key="E1", title="EBSCO", year="2026"),
        LibraryItem(key="E2", title="EBSCO", year="2026"),
    ]


class RecordingBackend:
    """Answers with a fixed library and records every write."""

    name = "recording"

    def __init__(self, items):
        self._items = items
        self.merged: list[tuple[str, list[str]]] = []
        self.trashed: list[str] = []

    def snapshot_library(self):
        return list(self._items)

    def merge_items(self, master_key, other_keys):
        self.merged.append((master_key, list(other_keys)))

    def trash_items(self, item_keys):
        self.trashed.extend(item_keys)


class ScanTests(unittest.TestCase):
    def test_scan_groups_the_doi_triplicate_and_defers_the_title_pair(self):
        plan = scan_duplicates(backend=RecordingBackend(library()))

        by_rule = {group.rule: group for group in plan.groups}
        self.assertEqual(by_rule["doi"].action, MERGE)
        self.assertEqual(by_rule["doi"].master_key, "B7WKDLMX")
        self.assertEqual(by_rule["title-year"].action, REVIEW)
        self.assertEqual(plan.items_removed, 2)

    def test_summary_names_what_was_left_for_a_person(self):
        plan = scan_duplicates(backend=RecordingBackend(library()))
        result = summarize(plan)

        self.assertFalse(result["applied"])
        self.assertEqual(result["counts"]["merge"], 1)
        self.assertEqual(result["counts"]["review"], 1)
        self.assertEqual(result["reviewGroups"][0]["keys"], ["E1", "E2"])

    def test_apply_writes_only_the_confident_group(self):
        backend = RecordingBackend(library())
        plan = scan_duplicates(backend=backend)

        apply_duplicates_plan(plan, backend=backend)

        self.assertEqual(backend.merged, [("B7WKDLMX", ["AMV7KCYM", "N8Y8RF82"])])
        self.assertEqual(backend.trashed, [])


class PlanFileTests(unittest.TestCase):
    def test_a_plan_round_trips_through_a_file_a_person_can_edit(self):
        plan = scan_duplicates(backend=RecordingBackend(library()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "plan.json"
            save_plan(plan, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["groups"][0]["masterKey"], "B7WKDLMX")

            restored = load_plan(path)
            self.assertEqual(len(restored.groups), 2)

    def test_an_edited_action_is_honoured(self):
        backend = RecordingBackend(library())
        plan = scan_duplicates(backend=backend)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            save_plan(plan, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            for group in payload["groups"]:
                if group["rule"] == "title-year":
                    group["action"] = TRASH
            path.write_text(json.dumps(payload), encoding="utf-8")

            apply_duplicates_plan(load_plan(path), backend=backend)

        self.assertEqual(backend.trashed, ["E1", "E2"])

    def test_replaying_an_applied_plan_is_refused(self):
        backend = RecordingBackend(library())
        plan = scan_duplicates(backend=backend)
        apply_duplicates_plan(plan, backend=backend)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            save_plan(plan, path)
            with self.assertRaisesRegex(ValueError, "already applied"):
                load_plan(path)

    def test_a_plan_edited_into_an_unsafe_state_is_refused_on_load(self):
        plan = scan_duplicates(backend=RecordingBackend(library()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            save_plan(plan, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["groups"][0]["masterKey"] = "NOTINGROUP"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not one of the items"):
                load_plan(path)


class CommandTests(unittest.TestCase):
    def _args(self, **overrides):
        base = dict(plan_out=None, from_plan=None, apply=False, json=False)
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_dry_run_writes_nothing_and_says_so(self):
        backend = RecordingBackend(library())
        buffer = io.StringIO()
        with patch("zotero_connector_cli.cli.ping"), patch(
            "zotero_connector_cli.merge_duplicates.DesktopBridgeBackend",
            return_value=backend,
        ), redirect_stdout(buffer):
            exit_code = command_merge_duplicates(self._args())

        output = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(backend.merged, [])
        self.assertIn("Nothing was written", output)
        self.assertIn("Dry run", output)

    def test_apply_merges_and_reports_the_review_backlog(self):
        backend = RecordingBackend(library())
        buffer = io.StringIO()
        with patch("zotero_connector_cli.cli.ping"), patch(
            "zotero_connector_cli.merge_duplicates.DesktopBridgeBackend",
            return_value=backend,
        ), redirect_stdout(buffer):
            command_merge_duplicates(self._args(apply=True))

        output = buffer.getvalue()
        self.assertEqual(backend.merged, [("B7WKDLMX", ["AMV7KCYM", "N8Y8RF82"])])
        self.assertIn("Merged", output)
        self.assertIn("matched only on title", output)

    def test_json_mode_emits_the_summary_and_nothing_else(self):
        backend = RecordingBackend(library())
        buffer = io.StringIO()
        with patch("zotero_connector_cli.cli.ping"), patch(
            "zotero_connector_cli.merge_duplicates.DesktopBridgeBackend",
            return_value=backend,
        ), redirect_stdout(buffer):
            command_merge_duplicates(self._args(json=True))

        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["counts"]["merge"], 1)
        self.assertEqual(payload["librarySize"], 5)

    def test_plan_out_writes_a_file_without_touching_the_library(self):
        backend = RecordingBackend(library())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            buffer = io.StringIO()
            with patch("zotero_connector_cli.cli.ping"), patch(
                "zotero_connector_cli.merge_duplicates.DesktopBridgeBackend",
                return_value=backend,
            ), redirect_stdout(buffer):
                command_merge_duplicates(self._args(plan_out=str(path)))

            self.assertTrue(path.is_file())
        self.assertEqual(backend.merged, [])


if __name__ == "__main__":
    unittest.main()
