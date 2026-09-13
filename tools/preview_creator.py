"""Render isolated Creator UI previews without opening the installed apps."""
from pathlib import Path
import os
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from core.paths import DATA_DIR_OVERRIDE_ENV
from core.odrlib import new_artifact, new_collection, new_item
from gui.creator_window import CreatorWindow, NewFileDialog
from gui.creator_publish import PublishResultDialog
from gui.creator_splash import CreatorSplashScreen


def main():
    output = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd() / "creator-ui-preview"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="oder-creator-preview-") as directory, \
         patch.dict(os.environ, {DATA_DIR_OVERRIDE_ENV: directory}):
        app = QApplication.instance() or QApplication([])
        # Windows' offscreen backend doesn't enumerate system fonts by itself.
        if sys.platform == "win32":
            fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
                if (fonts / name).exists():
                    QFontDatabase.addApplicationFont(str(fonts / name))
            app.setFont(QFont("Segoe UI", 10))

        def capture(widget, filename):
            widget.show()
            for _ in range(3):
                app.processEvents()
            if not widget.grab().save(str(output / filename)):
                raise RuntimeError(f"Unable to save {filename}")

        window = CreatorWindow()
        capture(window, "creator-home.png")
        window.new_document()
        window.library_name.setText("Field Notes")
        window.library_summary.setText("A small collection of guides, tools and reusable artwork.")
        window.library_description.setPlainText("Everything you need to start exploring. Curated, organized and ready to share.")
        window.library_creator.setText("ODeR community")
        window.library_category.setText("Resources")
        window._commit_editor()
        folder = new_collection(name="Documentation")
        window.project["collections"].append(folder)
        for name in ("Getting started.pdf", "Artwork pack.zip", "Readme.txt"):
            item = new_item(title=name)
            item["artifacts"] = [new_artifact(name=name, url="https://example.org/files/" + name.replace(" ", "%20"))]
            window.project["items"].append(item)
            if name.endswith(".pdf"):
                folder["item_ids"].append(item["id"])
        window._rebuild_tree(("library", None))
        capture(window, "creator-workspace.png")
        window.resize(1050, 680)
        capture(window, "creator-workspace-small.png")
        with patch("gui.creator_window.load_settings", return_value={"theme": "light"}):
            window._apply_theme()
        capture(window, "creator-workspace-light.png")
        window._apply_theme()
        window.resize(1380, 850)
        dialog = NewFileDialog(parent=window)
        capture(dialog, "creator-add-file.png")
        dialog.close()
        result = SimpleNamespace(
            path=str(output / "Field Notes.odrlib"), size=246_580, sha256="a" * 64,
            package=SimpleNamespace(name="Field Notes", item_count=3, collection_count=1),
            feed_path=None, torrent_path=None, update_torrent_path=None,
        )
        completed = PublishResultDialog(result, window)
        capture(completed, "creator-complete.png")
        completed.close()
        splash = CreatorSplashScreen()
        splash.set_status("Loading your workspace…")
        capture(splash, "creator-splash.png")
        splash.close()
        with patch.object(window, "_confirm_discard", return_value=True):
            window.close()
    print(output)


if __name__ == "__main__":
    main()
