"""Small, defensive libtorrent boundary used by ODeR Library T1.

The rest of ODeR works with plain dictionaries and bytes.  Keeping the native
binding behind this module makes package validation deterministic and produces
clear errors if a third-party build is missing the optional runtime.
"""
from __future__ import annotations

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


def _canonicalize_generated_hybrid(document):
    """Keep generated v1 piece spans in the same order as the BEP52 tree.

    Some libtorrent builders sort full paths, but v2 dictionaries sort each
    path component. For example a-/x precedes a/x in a flat string sort, while
    the v2 tree visits a first. That produces error 213 even with create_file_entry.
    Each generated file is piece-aligned and padded: move its ENTIRE v1 piece
    span with its file/padding records. Never reorder filenames alone, and never
    apply this to imported torrents (it changes the v1 info hash).
    """
    info = document.get(b"info", {})
    files = info.get(b"files")
    if info.get(b"meta version") != 2 or not isinstance(files, list) or b"pieces" not in info:
        return document
    piece_length = info[b"piece length"]
    pieces = info[b"pieces"]
    groups = []
    offset = 0
    for entry in files:
        length = entry[b"length"]
        if b"p" in entry.get(b"attr", b""):
            if not groups:
                raise TorrentSupportError("Generated hybrid torrent starts with unexpected padding.")
            groups[-1]["entries"].append(entry)
        else:
            groups.append({"key": tuple(entry[b"path"]), "start": offset, "entries": [entry]})
        offset += length
        groups[-1]["end"] = offset
    ordered = sorted(groups, key=lambda group: group["key"])
    if [g["key"] for g in groups] == [g["key"] for g in ordered]:
        return document
    if (piece_length < 16384 or piece_length & (piece_length - 1)
            or len(pieces) != ((offset + piece_length - 1) // piece_length) * 20
            or any(g["start"] % piece_length or g["end"] % piece_length for g in groups)):
        raise TorrentSupportError("Cannot safely canonicalize the generated hybrid torrent's piece alignment.")
    info[b"files"] = [entry for group in ordered for entry in group["entries"]]
    info[b"pieces"] = b"".join(
        pieces[g["start"] // piece_length * 20:g["end"] // piece_length * 20] for g in ordered
    )
    return document


def _source_stamp(path):
    stat = os.stat(path)
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_dev, stat.st_ino)


def _create_hybrid_metainfo(root_parent, records, *, trackers=(), web_seeds=(), private=False,
                            creator="ODeR Creator", comment="", piece_size=0, progress=None,
                            purpose="catalog payload"):
    """Shared generation boundary for payload and package-update torrents."""
    lt = _libtorrent()
    stage = "reading source files"
    size = 0
    snapshots = []
    try:
        storage = lt.file_storage()
        entry_type = getattr(lt, "create_file_entry", None)
        entries = [] if callable(entry_type) else None
        expected = {}
        for record in records:
            source = record["source_path"]
            name = record["torrent_path"]
            stamp = _source_stamp(source)
            snapshots.append((source, stamp))
            expected[name] = stamp[0]
            storage.add_file(name, stamp[0])
            if entries is not None:
                try:
                    entries.append(entry_type(name, stamp[0]))
                except (TypeError, ValueError):
                    entries = None  # Older Monterey-compatible Python binding.
        if not snapshots:
            raise TorrentSupportError("Select at least one file for the torrent.")
        if not any(stamp[0] for _path, stamp in snapshots):
            raise TorrentSupportError("A torrent needs at least one non-empty file. Empty files can still be bundled in the library.")
        stage = "creating file layout"
        size = max(0, int(piece_size or 0))
        builder = lt.create_torrent(entries if entries is not None else storage, size)
        size = int(builder.piece_length())
        for tier, url in enumerate(trackers):
            builder.add_tracker(str(url), tier)
        for url in web_seeds:
            builder.add_url_seed(str(url))
        builder.set_priv(bool(private))
        if creator:
            builder.set_creator(str(creator))
        if comment:
            builder.set_comment(str(comment))
        stage = "hashing source files"
        lt.set_piece_hashes(builder, root_parent, progress if callable(progress) else (lambda _piece: None))
        stage = "checking source stability"
        for path, stamp in snapshots:
            if _source_stamp(path) != stamp:
                raise TorrentSupportError(f"Source file changed during hashing: {os.path.basename(path)}. Stop editing or downloading it and try again.")
        stage = "validating generated metadata"
        document = _canonicalize_generated_hybrid(builder.generate())
        data = bytes(lt.bencode(document))
        metadata = inspect_metainfo(data)
        actual = {f["path"]: f["size"] for f in metadata["files"]}
        if actual != expected or len(metadata["files"]) != len(records):
            raise TorrentSupportError("The generated torrent did not preserve every selected file path and size.")
        if not metadata["info_hash_v1"] or not metadata["info_hash_v2"]:
            raise TorrentSupportError("The generated torrent did not preserve hybrid v1/v2 support.")
        return data
    except Exception as exc:
        empty = sum(stamp[0] == 0 for _path, stamp in snapshots)
        raise TorrentSupportError(
            f"Torrent creation failed for {purpose} while {stage} "
            f"(libtorrent {getattr(lt, '__version__', 'unknown')}; {len(records)} files, "
            f"{empty} empty; piece size {size or 'automatic'}): {exc}"
        ) from exc


def create_package_metainfo(package_path, *, trackers=(), private=False, creator="ODeR Creator"):
    package_path = os.path.abspath(package_path)
    return _create_hybrid_metainfo(
        os.path.dirname(package_path),
        [{"source_path": package_path, "torrent_path": os.path.basename(package_path)}],
        trackers=trackers, private=private, creator=creator, purpose="library package update",
    )


def create_metainfo(
        root_path, files, *, trackers=(), web_seeds=(), private=False,
        creator="ODeR Creator", comment="", piece_size=0, progress=None):
    """Create one hybrid v1/v2 torrent from selected files below *root_path*.

    ``files`` contains dictionaries with ``source_path`` and ``relative_path``.
    Libtorrent may put those files into canonical torrent order, so callers
    must use the paths returned by :func:`inspect_metainfo` for file indices.
    """
    root_path = os.path.abspath(root_path)
    if not os.path.isdir(root_path):
        raise TorrentSupportError("The torrent source folder no longer exists.")
    root_name = os.path.basename(root_path.rstrip("\\/"))
    if not root_name:
        raise TorrentSupportError("The torrent source folder needs a usable name.")
    root_parent = os.path.dirname(root_path)
    prepared = []
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
        torrent_path = f"{root_name}/{relative}"
        prepared.append({"source_path": source, "torrent_path": torrent_path})
    return _create_hybrid_metainfo(root_parent, prepared, trackers=trackers, web_seeds=web_seeds,
                                  private=private, creator=creator, comment=comment,
                                  piece_size=piece_size, progress=progress)


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
