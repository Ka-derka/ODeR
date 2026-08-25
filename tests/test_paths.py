import os
import sys
import tempfile
import unittest
from unittest import mock

from core import paths


class ApplicationPathTests(unittest.TestCase):
    def test_portable_executable_uses_data_folder_beside_it(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            executable = os.path.join(temporary_dir, "ODeR-Portable.exe")
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
                sys, "executable", executable
            ):
                self.assertTrue(paths.is_portable())
                self.assertEqual(paths.data_dir(), os.path.join(temporary_dir, "data"))

    def test_portable_marker_survives_executable_rename(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            executable = os.path.join(temporary_dir, "Renamed.exe")
            with open(os.path.join(temporary_dir, "portable.flag"), "w", encoding="utf-8"):
                pass
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
                sys, "executable", executable
            ):
                self.assertTrue(paths.is_portable())
                self.assertEqual(paths.data_dir(), os.path.join(temporary_dir, "data"))

    def test_installed_executable_uses_local_application_data(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            executable = os.path.join(temporary_dir, "Program Files", "ODeR", "ODeR.exe")
            local_app_data = os.path.join(temporary_dir, "LocalAppData")
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
                sys, "executable", executable
            ), mock.patch.dict(os.environ, {"LOCALAPPDATA": local_app_data}):
                self.assertFalse(paths.is_portable())
                self.assertEqual(paths.data_dir(), os.path.join(local_app_data, "ODeR"))

    def test_macos_application_uses_application_support(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            executable = os.path.join(temporary_dir, "ODeR.app", "Contents", "MacOS", "ODeR")
            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
                sys, "executable", executable
            ), mock.patch.object(sys, "platform", "darwin"), mock.patch(
                "core.paths.os.path.expanduser", return_value=temporary_dir
            ):
                self.assertFalse(paths.is_portable())
                self.assertEqual(
                    paths.data_dir(),
                    os.path.join(temporary_dir, "Library", "Application Support", "ODeR"),
                )


if __name__ == "__main__":
    unittest.main()
