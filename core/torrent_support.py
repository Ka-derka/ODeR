"""Small, defensive libtorrent boundary used by ODeR Library T1.

The rest of ODeR works with plain dictionaries and bytes.  Keeping the native
binding behind this module makes package validation deterministic and produces
clear errors if a third-party build is missing the optional runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import PurePosixPath


class TorrentSupportError(RuntimeError):
    pass


def _libtorrent():
    try:
        import libtorrent as lt
    except (ImportError, OSError) as exc:
        raise TorrentSupportError(
            "Torrent support is unavailable because the libtorrent runtime could not be loaded."
        ) from exc
    return lt


def available():
    try:
        _libtorrent()
        return True
    except TorrentSupportError:
        return False


def runtime_version():
    return str(getattr(_libtorrent(), "__version__", "unknown"))


def _safe_relative(value):
    text = str(value or "").replace("\\", "/").strip("/")
    path = PurePosixPath(text)
    if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise TorrentSupportError(f"Unsafe torrent file path: {value!r}")
    return path.as_posix()


def create_metainfo(
        root_path, files, *, trackers=(), web_seeds=(), private=False,
        creator="ODeR Creator", comment="", piece_size=0, progress=None):
    """Create one hybrid v1/v2 torrent from selected files below *root_path*.

    ``files`` contains dictionaries with ``source_path`` and ``relative_path``.
    Their order is retained and returned from :func:`inspect_metainfo` as the
    stable T1 file index mapping.
    """
    lt = _libtorrent()
    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        raise TorrentSupportError("The torrent source folder no longer exists.")
    root_name = os.path.basename(root_path.rstrip("\\/"))
    if not root_name:
        raise TorrentSupportError("The torrent source folder needs a usable name.")
    root_parent = os.path.dirname(root_path)
    storage = lt.file_storage()
    seen = set()
    for record in files:
        relative = _safe_relative(record.get("relative_path"))
        folded = relative.casefold()
        if folded in seen:
            raise TorrentSupportError(f"The torrent contains a duplicate file path: {relative}")
        seen.add(folded)
        source = os.path.abspath(str(record.get("source_path") or ""))
        expected = os.path.abspath(os.path.join(root_path, *PurePosixPath(relative).parts))
        try:
            inside = os.path.normcase(os.path.commonpath((root_path, source))) == os.path.normcase(root_path)
        except ValueError:
            inside = False
        if not inside or os.path.normcase(source) != os.path.normcase(expected):
            raise TorrentSupportError(f"Torrent source does not match its folder path: {relative}")
        if not os.path.isfile(source):
            raise TorrentSupportError(f"Torrent source file was not found: {relative}")
        stat = os.stat(source)
        storage.add_file(f"{root_name}/{relative}", stat.st_size, 0, int(stat.st_mtime))
    if storage.num_files() == 0:
        raise TorrentSupportError("Select at least one file for the torrent.")
    try:
        size = max(0, int(piece_size or 0))
        builder = lt.create_torrent(storage, size) if size else lt.create_torrent(storage)
        for tier, url in enumerate(trackers):
            builder.add_tracker(str(url), tier)
        for url in web_seeds:
            builder.add_url_seed(str(url))
        builder.set_priv(bool(private))
        if creator:
            builder.set_creator(str(creator))
        if comment:
            builder.set_comment(str(comment))
        callback = progress if callable(progress) else (lambda _piece: None)
        lt.set_piece_hashes(builder, root_parent, callback)
        return bytes(lt.bencode(builder.generate()))
    except TorrentSupportError:
        raise
    except Exception as exc:
        raise TorrentSupportError(f"Torrent creation failed: {exc}") from exc


def inspect_metainfo(data):
    """Parse torrent bytes into the portable metadata needed by T1."""
    lt = _libtorrent()
    try:
        raw = bytes(data)
        info = lt.torrent_info(raw)
        hashes = info.info_hashes()
        storage = info.files()
        trackers = []
        for tracker in info.trackers():
            trackers.append({"url": str(tracker.url), "tier": int(tracker.tier)})
        web_seeds = []
        for seed in info.web_seeds():
            if isinstance(seed, dict):
                url = seed.get("url")
            else:
                url = getattr(seed, "url", seed)
            if url:
                web_seeds.append(str(url))
        files = []
        for index in range(storage.num_files()):
            # Hybrid/v2 torrents may contain synthetic alignment files. They
            # remain in libtorrent's native index space, but are not catalog
            # artifacts and must not appear in the public T1 file map.
            if storage.file_flags(index) & storage.flag_pad_file:
                continue
            files.append({
                "file_index": index,
                "path": str(storage.file_path(index)).replace("\\", "/"),
                "size": int(storage.file_size(index)),
            })
        return {
            "name": str(info.name()),
            "info_hash_v1": str(hashes.v1) if hashes.has_v1() else "",
            "info_hash_v2": str(hashes.v2) if hashes.has_v2() else "",
            "private": bool(info.priv()),
            "piece_length": int(info.piece_length()),
            "trackers": trackers,
            "web_seeds": web_seeds,
            "files": files,
        }
    except TorrentSupportError:
        raise
    except Exception as exc:
        raise TorrentSupportError(f"The embedded torrent metadata is invalid: {exc}") from exc


def torrent_info(data):
    """Return a native torrent_info object for the download engine."""
    try:
        return _libtorrent().torrent_info(bytes(data))
    except Exception as exc:
        raise TorrentSupportError(f"The embedded torrent metadata is invalid: {exc}") from exc


def binding():
    """Return the checked native module to the runtime download manager."""
    return _libtorrent()
