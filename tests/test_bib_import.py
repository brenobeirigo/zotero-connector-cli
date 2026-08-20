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

    def test_loads_webpage_and_generic_thesis_types(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Company evidence.bib").write_text(
                """@online{company2026,
  title={Operations profile}, organization={Example Company}, year={2026},
  url={https://example.com/operations}, urldate={2026-08-16}}
@online{companyUndated,
  title={Locations}, organization={Example Company},
  url={https://example.com/locations}, urldate={2026-08-16}}
@thesis{student2025,
  author={Student, Sam}, title={Warehouse study}, school={University of Twente},
  type={Bachelor's thesis}, year={2025}, url={https://essay.utwente.nl/example}}
@bachelorthesis{student2024,
  author={Student, Alex}, title={Production study}, school={University of Twente},
  year={2024}, url={https://essay.utwente.nl/example-2}}
@report{company2025,
  title={Annual report}, institution={Example Company}, year={2025},
  url={https://example.com/report}}
""",
                encoding="utf-8",
            )
            entries = load_bib_directory(directory)
        by_key = {entry["citationKey"]: entry for entry in entries}
        self.assertEqual(by_key["company2026"]["itemType"], "webpage")
        self.assertEqual(
            by_key["company2026"]["fields"]["websiteTitle"], "Example Company"
        )
        self.assertEqual(
            by_key["company2026"]["fields"]["accessDate"], "2026-08-16"
        )
        self.assertEqual(by_key["companyUndated"]["itemType"], "webpage")
        self.assertNotIn("date", by_key["companyUndated"]["fields"])
        self.assertEqual(by_key["student2025"]["itemType"], "thesis")
        self.assertEqual(
            by_key["student2025"]["fields"]["thesisType"], "Bachelor's thesis"
        )
        self.assertEqual(
            by_key["student2024"]["fields"]["thesisType"], "Bachelor's thesis"
        )
        self.assertEqual(by_key["company2025"]["itemType"], "report")

    def test_distinguishes_generic_titles_by_corporate_creator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "Reports.bib").write_text(
                """@report{asml2025,
  author={{ASML Holding N.V.}}, title={Annual Report 2025},
  institution={ASML Holding N.V.}, year={2026}}
@report{vdl2025,
  author={{VDL Groep}}, title={Annual Report 2025},
  institution={VDL Groep}, year={2026}}
""",
                encoding="utf-8",
            )
            entries = load_bib_directory(directory)
        by_key = {entry["citationKey"]: entry for entry in entries}
        self.assertEqual(len(entries), 2)
        self.assertEqual(by_key["asml2025"]["matchCreator"], "ASML Holding N.V.")
        self.assertEqual(by_key["vdl2025"]["matchCreator"], "VDL Groep")
        self.assertEqual(by_key["vdl2025"]["creators"][0]["fieldMode"], 1)

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
