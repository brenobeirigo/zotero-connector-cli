from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zotero_connector_cli.bib_import import import_bib_directory, load_bib_directory


class BibImportTests(unittest.TestCase):
    def test_loads_stream_name_and_zotero_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "Search speed.bib")
            path.write_text(
                """@article{savelsbergh1992vrptw,
  author={Savelsbergh, Martin W. P.},
  title={The Vehicle Routing Problem with Time Windows: Minimizing Route Duration},
  journal={ORSA Journal on Computing}, year={1992}, volume={4}, number={2},
  pages={146--154}, doi={10.1287/ijoc.4.2.146}}
""",
                encoding="utf-8",
            )
            entries = load_bib_directory(directory)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["stream"], "Search speed")
        self.assertEqual(entries[0]["itemType"], "journalArticle")
        self.assertEqual(entries[0]["fields"]["pages"], "146-154")
        self.assertEqual(entries[0]["creators"][0]["lastName"], "Savelsbergh")

    @patch("zotero_connector_cli.bib_import.evaluate")
    def test_dry_run_uses_local_bridge_and_does_not_apply(self, evaluate) -> None:
        evaluate.return_value = {"ok": True, "applied": False, "parsed": 1}
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Methods.bib").write_text(
                "@article{x, author={Doe, Jane}, title={Example}, journal={J}, year={2020}}",
                encoding="utf-8",
            )
            result = import_bib_directory(directory, "Project", apply=False)
        self.assertTrue(result["ok"])
        script = evaluate.call_args.args[0]
        self.assertIn("const shouldApply = false", script)
        self.assertIn('const parentName = "Project"', script)


if __name__ == "__main__":
    unittest.main()
