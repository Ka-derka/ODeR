import os
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from core import cache, profiles, library
from core import oder_package


class OderPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.temp.name, "data")
        os.makedirs(self.data, exist_ok=True)

        def profile_dir(profile_id):
            value = os.path.join(self.data, "profiles", profile_id)
            os.makedirs(value, exist_ok=True)
            return value

        def profile_cache_path(profile_id):
            return os.path.join(profile_dir(profile_id), "cache.json")

        def profile_cache_db_path(profile_id):
            return os.path.join(profile_dir(profile_id), "cache.sqlite3")

        self.patchers = [
            patch.object(profiles, "profiles_index_path", lambda: os.path.join(self.data, "profiles.json")),
            patch.object(profiles, "profile_dir", profile_dir),
            patch.object(profiles, "profile_cache_path", profile_cache_path),
            patch.object(cache, "profile_cache_path", profile_cache_path),
            patch.object(cache, "profile_cache_db_path", profile_cache_db_path),
            patch.object(oder_package, "data_dir", lambda: self.data),
            patch.object(oder_package, "profile_dir", profile_dir),
            patch.object(oder_package, "profile_cache_db_path", profile_cache_db_path),
            patch.object(library, "package_history_path", lambda: os.path.join(self.data, "package_history.json")),
        ]
        for patcher in self.patchers:
            patcher.start()

        self.profile = profiles.create_profile("Example Archive", "https://example.test/files")
        cache.initialize(self.profile["id"], self.profile["base_url"])
        base = self.profile["base_url"]
        cache.upsert_nodes(self.profile["id"], [
            (base + "docs/", "docs", 1, None, base, 1),
            (base + "readme.txt", "readme.txt", 0, "42", base, 0),
        ])

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp.cleanup()

    def test_definition_export_and_copy_import(self):
        target = os.path.join(self.temp.name, "definition")
        exported = oder_package.export_directory(self.profile, target, include_cache=False)
        self.assertTrue(exported.path.endswith(".oder"))
        inspected = oder_package.inspect_package(exported.path)
        self.assertEqual(inspected.package_type, "definition")
        self.assertFalse(inspected.has_cache)
        with zipfile.ZipFile(exported.path) as archive:
            self.assertEqual(set(archive.namelist()), {"manifest.json", "profile.json"})

        imported = oder_package.import_directory(exported.path, conflict_policy="copy")
        self.assertNotEqual(imported.profile["id"], self.profile["id"])
        self.assertEqual(imported.profile["name"], "Example Archive (Imported)")
        self.assertFalse(imported.cache_imported)

    def test_full_export_validates_and_imports_cached_index(self):
        target = os.path.join(self.temp.name, "full.oder")
        exported = oder_package.export_directory(self.profile, target, include_cache=True)
        inspected = oder_package.inspect_package(exported.path)
        self.assertTrue(inspected.has_cache)
        self.assertEqual(inspected.cache_entries, 3)
        self.assertEqual(inspected.cache_folders, 2)
        self.assertEqual(inspected.cache_files, 1)

        imported = oder_package.import_directory(exported.path, conflict_policy="copy")
        self.assertTrue(imported.cache_imported)
        self.assertEqual(cache.count_nodes(imported.profile["id"]), 3)
        self.assertEqual(cache.get_base_url(imported.profile["id"]), self.profile["base_url"])

    def test_definition_replace_keeps_existing_cache(self):
        target = os.path.join(self.temp.name, "replace.oder")
        exported = oder_package.export_directory(self.profile, target, include_cache=False)
        result = oder_package.import_directory(
            exported.path,
            conflict_policy="replace",
            replace_profile_id=self.profile["id"],
        )
        self.assertTrue(result.replaced)
        self.assertFalse(result.cache_imported)
        self.assertEqual(cache.count_nodes(self.profile["id"]), 3)

    def test_tampered_profile_checksum_is_rejected(self):
        original = oder_package.export_directory(
            self.profile, os.path.join(self.temp.name, "original.oder"), include_cache=False
        ).path
        tampered = os.path.join(self.temp.name, "tampered.oder")
        with zipfile.ZipFile(original, "r") as source:
            manifest = source.read("manifest.json")
            profile = source.read("profile.json") + b" "
        with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.writestr("manifest.json", manifest)
            target.writestr("profile.json", profile)
        with self.assertRaises(oder_package.PackageError):
            oder_package.inspect_package(tampered)

    def test_subtree_export_is_a_browsable_standalone_package(self):
        folder = self.profile["base_url"] + "docs/"
        cache.replace_children(self.profile["id"], folder, [
            (folder + "guide.pdf", "guide.pdf", 0, "2 MB", folder, 0),
        ])
        exported = oder_package.export_directory(
            self.profile, os.path.join(self.temp.name, "docs.oder"), include_cache=True, root_url=folder,
        )
        inspected = oder_package.inspect_package(exported.path)
        self.assertEqual(inspected.scope, "subtree")
        self.assertEqual(inspected.base_url, folder)
        self.assertEqual(inspected.cache_entries, 2)

    def test_compare_packages_without_importing(self):
        older = oder_package.export_directory(
            self.profile, os.path.join(self.temp.name, "older.oder"), include_cache=True,
        ).path
        base = self.profile["base_url"]
        cache.replace_children(self.profile["id"], base, [
            (base + "docs/", "docs", 1, None, base, 1),
            (base + "readme.txt", "readme.txt", 0, "84", base, 0),
            (base + "new.zip", "new.zip", 0, "1 MB", base, 0),
        ])
        newer = oder_package.export_directory(
            self.profile, os.path.join(self.temp.name, "newer.oder"), include_cache=True,
        ).path
        comparison = oder_package.compare_packages(older, newer)
        self.assertEqual(comparison.new_count, 1)
        self.assertEqual(comparison.removed_count, 0)
        self.assertEqual(comparison.changed_count, 1)
        self.assertTrue(comparison.changes)


if __name__ == "__main__":
    unittest.main()
