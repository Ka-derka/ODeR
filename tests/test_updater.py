from datetime import datetime, timedelta, timezone
import hashlib
import os
import sys
import tempfile
import types
import unittest

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    class _RequestException(Exception):
        pass

    sys.modules["requests"] = types.SimpleNamespace(
        RequestException=_RequestException,
        Session=lambda: None,
    )

from core import updater


class FakeResponse:
    def __init__(self, *, json_data=None, content=b"", url="https://github.com/Ka-derka/ODeR/releases/download/v0.16.0/file"):
        self._json_data = json_data
        self.content = content
        self.url = url

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self.content), max(1, chunk_size)):
            yield self.content[index:index + chunk_size]

    def close(self):
        return None


class FakeSession:
    def __init__(self, responses):
        self.responses = {url: list(items) for url, items in responses.items()}

    def get(self, url, **_kwargs):
        return self.responses[url].pop(0)

    def close(self):
        return None


def release(version="0.16.0", asset_name=updater.INSTALLER_ASSET_NAME, digest=None, tag=None):
    payload = b"ODeR update"
    checksum = digest or hashlib.sha256(payload).hexdigest()
    return {
        "tag_name": tag or f"v{version}",
        "name": f"ODeR {version}",
        "body": "Release notes",
        "published_at": "2026-08-20T12:00:00Z",
        "html_url": f"https://github.com/Ka-derka/ODeR/releases/tag/v{version}",
        "draft": False,
        "prerelease": "-" in version,
        "assets": [{
            "name": asset_name,
            "browser_download_url": f"https://github.com/Ka-derka/ODeR/releases/download/v{version}/{asset_name}",
            "size": len(payload),
            "digest": f"sha256:{checksum}",
        }],
    }


class UpdaterTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(updater.is_newer_version("0.18.0", "0.17.0"))
        self.assertTrue(updater.is_newer_version("0.18", "0.17.0"))
        self.assertEqual(updater.normalize_version("v0.18"), "0.18.0")
        self.assertTrue(updater.is_newer_version("0.17.0", "0.16.2"))
        self.assertTrue(updater.is_newer_version("0.16.2", "0.16.1"))
        self.assertTrue(updater.is_newer_version("0.16.1", "0.16.0"))
        self.assertTrue(updater.is_newer_version("0.16.0", "0.15.2"))
        self.assertTrue(updater.is_newer_version("0.16.0", "0.16.0-beta.1"))
        self.assertTrue(updater.is_newer_version("0.16.0-beta.10", "0.16.0-beta.2"))
        self.assertTrue(updater.is_newer_version("1.0.0-rc.2", "1.0.0-rc.1"))
        self.assertTrue(updater.is_newer_version("1.0.0", "1.0.0-rc.1"))
        self.assertTrue(updater.is_newer_version("1.1.0-alpha.1", "1.0.0"))
        self.assertFalse(updater.is_newer_version("0.16.0+build.2", "0.16.0+build.1"))
        self.assertFalse(updater.is_newer_version("v0.15.2", "0.15.2"))
        with self.assertRaises(updater.UpdateError):
            updater.parse_version("latest")

    def test_update_check_uses_installer_and_github_digest(self):
        metadata = release()
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[metadata])]})
        info = updater.check_for_update("0.15.2", session=session)
        self.assertEqual(info.version, "0.16.0")
        self.assertEqual(info.asset.name, updater.INSTALLER_ASSET_NAME)
        self.assertEqual(info.asset.sha256, metadata["assets"][0]["digest"].split(":", 1)[1])

    def test_github_normalized_installer_name_is_accepted(self):
        metadata = release(asset_name="ODeR.Installer.exe")
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[metadata])]})
        info = updater.check_for_update("0.15.2", session=session)
        self.assertEqual(info.asset.name, "ODeR.Installer.exe")

    def test_current_version_needs_no_asset_download(self):
        metadata = release(version="0.15.2")
        metadata["assets"] = []
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[metadata])]})
        self.assertIsNone(updater.check_for_update("0.15.2", session=session))

    def test_abbreviated_release_tag_updates_skipped_versions(self):
        metadata = release(version="0.18.0", tag="0.18")
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[metadata])]})
        info = updater.check_for_update("0.16.2", session=session)
        self.assertEqual(info.version, "0.18.0")

    def test_malformed_and_incomplete_releases_do_not_block_valid_update(self):
        malformed = release(version="9.0.0", tag="latest")
        incomplete = release(version="0.20.0")
        incomplete["assets"] = []
        valid = release(version="0.19.0", asset_name="ODeR Installer 0.19.exe")
        session = FakeSession({
            updater.RELEASES_URL: [FakeResponse(json_data=[malformed, incomplete, valid])]
        })
        info = updater.check_for_update("0.16.2", session=session)
        self.assertEqual(info.version, "0.19.0")
        self.assertEqual(info.asset.name, "ODeR Installer 0.19.exe")

    def test_preview_channel_selects_portable_asset(self):
        draft = release(version="9.0.0")
        draft["draft"] = True
        preview = release(version="0.17.0-beta.1", asset_name=updater.PORTABLE_ASSET_NAME)
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[draft, preview])]})
        info = updater.check_for_update("0.16.0", channel="preview", portable=True, session=session)
        self.assertEqual(info.version, "0.17.0-beta.1")
        self.assertEqual(info.asset.name, updater.PORTABLE_ASSET_NAME)

    def test_stable_channel_ignores_alpha_release(self):
        alpha = release(version="1.1.0-alpha.1")
        session = FakeSession({updater.RELEASES_URL: [FakeResponse(json_data=[alpha])]})
        self.assertIsNone(updater.check_for_update("1.0.0", channel="stable", session=session))

    def test_checksum_file_is_used_when_asset_digest_is_missing(self):
        metadata = release()
        payload = b"ODeR update"
        checksum = hashlib.sha256(payload).hexdigest()
        metadata["assets"][0]["digest"] = None
        checksum_url = "https://github.com/Ka-derka/ODeR/releases/download/v0.16.0/SHA256SUMS.txt"
        metadata["assets"].append({
            "name": updater.CHECKSUM_ASSET_NAME,
            "browser_download_url": checksum_url,
            "size": 100,
        })
        session = FakeSession({
            updater.RELEASES_URL: [FakeResponse(json_data=[metadata])],
            checksum_url: [FakeResponse(content=f"{checksum}  {updater.INSTALLER_ASSET_NAME}\n".encode())],
        })
        info = updater.check_for_update("0.15.2", session=session)
        self.assertEqual(info.asset.sha256, checksum)

    def test_verified_download_is_moved_into_place(self):
        payload = b"MZverified update bytes"
        asset_url = "https://github.com/Ka-derka/ODeR/releases/download/v0.16.0/ODeR%20Installer.exe"
        info = updater.UpdateInfo(
            version="0.16.0", title="ODeR", notes="", published_at="", page_url="",
            channel="stable", asset=updater.ReleaseAsset(
                updater.INSTALLER_ASSET_NAME, asset_url, len(payload), hashlib.sha256(payload).hexdigest()
            ),
        )
        session = FakeSession({asset_url: [FakeResponse(content=payload, url=asset_url)]})
        progress = []
        with tempfile.TemporaryDirectory() as temporary_dir:
            result = updater.download_update(
                info, destination_root=temporary_dir, session=session,
                progress=lambda done, total: progress.append((done, total)),
            )
            self.assertTrue(os.path.isfile(result))
            with open(result, "rb") as handle:
                self.assertEqual(handle.read(), payload)
            self.assertEqual(progress[-1], (len(payload), len(payload)))

    def test_bad_download_is_deleted(self):
        payload = b"MZtampered"
        asset_url = "https://github.com/Ka-derka/ODeR/releases/download/v0.16.0/ODeR%20Installer.exe"
        info = updater.UpdateInfo(
            version="0.16.0", title="ODeR", notes="", published_at="", page_url="",
            channel="stable", asset=updater.ReleaseAsset(
                updater.INSTALLER_ASSET_NAME, asset_url, len(payload), "0" * 64
            ),
        )
        session = FakeSession({asset_url: [FakeResponse(content=payload, url=asset_url)]})
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaises(updater.UpdateError):
                updater.download_update(info, destination_root=temporary_dir, session=session)
            version_dir = os.path.join(temporary_dir, "0.16.0")
            self.assertFalse(os.path.exists(os.path.join(version_dir, updater.INSTALLER_ASSET_NAME)))
            self.assertFalse(os.path.exists(os.path.join(version_dir, updater.INSTALLER_ASSET_NAME + ".part")))

    def test_verified_non_executable_payload_is_rejected(self):
        payload = b"not a Windows executable"
        asset_url = "https://github.com/Ka-derka/ODeR/releases/download/v0.19.0/ODeR%20Installer.exe"
        info = updater.UpdateInfo(
            version="0.19.0", title="ODeR", notes="", published_at="", page_url="",
            channel="stable", asset=updater.ReleaseAsset(
                updater.INSTALLER_ASSET_NAME, asset_url, len(payload), hashlib.sha256(payload).hexdigest()
            ),
        )
        session = FakeSession({asset_url: [FakeResponse(content=payload, url=asset_url)]})
        with tempfile.TemporaryDirectory() as temporary_dir:
            with self.assertRaisesRegex(updater.UpdateError, "not a Windows executable"):
                updater.download_update(info, destination_root=temporary_dir, session=session)

    def test_existing_verified_download_is_reused(self):
        payload = b"MZalready downloaded"
        asset_url = "https://github.com/Ka-derka/ODeR/releases/download/v0.19.0/ODeR%20Installer.exe"
        info = updater.UpdateInfo(
            version="0.19.0", title="ODeR", notes="", published_at="", page_url="",
            channel="stable", asset=updater.ReleaseAsset(
                updater.INSTALLER_ASSET_NAME, asset_url, len(payload), hashlib.sha256(payload).hexdigest()
            ),
        )
        with tempfile.TemporaryDirectory() as temporary_dir:
            version_dir = os.path.join(temporary_dir, info.version)
            os.makedirs(version_dir)
            destination = os.path.join(version_dir, updater.INSTALLER_ASSET_NAME)
            with open(destination, "wb") as handle:
                handle.write(payload)
            result = updater.download_update(
                info, destination_root=temporary_dir, session=FakeSession({})
            )
            self.assertEqual(result, destination)

    def test_daily_check_interval(self):
        now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(updater.should_check((now - timedelta(hours=23)).isoformat(), now=now))
        self.assertTrue(updater.should_check((now - timedelta(hours=25)).isoformat(), now=now))
        self.assertTrue(updater.should_check("not a timestamp", now=now))


if __name__ == "__main__":
    unittest.main()
