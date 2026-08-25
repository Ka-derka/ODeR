import hashlib
import json
import os
import tempfile
import unittest
import uuid
from unittest.mock import patch

from core.odrlib import (
    OdrLibError, build_library, new_artifact, new_collection, new_item, new_project,
)
from core.odrlib_store import (
    check_for_update, download_update, extract_embedded, find_conflicts,
    import_library, inspect_for_import, load_profile_package, save_library_copy,
)
from core.version import APP_VERSION


class _Response:
    def __init__(self, data):
        self.data = data
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.data), max(1, chunk_size)):
            yield self.data[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, responses):
        self.responses = responses
        self.returned = []

    def get(self, url, **_kwargs):
        response = _Response(self.responses[url])
        self.returned.append(response)
        return response


class OdrLibStoreTests(unittest.TestCase):
    def _package(self, root, revision=1, library_id=None):
        payload = os.path.join(root, f"payload-{revision}.bin")
        with open(payload, "wb") as handle:
            handle.write(f"offline payload revision {revision}".encode("ascii"))
        project = new_project()
        if library_id:
            project["library"]["id"] = library_id
        project["library"].update({
            "name": "Curated Utilities",
            "creator": "Test Curator",
            "version": f"Release {revision}",
            "revision": revision,
            "update": {
                "feed_url": "https://example.org/curated-library.feed.json",
                "channel": "stable",
            },
        })
        item = new_item(title="Utility")
        item["artifacts"].append(new_artifact(
            name="Utility", embedded_path=payload, url="https://example.org/utility.bin"
        ))
        project["items"].append(item)
        folder = new_collection(name="Tools")
        folder["item_ids"].append(item["id"])
        project["collections"].append(folder)
        return build_library(project, os.path.join(root, f"library-{revision}.odrlib")).path

    def test_import_browse_extract_and_save_copy(self):
        with tempfile.TemporaryDirectory() as root:
            package = self._package(root)
            app_data = os.path.join(root, "app-data")
            with patch("core.paths.data_dir", return_value=app_data):
                preview = inspect_for_import(package)
                self.assertEqual(preview.package.item_count, 1)
                self.assertEqual(preview.conflicts, ())
                result = import_library(package)
                self.assertEqual(result.profile["kind"], "odrlib")
                self.assertTrue(os.path.isfile(result.profile["odrlib"]["package_path"]))
                self.assertEqual(len(find_conflicts(result.package)), 1)
                installed = load_profile_package(result.profile)
                source = installed.items[0]["artifacts"][0]["sources"][0]
                destination = os.path.join(root, "downloads", "utility.bin")
                extracted = extract_embedded(result.profile, source, destination)
                self.assertTrue(os.path.isfile(extracted["path"]))
                with open(destination, "rb") as handle:
                    self.assertEqual(handle.read(), b"offline payload revision 1")
                copied = save_library_copy(result.profile, os.path.join(root, "shared"))
                self.assertTrue(copied.endswith(".odrlib"))
                self.assertTrue(os.path.isfile(copied))

    def test_duplicate_requires_policy_and_older_revision_cannot_replace(self):
        with tempfile.TemporaryDirectory() as root:
            library_id = str(uuid.uuid4())
            newer = self._package(root, revision=2, library_id=library_id)
            older = self._package(root, revision=1, library_id=library_id)
            app_data = os.path.join(root, "app-data")
            with patch("core.paths.data_dir", return_value=app_data):
                installed = import_library(newer)
                with self.assertRaisesRegex(OdrLibError, "older library revision"):
                    import_library(
                        older,
                        conflict_policy="replace",
                        replace_profile_id=installed.profile["id"],
                    )

    def test_verified_update_feed_download_replaces_the_installed_revision(self):
        with tempfile.TemporaryDirectory() as root:
            library_id = str(uuid.uuid4())
            original = self._package(root, revision=1, library_id=library_id)
            update = self._package(root, revision=2, library_id=library_id)
            with open(update, "rb") as handle:
                update_data = handle.read()
            feed = {
                "format": "oder-library-update-feed",
                "format_version": 1,
                "library_id": library_id,
                "channel": "stable",
                "latest": {
                    "revision": 2,
                    "version": "Release 2",
                    "published_at": "2026-08-20T12:00:00Z",
                    "url": "https://example.org/curated-library.odrlib",
                    "size": len(update_data),
                    "sha256": hashlib.sha256(update_data).hexdigest(),
                    "minimum_reader": APP_VERSION,
                    "release_notes": "Updated payload.",
                },
            }
            feed_data = json.dumps(feed).encode("utf-8")
            session = _Session({
                "https://example.org/curated-library.feed.json": feed_data,
                "https://example.org/curated-library.odrlib": update_data,
            })
            app_data = os.path.join(root, "app-data")
            with patch("core.paths.data_dir", return_value=app_data):
                installed = import_library(original)
                available = check_for_update(installed.profile, session=session)
                self.assertEqual(available.revision, 2)
                result = download_update(installed.profile, available, session=session)
                self.assertTrue(result.replaced)
                self.assertEqual(result.package.revision, 2)
                self.assertEqual(result.profile["odrlib"]["revision"], 2)
                self.assertTrue(all(response.closed for response in session.returned))


if __name__ == "__main__":
    unittest.main()
