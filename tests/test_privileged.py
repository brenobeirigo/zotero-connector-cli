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


if __name__ == "__main__":
    unittest.main()
