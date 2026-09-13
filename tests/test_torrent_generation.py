"""Synthetic torrent generation regressions; never start a network session."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import libtorrent as lt
from core.torrent_support import (TorrentSupportError, _canonicalize_generated_hybrid,
                                 create_metainfo, create_package_metainfo, inspect_metainfo)


class _LegacyBinding:
    """Exercise the file_storage API without pretending to be another runtime."""
    create_file_entry = None

    def __getattr__(self, name):
        return getattr(lt, name)


class TorrentGenerationTests(unittest.TestCase):
    def _assert_piece_hashes(self, data, root):
        info = lt.bdecode(data)[b"info"]
        stream = bytearray()
        for entry in info[b"files"]:
            if b"p" in entry.get(b"attr", b""):
                stream.extend(bytes(entry[b"length"]))
            else:
                path = root.joinpath(*(part.decode("utf-8") for part in entry[b"path"]))
                content = path.read_bytes()
                self.assertEqual(len(content), entry[b"length"])
                stream.extend(content)
                node = info[b"file tree"]
                for part in entry[b"path"]:
                    node = node[part]
                leaf = node[b""]
                self.assertEqual(leaf[b"length"], len(content))
                if content:
                    hashes = [hashlib.sha256(content[i:i + 16384]).digest()
                              for i in range(0, len(content), 16384)]
                    hashes.extend([bytes(32)] * ((1 << (len(hashes) - 1).bit_length()) - len(hashes)))
                    while len(hashes) > 1:
                        hashes = [hashlib.sha256(hashes[i] + hashes[i + 1]).digest()
                                  for i in range(0, len(hashes), 2)]
                    self.assertEqual(leaf[b"pieces root"], hashes[0])
        length = info[b"piece length"]
        expected = b"".join(hashlib.sha1(stream[i:i + length]).digest()
                            for i in range(0, len(stream), length))
        self.assertEqual(info[b"pieces"], expected)

    def test_hybrid_layout_edge_cases(self):
        cases = {
            "empty_first": [("a.empty", 0), ("b.bin", 7)],
            "empty_last": [("a.bin", 7), ("z.empty", 0)],
            "empty_between": [("a.bin", 7), ("b.empty", 0), ("c.bin", 11)],
            "empty_nested": [("root.bin", 7), ("nested/empty", 0), ("nested/last.bin", 19)],
            "nested_before_root": [("z.bin", 31), ("a/one.bin", 17), ("a/two.bin", 23)],
            "prefixes": [("a.bin", 7), ("a/one.bin", 17), ("a-/one.bin", 23)],
            "prefixes_with_empty": [("a-/empty", 0), ("a/empty", 0), ("a/x", 29), ("a.bin", 13)],
            "unicode": [("Žluťoučký/你好.bin", 7), ("A/data.bin", 11), ("é.txt", 13)],
            "piece_boundaries": [("a.bin", 16384), ("b.bin", 16385), ("c.bin", 32767)],
        }
        for name, layout in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="oder-torrent-regression-") as directory:
                root = Path(directory) / "payload"
                records = []
                for relative, size in layout:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(bytes([len(records) + 1]) * size)
                    records.append({"source_path": str(path), "relative_path": relative})
                data = create_metainfo(str(root), records, piece_size=16384)
                info = inspect_metainfo(data)
                self.assertTrue(info["info_hash_v1"])
                self.assertTrue(info["info_hash_v2"])
                self.assertEqual({f["path"]: f["size"] for f in info["files"]},
                                 {f"payload/{p}": n for p, n in layout})
                self._assert_piece_hashes(data, root)

    def test_prefix_layout_preserves_both_hash_sets_at_multiple_piece_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = []
            for index, relative in enumerate(("a.bin", "a/one", "a-/one", "a/zero", "a-/two")):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bytes([index + 1]) * (0 if relative.endswith("zero") else 65536 + index * 137))
                records.append({"source_path": str(path), "relative_path": relative})
            for size in (0, 16384, 65536, 262144):
                with self.subTest(size=size):
                    data = create_metainfo(str(root), records[::-1], piece_size=size)
                    self._assert_piece_hashes(data, root)

    def test_legacy_file_storage_path_handles_interleaved_prefixes(self):
        with patch("core.torrent_support._libtorrent", return_value=_LegacyBinding()):
            self.test_hybrid_layout_edge_cases()

    def test_already_canonical_output_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one").write_bytes(b"one")
            (root / "two").write_bytes(b"two")
            data = create_metainfo(directory, [{"source_path": str(root / name), "relative_path": name}
                                              for name in ("one", "two")])
            document = lt.bdecode(data)
            before = lt.bencode(document)
            self.assertEqual(lt.bencode(_canonicalize_generated_hybrid(document)), before)

    def test_unsafe_piece_reordering_is_rejected(self):
        document = {b"info": {b"meta version": 2, b"piece length": 16384, b"pieces": b"x" * 20,
                             b"files": [{b"path": [b"a-", b"x"], b"length": 2},
                                        {b"path": [b"a", b"x"], b"length": 2}]}}
        original = deepcopy(document)
        with self.assertRaisesRegex(TorrentSupportError, "piece alignment"):
            _canonicalize_generated_hybrid(document)
        self.assertEqual(document, original)

    def test_all_empty_files_get_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty"
            path.touch()
            with self.assertRaisesRegex(TorrentSupportError, "at least one non-empty file"):
                create_metainfo(directory, [{"source_path": str(path), "relative_path": "empty"}])

    def test_changed_source_is_detected_before_returning_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_bytes(b"original")
            native_hash = lt.set_piece_hashes

            def mutate(*args):
                native_hash(*args)
                path.write_bytes(b"changed after hashing")

            with patch.object(lt, "set_piece_hashes", side_effect=mutate):
                with self.assertRaisesRegex(TorrentSupportError, "Source file changed during hashing"):
                    create_metainfo(directory, [{"source_path": str(path), "relative_path": "file"}])

    def test_package_update_uses_shared_validation_and_single_file_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Sample.odrlib"
            content = b"package bytes" * 32768
            path.write_bytes(content)
            data = create_package_metainfo(str(path))
            info = inspect_metainfo(data)
            self.assertEqual(info["files"], [{"file_index": 0, "path": "Sample.odrlib", "size": len(content)}])
            native = lt.bdecode(data)[b"info"]
            size = native[b"piece length"]
            self.assertEqual(native[b"pieces"], b"".join(hashlib.sha1(content[i:i + size]).digest()
                                                       for i in range(0, len(content), size)))
            with patch("core.torrent_support.inspect_metainfo", side_effect=RuntimeError("synthetic validation failure")):
                with self.assertRaisesRegex(TorrentSupportError, "library package update.*validating generated metadata.*libtorrent"):
                    create_package_metainfo(str(path))

    def test_creator_build_preserves_prefix_files_and_catalog_indices(self):
        from core.odrlib import build_library, import_folder_selection, new_project, scan_folder
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "payload"
            content_by_path = {"Data/one.bin": b"one" * 20000,
                               "Data-2/two.bin": b"two" * 17000,
                               "Data.txt": b"root file", "Data/empty": b""}
            for relative, content in content_by_path.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            project, count = import_folder_selection(new_project(), str(root), scan_folder(str(root)))
            result = build_library(project, str(Path(directory) / "regression.odrlib"))
            self.assertEqual(count, len(content_by_path))
            data = Path(result.torrent_path).read_bytes()
            metadata = inspect_metainfo(data)
            native_by_index = {record["file_index"]: record for record in metadata["files"]}
            for item in result.package.items:
                source = item["artifacts"][0]["sources"][0]
                native_file = native_by_index[source["file_index"]]
                self.assertEqual(source["path"], native_file["path"])
                relative = source["path"].removeprefix("payload/")
                self.assertEqual(source["sha256"], hashlib.sha256(content_by_path[relative]).hexdigest())
            self._assert_piece_hashes(data, root)


if __name__ == "__main__":
    unittest.main()
