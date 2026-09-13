import json
import os
import tempfile
import unittest
import zipfile

from core.odrlib import (
    MANIFEST_NAME, UPDATE_EXTENSION_ID, OdrLibError, build_library, import_folder,
    import_folder_selection, inspect_library, scan_folder,
    inspect_update_feed,
    load_project, new_artifact, new_collection, new_item, new_project,
    save_project, validate_project,
)
from core.version import APP_VERSION, CREATOR_VERSION
from core.torrent_support import create_metainfo, inspect_metainfo


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05"
    b"\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class OdrLibTests(unittest.TestCase):
    def _rewrite_manifest(self, source, destination, change):
        with zipfile.ZipFile(source, "r") as incoming, zipfile.ZipFile(destination, "w") as outgoing:
            for info in incoming.infolist():
                data = incoming.read(info)
                if info.filename == MANIFEST_NAME:
                    manifest = json.loads(data.decode("utf-8"))
                    change(manifest)
                    data = json.dumps(manifest).encode("utf-8")
                outgoing.writestr(info.filename, data, compress_type=info.compress_type)

    def _project(self, root):
        payload = os.path.join(root, "tool.zip")
        artwork = os.path.join(root, "cover.png")
        with open(payload, "wb") as handle:
            handle.write(b"portable software payload")
        with open(artwork, "wb") as handle:
            handle.write(PNG_1X1)
        project = new_project()
        project["library"].update({
            "name": "Archivist Toolkit",
            "summary": "A curated set of useful tools.",
            "creator": "Test Curator",
            "category": "Software",
            "tags": ["shareware", "preservation"],
            "version": "2026.1",
            "revision": 7,
            "artwork_path": artwork,
            "update": {
                "feed_url": "https://example.org/archivist.odrlib-feed.json",
                "channel": "stable",
            },
        })
        project["publishing"].update({
            "package_url": "https://example.org/archivist.odrlib",
            "release_notes": "First public catalog.",
        })
        item = new_item(title="Tool One")
        item.update({"creator": "Example Publisher", "category": "Utilities", "version": "2.0"})
        item["artifacts"].append(new_artifact(
            name="Windows portable", embedded_path=payload,
            url="https://example.org/tool.zip",
        ))
        project["items"].append(item)
        collection = new_collection(name="Essentials")
        collection["item_ids"].append(item["id"])
        project["collections"].append(collection)
        return project

    def test_project_round_trip_relativizes_local_sources(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            path = os.path.join(root, "library.odrproj")
            stored = save_project(path, project)
            self.assertEqual(stored["library"]["artwork_path"], "cover.png")
            embedded = stored["items"][0]["artifacts"][0]["sources"][0]
            self.assertEqual(embedded["source_path"], "tool.zip")
            loaded = load_project(path)
            self.assertEqual(loaded["library"]["id"], project["library"]["id"])
            self.assertEqual(loaded["items"][0]["title"], "Tool One")
            self.assertFalse(any(issue.level == "error" for issue in validate_project(loaded, path)))

    def test_build_and_inspect_full_library_and_update_feed(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            project_path = os.path.join(root, "library.odrproj")
            project = save_project(project_path, project)
            output = os.path.join(root, "Archivist Toolkit.odrlib")
            result = build_library(project, output, project_path=project_path)
            self.assertEqual(result.package.name, "Archivist Toolkit")
            self.assertEqual(result.package.revision, 7)
            self.assertEqual(result.package.item_count, 1)
            self.assertEqual(result.package.collection_count, 1)
            self.assertEqual(result.package.artifact_count, 1)
            self.assertGreater(result.package.embedded_bytes, 0)
            self.assertEqual(result.package.online_source_count, 1)
            self.assertEqual(result.package.created_by_version, CREATOR_VERSION)
            self.assertEqual([extension.badge for extension in result.package.extensions], ["U1"])
            self.assertEqual(
                result.package.manifest["extensions"]["optional"],
                [{"id": UPDATE_EXTENSION_ID, "version": 1}],
            )
            self.assertTrue(os.path.isfile(result.feed_path))
            with open(result.feed_path, "r", encoding="utf-8") as handle:
                feed = json.load(handle)
            self.assertEqual(feed["library_id"], project["library"]["id"])
            self.assertEqual(feed["latest"]["revision"], 7)
            self.assertEqual(feed["latest"]["sha256"], result.sha256)
            self.assertEqual(feed["latest"]["minimum_reader"], APP_VERSION)
            feed_info = inspect_update_feed(result.feed_path)
            self.assertEqual(feed_info.library_id, project["library"]["id"])
            self.assertEqual(feed_info.revision, 7)
            inspected = inspect_library(output)
            self.assertEqual(inspected.package_id, result.package.package_id)
            self.assertEqual(
                inspected.update_feed_url,
                "https://example.org/archivist.odrlib-feed.json",
            )
            with zipfile.ZipFile(output, "r") as archive:
                self.assertIn("assets/library-cover.png", archive.namelist())
                self.assertTrue(any(name.startswith("payload/") for name in archive.namelist()))

    def test_unknown_optional_extension_is_preserved_but_unknown_required_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            source = build_library(project, os.path.join(root, "source.odrlib")).path
            optional = os.path.join(root, "optional.odrlib")
            self._rewrite_manifest(
                source,
                optional,
                lambda manifest: manifest["extensions"]["optional"].append({"id": "X", "version": 7}),
            )
            inspected = inspect_library(optional)
            self.assertEqual([extension.badge for extension in inspected.extensions], ["U1", "X7"])

            required = os.path.join(root, "required.odrlib")
            self._rewrite_manifest(
                source,
                required,
                lambda manifest: manifest["extensions"]["required"].append({"id": "Z", "version": 1}),
            )
            with self.assertRaisesRegex(OdrLibError, "unsupported extension Z1"):
                inspect_library(required)

    def test_t1_folder_selection_builds_embedded_torrent_and_standalone_file(self):
        with tempfile.TemporaryDirectory() as root:
            nested = os.path.join(root, "Media")
            os.makedirs(nested)
            payload = os.path.join(nested, "episode.bin")
            with open(payload, "wb") as handle:
                handle.write(b"T1 payload" * 1000)
            records = scan_folder(root)
            self.assertEqual([record["relative_path"] for record in records], ["Media/episode.bin"])
            records[0]["bundle"] = False
            project, count = import_folder_selection(new_project(), root, records)
            project["library"].update({
                "name": "T1 Test", "creator": "Curator", "category": "Test",
            })
            result = build_library(project, os.path.join(root, "T1 Test.odrlib"))
            self.assertEqual(count, 1)
            self.assertTrue(os.path.isfile(result.torrent_path))
            self.assertEqual([extension.badge for extension in result.package.extensions], ["T1"])
            self.assertTrue(result.package.extensions[0].required)
            source = result.package.items[0]["artifacts"][0]["sources"][0]
            self.assertEqual(source["type"], "torrent")
            self.assertEqual(source["file_index"], 0)
            self.assertEqual(source["path"].replace("\\", "/"), f"{os.path.basename(root)}/Media/episode.bin")
            self.assertEqual(len(source["sha256"]), 64)
            self.assertEqual(source["metainfo_path"], "torrents/library.torrent")

    def test_t1_multi_file_padding_is_not_treated_as_a_catalog_file(self):
        with tempfile.TemporaryDirectory() as root:
            source_root = os.path.join(root, "The Sopranos")
            season = os.path.join(source_root, "Season 05")
            os.makedirs(season)
            for episode in range(3, 15):
                filename = f"The Sopranos (1999) - S05E{episode:02d} - Test [1080p].mkv"
                with open(os.path.join(season, filename), "wb") as handle:
                    handle.write(bytes([episode]) * (1000 + episode * 137))
            records = scan_folder(source_root)
            project, count = import_folder_selection(new_project(), source_root, records)
            project["library"].update({
                "name": "Multi-file T1", "creator": "Curator", "category": "Test",
            })

            result = build_library(project, os.path.join(root, "Multi-file T1.odrlib"))

            self.assertEqual(count, 12)
            sources = [
                artifact["sources"][0]
                for item in result.package.items for artifact in item["artifacts"]
            ]
            self.assertEqual(len(sources), 12)
            self.assertEqual(len({source["file_index"] for source in sources}), 12)
            self.assertTrue(all("/.pad/" not in source["path"] for source in sources))
            self.assertGreater(max(source["file_index"] for source in sources), 11)

    def test_t1_large_interleaved_folder_tree_has_consistent_hybrid_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            records = []
            for index in range(179):
                folder = os.path.join(root, f"folder{index % 27}")
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, f"file{index:03}.bin")
                with open(path, "wb") as handle:
                    handle.write(bytes([index % 251 + 1]) * (index % 17 + 1))
                records.append({
                    "source_path": path,
                    "relative_path": os.path.relpath(path, root).replace("\\", "/"),
                })

            metadata = inspect_metainfo(create_metainfo(root, records, piece_size=16 * 1024))

            self.assertEqual(len(metadata["files"]), 179)
            self.assertTrue(metadata["info_hash_v1"])
            self.assertTrue(metadata["info_hash_v2"])
            self.assertEqual(len({record["file_index"] for record in metadata["files"]}), 179)

    def test_future_optional_t_extension_uses_recognized_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            payload = os.path.join(root, "file.bin")
            with open(payload, "wb") as handle:
                handle.write(b"future torrent fallback")
            records = scan_folder(root)
            records[0]["bundle"] = True
            project, _count = import_folder_selection(new_project(), root, records)
            project["library"].update({"name": "Future T", "creator": "Test", "category": "Test"})
            source = build_library(project, os.path.join(root, "source.odrlib")).path
            future = os.path.join(root, "future.odrlib")
            self._rewrite_manifest(
                source,
                future,
                lambda manifest: manifest["extensions"]["optional"][0].update(version=99),
            )
            inspected = inspect_library(future)
            self.assertEqual([extension.badge for extension in inspected.extensions], ["T99"])
            self.assertEqual(
                [source["type"] for source in inspected.items[0]["artifacts"][0]["sources"]],
                ["embedded"],
            )

    def test_u1_requires_an_https_update_feed(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            project["library"]["update"]["feed_url"] = ""
            project["publishing"]["package_url"] = ""
            source = build_library(project, os.path.join(root, "source.odrlib")).path
            self.assertEqual(inspect_library(source).extensions, ())
            bad = os.path.join(root, "bad-u1.odrlib")
            self._rewrite_manifest(
                source,
                bad,
                lambda manifest: manifest["extensions"]["optional"].append({"id": "U", "version": 1}),
            )
            with self.assertRaisesRegex(OdrLibError, "U1 requires"):
                inspect_library(bad)

    def test_early_alpha2_update_capability_is_read_as_u1(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            source = build_library(project, os.path.join(root, "source.odrlib")).path
            legacy = os.path.join(root, "legacy.odrlib")
            self._rewrite_manifest(source, legacy, lambda manifest: manifest.pop("extensions"))
            inspected = inspect_library(legacy)
            self.assertEqual([extension.badge for extension in inspected.extensions], ["U1"])

    def test_future_optional_update_extension_does_not_enable_unknown_updater(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            source = build_library(project, os.path.join(root, "source.odrlib")).path
            future = os.path.join(root, "future-u.odrlib")
            self._rewrite_manifest(
                source,
                future,
                lambda manifest: manifest["extensions"]["optional"][0].update(version=2),
            )
            inspected = inspect_library(future)
            self.assertEqual([extension.badge for extension in inspected.extensions], ["U2"])
            self.assertIsNone(inspected.update_feed_url)

    def test_manifest_checksum_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            project = self._project(root)
            project_path = os.path.join(root, "library.odrproj")
            project = save_project(project_path, project)
            source = build_library(project, os.path.join(root, "good.odrlib"), project_path=project_path).path
            bad = os.path.join(root, "bad.odrlib")
            def corrupt_payload(manifest):
                payload = next(member for member in manifest["members"] if member["role"] == "payload")
                payload["sha256"] = "0" * 64
            self._rewrite_manifest(source, bad, corrupt_payload)
            with self.assertRaisesRegex(OdrLibError, "checksum|integrity|SHA-256"):
                inspect_library(bad)

    def test_invalid_online_source_is_reported_without_losing_project(self):
        project = new_project()
        item = new_item(title="Unsafe source")
        item["artifacts"].append(new_artifact(name="Download", url="http://example.org/file.exe"))
        project["items"].append(item)
        issues = validate_project(project)
        self.assertTrue(any(issue.level == "error" and "HTTPS" in issue.message for issue in issues))

    def test_bare_addresses_are_normalized_to_https(self):
        project = new_project()
        project["library"].update({
            "links": ["a.111477.xyz"],
            "license": {"name": "Info", "url": "example.org/license"},
            "update": {"feed_url": "example.org/library.feed.json", "channel": "stable"},
        })
        project["publishing"]["package_url"] = "example.org/library.odrlib"
        item = new_item(title="Episode 1")
        item["links"] = ["example.org/item"]
        item["license"] = {"name": "Info", "url": "example.org/item-license"}
        item["artifacts"].append(new_artifact(name="Episode 1", url="example.org/episode.mkv"))
        project["items"].append(item)
        with tempfile.TemporaryDirectory() as root:
            project_path = os.path.join(root, "bare-links.odrproj")
            normalized = save_project(project_path, project)
            self.assertEqual(normalized["library"]["links"], ["https://a.111477.xyz"])
            self.assertEqual(normalized["library"]["license"]["url"], "https://example.org/license")
            self.assertEqual(normalized["library"]["update"]["feed_url"], "https://example.org/library.feed.json")
            self.assertEqual(normalized["publishing"]["package_url"], "https://example.org/library.odrlib")
            self.assertEqual(normalized["items"][0]["links"], ["https://example.org/item"])
            self.assertEqual(normalized["items"][0]["license"]["url"], "https://example.org/item-license")
            self.assertEqual(normalized["items"][0]["artifacts"][0]["sources"][0]["url"], "https://example.org/episode.mkv")
            self.assertFalse(any(issue.level == "error" for issue in validate_project(normalized, project_path)))

    def test_folder_import_adds_items_and_parent_collections(self):
        with tempfile.TemporaryDirectory() as root:
            nested = os.path.join(root, "Utilities")
            os.makedirs(nested)
            with open(os.path.join(root, "readme.txt"), "wb") as handle:
                handle.write(b"hello")
            with open(os.path.join(nested, "program.exe"), "wb") as handle:
                handle.write(b"MZ-test")
            project, count = import_folder(new_project(), root)
            self.assertEqual(count, 2)
            self.assertEqual(len(project["items"]), 2)
            self.assertEqual(project["collections"][0]["name"], "Utilities")
            self.assertEqual(len(project["collections"][0]["item_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
