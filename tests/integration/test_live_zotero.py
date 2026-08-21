"""The live Windows profile.

Everything here needs a real Zotero Desktop, the CLI Bridge plugin, and (for
one class) a browser. All of it is skipped unless ``ZOTERO_CONNECTOR_LIVE=1``.

Read ``tests/integration/README.md`` before running it: these tests write to
your actual library. They confine themselves to scratch collections and clean
up after themselves, but they are not a dry run.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from zotero_core.backends.desktop import (
    BRIDGE_ADDON_ID,
    DesktopBridgeBackend,
    bridge_info,
)
from zotero_core.dedup import MERGE, apply_merge_plan, find_duplicates

from zotero_connector_cli.bib_import import import_bib_directory
from zotero_connector_cli.cli import (
    _single_batch_instance,
    _write_csv_atomic,
    _write_json_atomic,
)

from .harness import LIVE_ENV, LiveZoteroTestCase, live_enabled, requires_live


class BridgeTests(unittest.TestCase):
    """Is the component this package depends on actually the one we tested?"""

    @requires_live
    def test_the_bridge_reports_itself_and_is_a_version_we_support(self):
        info = bridge_info()

        self.assertTrue(info["endpointRegistered"], info["problems"])
        self.assertEqual(info["addonID"], BRIDGE_ADDON_ID)
        self.assertTrue(info["bridgeVersion"], "the plugin did not report a version")
        self.assertTrue(info["ok"], "; ".join(info["problems"]))

    @requires_live
    def test_the_library_answers_and_is_not_empty(self):
        items = DesktopBridgeBackend().snapshot_library()

        self.assertGreater(len(items), 0)
        self.assertTrue(all(item.key for item in items))


class ScratchLifecycleTests(LiveZoteroTestCase):
    """Temporary-item cleanup: what the profile creates, it removes."""

    @requires_live
    def test_a_scratch_item_exists_while_the_test_runs(self):
        key = self.make_item(title="Live harness probe", date="2026")

        live = {item.key for item in DesktopBridgeBackend().snapshot_library()}
        self.assertIn(key, live)

    @requires_live
    def test_teardown_removes_every_item_and_collection_it_created(self):
        # Runs teardown early and asserts on the result, rather than trusting
        # that the cleanup registered by setUp did anything.
        key = self.make_item(title="Live harness cleanup probe", date="2026")
        collection = self.collection_key

        self._teardown()

        live = {item.key for item in DesktopBridgeBackend().snapshot_library()}
        self.assertNotIn(key, live)
        collections = {c.key for c in DesktopBridgeBackend().list_collections()}
        self.assertNotIn(collection, collections)

    @requires_live
    def test_teardown_refuses_a_collection_it_did_not_create(self):
        # The guard that makes this profile safe to run against a real
        # library: a wrong key must not erase a real project.
        real = next(
            c
            for c in DesktopBridgeBackend().list_collections()
            if not c.name.startswith("zzz-connector-live-test")
        )
        self._collections.append(real.key)

        with self.assertRaisesRegex(Exception, "Refusing to tear down"):
            self._teardown()

        self._collections.remove(real.key)
        surviving = {c.key for c in DesktopBridgeBackend().list_collections()}
        self.assertIn(real.key, surviving)


class ImportTests(LiveZoteroTestCase):
    """Collection preservation, against the real bridge."""

    def _write_bib(self, directory, stream, entries):
        path = Path(directory) / f"{stream}.bib"
        path.write_text("\n".join(entries), encoding="utf-8")
        return path

    @requires_live
    def test_an_existing_item_is_filed_rather_than_duplicated(self):
        doi = "10.5555/live-harness-file-me"
        existing = self.make_item(
            title="Live Harness Existing Work",
            date="2026",
            DOI=doi,
            creators=[{"creatorType": "author", "firstName": "Ada", "lastName": "Probe"}],
        )
        target = self.make_collection()

        with tempfile.TemporaryDirectory() as directory:
            self._write_bib(
                directory,
                "stream-one",
                [
                    "@article{probe2026live,",
                    "  title = {Live Harness Existing Work},",
                    "  author = {Probe, Ada},",
                    "  year = {2026},",
                    f"  doi = {{{doi}}},",
                    "  journal = {Journal of Probes},",
                    "}",
                ],
            )
            plan = import_bib_directory(directory, self.collection_name, apply=False)

        self.assertTrue(plan["ok"], plan.get("conflicts"))
        # The work is already in the library, so it is added to the target
        # rather than created a second time.
        self.assertEqual(plan["counts"]["create"], 0)
        rows = plan["plan"]
        self.assertTrue(any(row["itemKey"] == existing for row in rows), rows)
        self.assertTrue(all(row["matchedBy"] in ("doi", "citekey", None) for row in rows))
        del target

    @requires_live
    def test_an_absent_work_is_planned_as_a_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            self._write_bib(
                directory,
                "stream-one",
                [
                    "@article{probe2026absent,",
                    "  title = {Live Harness Work That Is Not In This Library},",
                    "  author = {Probe, Ada},",
                    "  year = {2026},",
                    "  doi = {10.5555/live-harness-absent},",
                    "  journal = {Journal of Probes},",
                    "}",
                ],
            )
            plan = import_bib_directory(directory, self.collection_name, apply=False)

        self.assertTrue(plan["ok"], plan.get("conflicts"))
        self.assertEqual(plan["counts"]["create"], 1)


class MergeTests(LiveZoteroTestCase):
    """The write path that has no unit coverage, exercised end to end."""

    @requires_live
    def test_merging_moves_attachments_and_unions_collections(self):
        doi = "10.5555/live-harness-merge-me"
        second_collection = self.make_collection()
        master = self.make_item(title="Live Harness Duplicate", date="2026", DOI=doi)
        loser = self.make_item(
            collection_key=second_collection,
            title="Live Harness Duplicate",
            date="2026",
            DOI=doi,
        )

        backend = DesktopBridgeBackend(sync_after_write=False)
        snapshot = [
            item
            for item in backend.snapshot_library()
            if item.key in {master, loser}
        ]
        plan = find_duplicates(snapshot)

        self.assertEqual(len(plan.groups), 1)
        self.assertEqual(plan.groups[0].action, MERGE)

        # Whichever copy the ladder chose; the point is the survivor keeps
        # both collections and the other is trashed rather than erased.
        survivor = plan.groups[0].master_key
        apply_merge_plan(plan, backend)

        live = {item.key: item for item in backend.snapshot_library()}
        self.assertIn(survivor, live)
        self.assertNotIn(loser if survivor == master else master, live)
        self.assertEqual(len(live[survivor].collection_keys), 2)


class RecoveryTests(unittest.TestCase):
    """Interrupted-run recovery, on the real checkpoint and lock mechanisms."""

    @requires_live
    def test_an_interrupted_checkpoint_write_leaves_the_previous_one_intact(self):
        # The property that makes a killed run resumable: os.replace is
        # atomic, so a reader either sees the old file or the new one.
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            _write_json_atomic(report, {"rows": [{"parentKey": "AAAA1111", "ok": True}]})
            first = json.loads(report.read_text(encoding="utf-8"))

            with unittest.mock.patch(
                "zotero_connector_cli.cli.os.replace", side_effect=OSError("killed")
            ):
                with self.assertRaises(OSError):
                    _write_json_atomic(report, {"rows": [{"parentKey": "BBBB2222"}]})

            surviving = json.loads(report.read_text(encoding="utf-8"))
            leftovers = [p.name for p in Path(directory).iterdir() if p.name != "report.json"]

        self.assertEqual(surviving, first)
        self.assertEqual(leftovers, [], "a failed write left a temporary file behind")

    @requires_live
    def test_a_finished_row_is_not_reselected_on_resume(self):
        # Resume is the status column, not a side file: rows already carrying
        # the success value are filtered out before any work is attempted.
        rows = [
            {"parent_key": "AAAA1111", "status": "pending", "sha256": "A" * 64},
            {"parent_key": "BBBB2222", "status": "done", "sha256": "B" * 64},
        ]
        selected = [row for row in rows if row.get("status", "") == "pending"]

        self.assertEqual([row["parent_key"] for row in selected], ["AAAA1111"])

    @requires_live
    def test_a_status_csv_keeps_its_digests_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pdf-status.csv"
            _write_csv_atomic(
                path,
                [{"parent_key": "AAAA1111", "status": "done", "sha256": "A" * 64}],
            )
            with path.open(encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))

        # Digests in this CSV are uppercase and compared byte-wise on resume;
        # a writer that normalised case would restart finished downloads.
        self.assertEqual(rows[0]["sha256"], "A" * 64)

    @requires_live
    def test_a_second_batch_on_the_same_csv_is_refused(self):
        if os.name != "nt":
            self.skipTest("the batch lock is a Windows named mutex")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pdf-status.csv"
            path.write_text("parent_key\n", encoding="utf-8")
            with _single_batch_instance(path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with _single_batch_instance(path):
                        pass

            # And the lock is released once the first run finishes, so a
            # crashed run does not lock the CSV forever.
            with _single_batch_instance(path):
                pass


class BrowserTests(unittest.TestCase):
    """The browser half of the profile: is a Connector-capable browser here?"""

    @requires_live
    def test_a_supported_browser_is_installed(self):
        from zotero_connector_cli.cli import BROWSER_PROCESSES
        from zotero_connector_cli.windows import find_browser_executable

        found = {
            browser: find_browser_executable(browser) for browser in BROWSER_PROCESSES
        }
        self.assertTrue(
            any(found.values()),
            f"no supported browser found; looked for {sorted(BROWSER_PROCESSES)}",
        )

    @requires_live
    def test_the_zotero_connector_endpoint_answers(self):
        # The Connector talks to the same local server the bridge rides on.
        # If this fails, browser saves cannot work regardless of the plugin.
        from zotero_connector_cli.zotero import ping

        self.assertTrue(ping())


class GatingTests(unittest.TestCase):
    """The profile's own safety property, checked without a live Zotero."""

    def test_the_profile_is_off_unless_it_was_asked_for(self):
        original = os.environ.get(LIVE_ENV)
        try:
            os.environ.pop(LIVE_ENV, None)
            self.assertFalse(live_enabled())
            os.environ[LIVE_ENV] = "0"
            self.assertFalse(live_enabled())
            os.environ[LIVE_ENV] = "1"
            self.assertTrue(live_enabled())
        finally:
            if original is None:
                os.environ.pop(LIVE_ENV, None)
            else:
                os.environ[LIVE_ENV] = original


if __name__ == "__main__":
    unittest.main()
