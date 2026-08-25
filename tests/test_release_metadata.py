import os
import unittest
from unittest.mock import patch

from core.version import APP_VERSION, CREATOR_VERSION
from tools.verify_release import CANONICAL_VERSION, verify_release_metadata


class ReleaseMetadataTests(unittest.TestCase):
    def test_canonical_versions_accept_release_candidates(self):
        for value in ("1.0.0", "1.0.0-rc.1", "2.4.3-beta.12", "2026.0.1a", "2026.0.1b2", "2026.0.1rc"):
            with self.subTest(value=value):
                self.assertIsNotNone(CANONICAL_VERSION.fullmatch(value))
        for value in ("1.0", "v1.0.0", "1.0.0-", "1.0.0+local", "2026.0.1preview"):
            with self.subTest(value=value):
                self.assertIsNone(CANONICAL_VERSION.fullmatch(value))

        self.assertEqual(CREATOR_VERSION, "2026.0.2a")

    def test_repository_metadata_matches_current_version_and_tag(self):
        with patch.dict(
            os.environ,
            {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": f"v{APP_VERSION}"},
            clear=False,
        ):
            self.assertEqual(verify_release_metadata(), APP_VERSION)


if __name__ == "__main__":
    unittest.main()
