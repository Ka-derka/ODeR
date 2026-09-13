import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.creator_publish import PublishResultDialog, sharing_instructions


def build_result(**changes):
    result = dict(
        path=os.path.abspath("output/My Library.odrlib"),
        size=2048,
        sha256="a" * 64,
        package=SimpleNamespace(
            library={},
            name="My Library", item_count=12, collection_count=3,
            update_feed_url="https://example.org/library-feed.json",
        ),
        feed_path=None, torrent_path=None, update_torrent_path=None,
    )
    result.update(changes)
    return SimpleNamespace(**result)


class CreatorPublishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_torrent_sharing_separates_source_data_and_package_seeding(self):
        result = build_result(
            feed_path="output/My Library.odrlib-feed.json",
            torrent_path="output/My Library.torrent",
            update_torrent_path="output/My Library.odrlib.torrent",
        )
        source = os.path.abspath("original/Library files")
        instructions = sharing_instructions(result, source_folder=source)
        self.assertIn(f"Original source folder: {source}", instructions)
        self.assertIn(f"use its parent: {os.path.dirname(source)}", instructions)
        self.assertIn(f"output folder as its save location: {os.path.dirname(result.path)}", instructions)
        self.assertIn("My Library.odrlib.torrent", instructions)
        self.assertLess(instructions.index("Upload My Library.odrlib.torrent"),
                        instructions.index("Publish My Library.odrlib-feed.json"))
        self.assertIn("https://example.org/library-feed.json LAST", instructions)

    def test_simple_package_does_not_instruct_user_to_publish_or_seed_missing_outputs(self):
        instructions = sharing_instructions(build_result())
        self.assertIn("Share My Library.odrlib", instructions)
        self.assertNotIn("Upload", instructions)
        self.assertNotIn("torrent", instructions)

    def test_package_update_without_payload_does_not_promise_a_payload_torrent(self):
        instructions = sharing_instructions(build_result(
            feed_path="output/My Library.odrlib-feed.json",
            update_torrent_path="output/My Library.odrlib.torrent",
        ))
        self.assertIn("This torrent shares the library package.", instructions)
        self.assertNotIn("file-sharing torrent", instructions)

    def test_details_are_optional_and_failed_open_explains_manual_import(self):
        result = build_result()
        dialog = PublishResultDialog(result)
        try:
            self.assertTrue(dialog.technical_details.isHidden())
            dialog.details_toggle.setChecked(True)
            self.assertFalse(dialog.technical_details.isHidden())
            self.assertIn(result.sha256, dialog.technical_details.text())
            with patch("gui.creator_publish.QDesktopServices.openUrl", return_value=False) as opener:
                with patch("gui.creator_publish.QMessageBox.information") as message:
                    dialog._test_in_oder()
            self.assertEqual(opener.call_args.args[0].toLocalFile(), result.path.replace("\\", "/"))
            self.assertIn("drag the .odrlib", message.call_args.args[2])
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
