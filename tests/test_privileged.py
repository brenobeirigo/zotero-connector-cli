import unittest
from unittest.mock import patch

from zotero_connector_cli.privileged import (
    adopt_connector_pdf,
    attach_pdf_file,
    find_available_pdf,
)


class PrivilegedAttachmentTests(unittest.TestCase):
    @patch("zotero_connector_cli.privileged.evaluate", return_value={"ok": True})
    def test_find_pdf_requires_a_physical_existing_file(self, evaluate) -> None:
        find_available_pdf("ABCD1234")

        script = evaluate.call_args.args[0]
        self.assertIn("await attachment.fileExists()", script)

    @patch("zotero_connector_cli.privileged.evaluate", return_value={"ok": True})
    def test_attach_file_links_files_inside_configured_base(self, evaluate) -> None:
        attach_pdf_file("ABCD1234", r"C:\Library\paper.pdf")

        script = evaluate.call_args.args[0]
        self.assertIn("Zotero.Attachments.linkFromFile", script)
        self.assertIn("Zotero.Attachments.importFromFile", script)
        self.assertIn('attachmentMode = "linked-file"', script)
        self.assertIn('attachmentMode = "relinked-broken-file"', script)
        self.assertIn("relinkAttachmentFile", script)
        self.assertIn("Refusing to import into Zotero storage", script)
        self.assertIn('normalizedBase.includes("\\\\")', script)
        self.assertIn("brokenAttachments", script)

    @patch("zotero_connector_cli.privileged.evaluate", return_value={"ok": True})
    def test_connector_adoption_counts_only_existing_final_pdfs(self, evaluate) -> None:
        adopt_connector_pdf("ABCD1234", ["TEMP1234"])

        script = evaluate.call_args.args[0]
        final_validation = script[script.index("const finalPDFs = [];") :]
        self.assertIn("await current.fileExists()", final_validation)
        self.assertIn("IOUtils.copy(sourcePath, destinationPath)", script)
        self.assertIn("Zotero.Attachments.linkFromFile", script)
        self.assertIn("Externalized PDF size mismatch", script)
        self.assertIn("temporaryNonPDFFiles", script)
        self.assertIn("Refusing to erase an annotated temporary non-PDF attachment", script)
        self.assertIn("await temporary.item.eraseTx()", script)
        self.assertIn("await adoptedAttachment.eraseTx()", script)
        self.assertIn("discardedTemporaryFiles", script)

    @patch("zotero_connector_cli.privileged.evaluate", return_value={"ok": True})
    def test_a_saved_landing_page_is_trashed_however_many_candidates_there_were(
        self, evaluate
    ) -> None:
        # Six webpage items titled "EBSCO" survived a real run because the
        # cleanup only ever considered a single candidate. The sweep must not
        # be conditioned on that count again.
        adopt_connector_pdf("ABCD1234", ["TEMP1234", "TEMP5678"])

        script = evaluate.call_args.args[0]
        sweep = script[script.index("const landingPagesTrashed = [];") :]
        self.assertIn("for (const candidate of regularCandidates)", sweep)
        self.assertIn('route: "provider-landing-page"', sweep)
        # A candidate carrying a real PDF is never swept as litter...
        self.assertIn("child.isPDFAttachment() && !child.deleted", sweep)
        # ...and neither is annotated work.
        self.assertIn("child.getAnnotations().length", sweep)
        # The mismatch branch now reasons about what survived the sweep, so
        # the old single-candidate condition must be gone, not merely joined.
        self.assertIn("unmatchedWithPDFs.length === 1", script)
        self.assertNotIn("regularCandidates.length === 1", script)

    @patch("zotero_connector_cli.privileged.evaluate", return_value={"ok": True})
    def test_swept_litter_is_reported_on_outcomes_it_did_not_cause(self, evaluate) -> None:
        # Litter cleaned during an otherwise successful save still has to be
        # visible, or the run reports success and never mentions it.
        adopt_connector_pdf("ABCD1234", ["TEMP1234"])

        script = evaluate.call_args.args[0]
        self.assertEqual(script.count("landingPagesTrashed,"), 3)


if __name__ == "__main__":
    unittest.main()
