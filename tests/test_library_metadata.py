import base64
import os
import tempfile
import unittest
from unittest.mock import patch

from core import profiles
from core.library_metadata import (
    LibraryMetadataError, artwork_data_uri, decode_artwork_data_uri,
    normalize_library_metadata,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class LibraryMetadataTests(unittest.TestCase):
    def test_text_tags_and_artwork_are_normalized(self):
        artwork = artwork_data_uri("image/png", PNG_1X1)
        result = normalize_library_metadata({
            "description": "  A useful archive  ",
            "creator": "Curator",
            "category": "Software",
            "tags": ["Shareware", "shareware", " Preservation "],
            "artwork_data_uri": artwork,
        }, strict=True)
        self.assertEqual(result["description"], "A useful archive")
        self.assertEqual(result["tags"], ["Shareware", "Preservation"])
        mime_type, decoded = decode_artwork_data_uri(result["artwork_data_uri"])
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(decoded, PNG_1X1)

    def test_invalid_artwork_is_rejected_for_packages_and_dropped_from_saved_profiles(self):
        invalid = {"artwork_data_uri": "data:image/png;base64,bm90LWEtcG5n"}
        with self.assertRaises(LibraryMetadataError):
            normalize_library_metadata(invalid, strict=True)
        self.assertEqual(normalize_library_metadata(invalid), {})

    def test_profiles_persist_optional_metadata_without_a_schema_migration(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            index_path = os.path.join(temporary_dir, "profiles.json")

            def profile_dir(profile_id):
                target = os.path.join(temporary_dir, "profiles", profile_id)
                os.makedirs(target, exist_ok=True)
                return target

            with (
                patch.object(profiles, "profiles_index_path", return_value=index_path),
                patch.object(profiles, "profile_dir", side_effect=profile_dir),
            ):
                profile = profiles.create_profile("Archive", "https://example.test/files")
                profiles.update_profile(profile["id"], metadata={
                    "description": "Preserved software",
                    "tags": "DOS, Shareware, dos",
                })
                loaded = profiles.get_profile(profile["id"])

            self.assertEqual(loaded["metadata"]["description"], "Preserved software")
            self.assertEqual(loaded["metadata"]["tags"], ["DOS", "Shareware"])


if __name__ == "__main__":
    unittest.main()
