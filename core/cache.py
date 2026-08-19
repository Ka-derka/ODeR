"""SQLite-backed offline cache for scalable directory browsing.

The older project stored the entire cache as one JSON object.  That works for
small trees but becomes expensive when a site contains hundreds of thousands
of entries.  This module keeps the same logical model while storing nodes in a
small SQLite database with indexes for parent browsing and name search.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from core.paths import profile_cache_checkpoint_path, profile_cache_db_path, profile_cache_path

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_SCHEMA_READY: set[str] = set()
_SCHEMA_GUARD = threading.Lock()
_ACTIVE_FULL_UPDATES: set[str] = set()
_CHECKPOINT_GUARD = threading.Lock()
SCHEMA_VERSION = 1


class CacheVersionError(RuntimeError):
    """The cache was created by a newer, incompatible ODeR version."""


def _quarantine_database(profile_id: str) -> str | None:
    path = profile_cache_db_path(profile_id)
    if not os.path.exists(path):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = f"{path}.corrupt-{stamp}"
    counter = 1
    while os.path.exists(destination):
        destination = f"{path}.corrupt-{stamp}-{counter}"
        counter += 1
    os.replace(path, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = path + suffix
        if os.path.exists(sidecar):
            try:
                os.replace(sidecar, destination + suffix)
            except OSError:
                pass
    with _SCHEMA_GUARD:
        _SCHEMA_READY.discard(profile_id)
    return destination


def _lock(profile_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(profile_id, threading.RLock())


def _connect(profile_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(profile_cache_db_path(profile_id), timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
    except Exception:
        conn.close()
        raise
    with _SCHEMA_GUARD:
        if profile_id not in _SCHEMA_READY:
            # WAL is persistent, so negotiating it once per database/process is
            # enough. Doing this for every short-lived reader can momentarily
            # require a write lock and stall browsing during a crawl.
            conn.execute("PRAGMA journal_mode=WAL")
            version_row = conn.execute("PRAGMA user_version").fetchone()
            existing_version = int(version_row[0] if version_row else 0)
            if existing_version > SCHEMA_VERSION:
                conn.close()
                raise CacheVersionError(
                    f"This cached index uses schema {existing_version}, but this ODeR version supports "
                    f"up to schema {SCHEMA_VERSION}. Update ODeR before opening it."
                )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS nodes (
                    url TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    is_dir INTEGER NOT NULL,
                    size TEXT,
                    parent_url TEXT,
                    crawled INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER,
                    last_seen TEXT,
                    last_scanned TEXT
                )"""
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
            for name, declaration in (
                ("size_bytes", "INTEGER"), ("last_seen", "TEXT"), ("last_scanned", "TEXT")
            ):
                if name not in columns:
                    conn.execute(f"ALTER TABLE nodes ADD COLUMN {name} {declaration}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_url, name COLLATE NOCASE)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_nodes_parent_kind_name "
                "ON nodes(parent_url, is_dir DESC, name COLLATE NOCASE)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name COLLATE NOCASE)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_crawled_dir ON nodes(is_dir, crawled)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_last_scanned ON nodes(is_dir, last_scanned)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_size_bytes ON nodes(is_dir, size_bytes)")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS scan_runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    mode TEXT NOT NULL,
                    root_url TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    before_count INTEGER NOT NULL DEFAULT 0,
                    after_count INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0,
                    removed_count INTEGER NOT NULL DEFAULT 0,
                    changed_count INTEGER NOT NULL DEFAULT 0,
                    recorded_changes INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS snapshot_baseline (
                    run_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_dir INTEGER NOT NULL,
                    size TEXT,
                    size_bytes INTEGER,
                    parent_url TEXT,
                    PRIMARY KEY(run_id, url)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    url TEXT NOT NULL,
                    name TEXT NOT NULL,
                    is_dir INTEGER NOT NULL,
                    old_size TEXT,
                    new_size TEXT
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_changes_run ON changes(run_id, change_type, name)")
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(url UNINDEXED, name, tokenize='unicode61')")
                conn.executescript(
                    """CREATE TRIGGER IF NOT EXISTS nodes_fts_insert AFTER INSERT ON nodes BEGIN
                           INSERT INTO nodes_fts(url,name) VALUES(new.url,new.name);
                       END;
                       CREATE TRIGGER IF NOT EXISTS nodes_fts_delete AFTER DELETE ON nodes BEGIN
                           DELETE FROM nodes_fts WHERE url=old.url;
                       END;
                       CREATE TRIGGER IF NOT EXISTS nodes_fts_update AFTER UPDATE OF url,name ON nodes BEGIN
                           DELETE FROM nodes_fts WHERE url=old.url;
                           INSERT INTO nodes_fts(url,name) VALUES(new.url,new.name);
                       END;"""
                )
                fts_version = conn.execute("SELECT value FROM meta WHERE key='fts_version'").fetchone()
                if not fts_version or fts_version[0] != "1":
                    conn.execute("DELETE FROM nodes_fts")
                    conn.execute("INSERT INTO nodes_fts(url,name) SELECT url,name FROM nodes")
                    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('fts_version','1')")
                conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('fts_available','1')")
            except sqlite3.OperationalError:
                conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('fts_available','0')")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
            _SCHEMA_READY.add(profile_id)
    return conn


@contextmanager
def _reader(profile_id: str):
    """Open an independent WAL reader without waiting on the Python writer lock."""
    conn = _connect(profile_id)
    try:
        yield conn
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_size_bytes(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().upper().replace("IB", "B")
    import re
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([KMGTPE]?B)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = (match.group(2) or "B")[0]
    power = {"B": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}.get(unit, 0)
    return int(number * (1024 ** power))


def _norm_base(url: str) -> str:
    return url if url.endswith("/") else url + "/"


def _parent_url(url: str, base_url: str) -> str | None:
    if url == base_url:
        return None
    path = urlsplit(url).path.rstrip("/")
    base_path = urlsplit(base_url).path.rstrip("/")
    if not path.startswith(base_path):
        return None
    parent_path = path.rsplit("/", 1)[0] + "/"
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parent_path, "", ""))


def initialize(profile_id: str, base_url: str) -> None:
    base_url = _norm_base(base_url)
    with _lock(profile_id):
        checkpoint = profile_cache_checkpoint_path(profile_id)
        with _CHECKPOINT_GUARD:
            recover_checkpoint = os.path.isfile(checkpoint) and profile_id not in _ACTIVE_FULL_UPDATES
        if recover_checkpoint:
            try:
                replace_database(profile_id, checkpoint)
                os.remove(checkpoint)
                try:
                    from core import applog
                    applog.log(
                        f"Restored the last complete cache for profile {profile_id} after an interrupted full update."
                    )
                except Exception:
                    pass
            except Exception as exc:
                try:
                    from core import applog
                    applog.log(
                        f"Could not restore the full-update checkpoint for profile {profile_id}: {exc}"
                    )
                except Exception:
                    pass
                raise
        try:
            conn = _connect(profile_id)
        except sqlite3.DatabaseError:
            # Directory caches are derived data. Preserve a damaged database
            # for diagnosis, then recreate an empty cache so startup and a
            # future crawl remain possible.
            quarantined = _quarantine_database(profile_id)
            try:
                from core import applog
                applog.log(
                    f"Damaged cache for profile {profile_id} was preserved as "
                    f"{os.path.basename(quarantined) if quarantined else 'a recovery copy'}; "
                    "an empty cache was created."
                )
            except Exception:
                pass
            conn = _connect(profile_id)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='base_url'").fetchone()
            old_base = row[0] if row else None
            if old_base and old_base != base_url:
                conn.execute("DELETE FROM nodes")
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('base_url',?)", (base_url,))
            conn.execute(
                "INSERT OR IGNORE INTO nodes(url,name,is_dir,size,parent_url,crawled) VALUES(?,?,?,?,?,0)",
                (base_url, "/", 1, None, None),
            )
            conn.commit()
        finally:
            conn.close()


def migrate_json_if_needed(profile_id: str, base_url: str) -> bool:
    """Migrate an existing cache.json once. Returns True when migration occurred."""
    db_path = profile_cache_db_path(profile_id)
    if os.path.exists(db_path):
        initialize(profile_id, base_url)
        return False
    json_path = profile_cache_path(profile_id)
    if not os.path.exists(json_path):
        initialize(profile_id, base_url)
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            tree = json.load(f)
    except (OSError, json.JSONDecodeError):
        initialize(profile_id, base_url)
        return False
    initialize(profile_id, base_url)
    nodes = tree.get("nodes", {})
    rows = []
    for url, node in nodes.items():
        rows.append((url, node.get("name", "/"), 1 if node.get("is_dir") else 0,
                     node.get("size"), _parent_url(url, base_url), 1 if node.get("crawled") else 0))
        if len(rows) >= 5000:
            upsert_nodes(profile_id, rows)
            rows.clear()
    if rows:
        upsert_nodes(profile_id, rows)
    try:
        os.replace(json_path, json_path + ".migrated")
    except OSError:
        pass
    return True


def upsert_nodes(profile_id: str, rows) -> None:
    now = _now_iso()
    prepared = [tuple(row[:6]) + (_parse_size_bytes(row[3]), now) for row in rows]
    if not prepared:
        return
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            conn.executemany(
                """INSERT INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET
                     name=excluded.name,
                     is_dir=excluded.is_dir,
                     size=excluded.size,
                     size_bytes=excluded.size_bytes,
                     parent_url=excluded.parent_url,
                     crawled=CASE WHEN nodes.is_dir=1 AND excluded.is_dir=1 THEN nodes.crawled ELSE excluded.crawled END,
                     last_seen=excluded.last_seen""",
                prepared,
            )
            conn.commit()
        finally:
            conn.close()


def replace_children(profile_id: str, parent_url: str, rows, mark_parent_crawled: bool = True) -> dict:
    """Replace one folder listing in a single transaction.

    Marking the parent as crawled here avoids opening a second connection and
    committing a second transaction for every directory request.
    """
    now = _now_iso()
    prepared = [tuple(row[:6]) + (_parse_size_bytes(row[3]), now) for row in rows]
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            before = conn.execute("SELECT COUNT(*) FROM nodes WHERE parent_url=?", (parent_url,)).fetchone()[0]
            conn.execute("DROP TABLE IF EXISTS temp.seen_urls")
            conn.execute("CREATE TEMP TABLE seen_urls(url TEXT PRIMARY KEY)")
            if prepared:
                conn.executemany("INSERT OR IGNORE INTO seen_urls(url) VALUES(?)", ((row[0],) for row in prepared))
                conn.executemany(
                    """INSERT INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(url) DO UPDATE SET
                         name=excluded.name,
                         is_dir=excluded.is_dir,
                         size=excluded.size,
                         size_bytes=excluded.size_bytes,
                         parent_url=excluded.parent_url,
                         crawled=CASE WHEN nodes.is_dir=1 AND excluded.is_dir=1 THEN nodes.crawled ELSE excluded.crawled END,
                         last_seen=excluded.last_seen""",
                    prepared,
                )
            removed = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE parent_url=? AND NOT EXISTS "
                "(SELECT 1 FROM seen_urls s WHERE s.url=nodes.url)", (parent_url,)
            ).fetchone()[0]
            conn.execute(
                """WITH RECURSIVE doomed(url) AS (
                       SELECT url FROM nodes WHERE parent_url=? AND NOT EXISTS
                           (SELECT 1 FROM seen_urls s WHERE s.url=nodes.url)
                       UNION ALL
                       SELECT n.url FROM nodes n JOIN doomed d ON n.parent_url=d.url
                   )
                   DELETE FROM nodes WHERE url IN (SELECT url FROM doomed)""",
                (parent_url,),
            )
            if mark_parent_crawled:
                conn.execute(
                    "UPDATE nodes SET crawled=1, last_scanned=? WHERE url=?",
                    (now, parent_url),
                )
            conn.execute("DROP TABLE temp.seen_urls")
            conn.commit()
            return {"before": int(before), "after": len(prepared), "removed_roots": int(removed)}
        finally:
            conn.close()


def replace_all_nodes(profile_id: str, base_url: str, rows) -> None:
    """Replace a complete index using a bulk-load transaction.

    Maintaining every secondary/FTS index row-by-row is much slower than
    rebuilding those indexes once after a large imported listing is written.
    """
    now = _now_iso()
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            fts = conn.execute("SELECT value FROM meta WHERE key='fts_available'").fetchone()
            fts_enabled = bool(fts and fts[0] == "1")
            conn.execute("BEGIN IMMEDIATE")
            if fts_enabled:
                for trigger_name in ("nodes_fts_insert", "nodes_fts_delete", "nodes_fts_update"):
                    conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
                conn.execute("DELETE FROM nodes_fts")
            conn.execute("DELETE FROM nodes")
            for index_name in (
                "idx_nodes_parent", "idx_nodes_parent_kind_name", "idx_nodes_name",
                "idx_nodes_crawled_dir", "idx_nodes_last_scanned", "idx_nodes_size_bytes",
            ):
                conn.execute(f"DROP INDEX IF EXISTS {index_name}")
            batch = []
            for row in rows:
                batch.append(tuple(row[:6]) + (_parse_size_bytes(row[3]), now))
                if len(batch) < 5000:
                    continue
                conn.executemany(
                    "INSERT INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen) "
                    "VALUES(?,?,?,?,?,?,?,?)", batch,
                )
                batch.clear()
            if batch:
                conn.executemany(
                    "INSERT INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen) "
                    "VALUES(?,?,?,?,?,?,?,?)", batch,
                )
            conn.execute(
                "INSERT OR IGNORE INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen) "
                "VALUES(?,?,?,?,?,?,?,?)", (base_url, "/", 1, None, None, 1, None, now),
            )
            conn.execute("UPDATE nodes SET last_scanned=? WHERE is_dir=1", (now,))
            conn.execute("CREATE INDEX idx_nodes_parent ON nodes(parent_url, name COLLATE NOCASE)")
            conn.execute(
                "CREATE INDEX idx_nodes_parent_kind_name "
                "ON nodes(parent_url, is_dir DESC, name COLLATE NOCASE)"
            )
            conn.execute("CREATE INDEX idx_nodes_name ON nodes(name COLLATE NOCASE)")
            conn.execute("CREATE INDEX idx_nodes_crawled_dir ON nodes(is_dir, crawled)")
            conn.execute("CREATE INDEX idx_nodes_last_scanned ON nodes(is_dir, last_scanned)")
            conn.execute("CREATE INDEX idx_nodes_size_bytes ON nodes(is_dir, size_bytes)")
            if fts_enabled:
                conn.execute("INSERT INTO nodes_fts(url,name) SELECT url,name FROM nodes")
                conn.execute(
                    "CREATE TRIGGER nodes_fts_insert AFTER INSERT ON nodes BEGIN "
                    "INSERT INTO nodes_fts(url,name) VALUES(new.url,new.name); END"
                )
                conn.execute(
                    "CREATE TRIGGER nodes_fts_delete AFTER DELETE ON nodes BEGIN "
                    "DELETE FROM nodes_fts WHERE url=old.url; END"
                )
                conn.execute(
                    "CREATE TRIGGER nodes_fts_update AFTER UPDATE OF url,name ON nodes BEGIN "
                    "DELETE FROM nodes_fts WHERE url=old.url; "
                    "INSERT INTO nodes_fts(url,name) VALUES(new.url,new.name); END"
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def mark_crawled(profile_id: str, url: str, crawled: bool = True) -> None:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            conn.execute(
                "UPDATE nodes SET crawled=?, last_scanned=? WHERE url=?",
                (1 if crawled else 0, _now_iso() if crawled else None, url),
            )
            conn.commit()
        finally:
            conn.close()



def pending_dirs(profile_id: str):
    with _reader(profile_id) as conn:
        rows = conn.execute("SELECT url FROM nodes WHERE is_dir=1 AND crawled=0").fetchall()
        return [r[0] for r in rows]

def get_base_url(profile_id: str) -> str | None:
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='base_url'").fetchone()
        return row[0] if row else None


def get_node(profile_id: str, url: str):
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT url,name,is_dir,size,parent_url,crawled FROM nodes WHERE url=?", (url,)).fetchone()
        return dict(row) if row else None



def child_count(profile_id: str, parent_url: str, filter_text: str = ""):
    with _reader(profile_id) as conn:
        if filter_text:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM nodes WHERE parent_url=? AND name LIKE ? COLLATE NOCASE",
                (parent_url, f"%{filter_text}%"),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS total FROM nodes WHERE parent_url=?", (parent_url,)).fetchone()
        return int(row["total"])

def get_children(profile_id: str, parent_url: str, filter_text: str = "", sort_mode: str = "name",
                 limit: int = 500, offset: int = 0):
    order = {
        "name": "is_dir DESC, name COLLATE NOCASE ASC",
        "name_desc": "is_dir DESC, name COLLATE NOCASE DESC",
        "size": "is_dir DESC, CASE WHEN is_dir=1 THEN -1 ELSE COALESCE(CAST(size AS INTEGER), -1) END DESC, name COLLATE NOCASE",
        "type": "is_dir DESC, name COLLATE NOCASE ASC",
    }.get(sort_mode, "is_dir DESC, name COLLATE NOCASE ASC")
    params = [parent_url]
    where = "parent_url=?"
    if filter_text:
        where += " AND name LIKE ? COLLATE NOCASE"
        params.append(f"%{filter_text}%")
    with _reader(profile_id) as conn:
        rows = conn.execute(
            f"SELECT url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen,last_scanned "
            f"FROM nodes WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [max(1, min(5000, int(limit))), max(0, int(offset))],
        ).fetchall()
        return [dict(r) for r in rows]


def _fts_query(query: str) -> str:
    tokens = [token.replace('"', '""') for token in query.split() if token.strip()]
    return " AND ".join(f'"{token}"*' for token in tokens)


def search(profile_id: str, query: str, limit: int = 500, file_type: str = "all",
           min_size: int | None = None, max_size: int | None = None,
           include_files: bool = True, include_dirs: bool = True):
    q = query.strip()
    if not q:
        return []
    with _reader(profile_id) as conn:
        clauses = []
        params = []
        use_glob = "*" in q or "?" in q
        fts_available = conn.execute("SELECT value FROM meta WHERE key='fts_available'").fetchone()
        if fts_available and fts_available[0] == "1" and not use_glob:
            source = "nodes n JOIN nodes_fts f ON f.url=n.url"
            clauses.append("f.name MATCH ?")
            params.append(_fts_query(q))
        else:
            source = "nodes n"
            pattern = q.replace("%", "\\%").replace("_", "\\_")
            if use_glob:
                pattern = pattern.replace("*", "%").replace("?", "_")
            else:
                pattern = f"%{pattern}%"
            clauses.append("n.name LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(pattern)
        if include_files and not include_dirs:
            clauses.append("n.is_dir=0")
        elif include_dirs and not include_files:
            clauses.append("n.is_dir=1")
        elif not include_files and not include_dirs:
            return []
        extension_groups = {
            "archive": (".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"),
            "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"),
            "video": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
            "audio": (".mp3", ".flac", ".wav", ".ogg", ".m4a"),
            "document": (".pdf", ".txt", ".doc", ".docx", ".odt", ".md"),
            "application": (".exe", ".msi", ".deb", ".rpm", ".appimage"),
            "disk": (".iso", ".img", ".vhd", ".vhdx"),
        }
        extensions = extension_groups.get(file_type)
        if extensions:
            clauses.append("(" + " OR ".join("LOWER(n.name) LIKE ?" for _ in extensions) + ")")
            params.extend(f"%{ext}" for ext in extensions)
        if min_size is not None:
            clauses.append("n.size_bytes>=?")
            params.append(int(min_size))
        if max_size is not None:
            clauses.append("n.size_bytes<=?")
            params.append(int(max_size))
        params.append(max(1, min(5000, int(limit))))
        rows = conn.execute(
            f"WITH matches AS MATERIALIZED ("
            f"SELECT n.url,n.name,n.is_dir,n.size,n.size_bytes,n.parent_url FROM {source} "
            f"WHERE {' AND '.join(clauses)} LIMIT ?) "
            f"SELECT url,name,is_dir,size,size_bytes,parent_url FROM matches "
            f"ORDER BY is_dir DESC, name COLLATE NOCASE",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def search_all(profiles, query: str, limit_per_profile: int = 500, **filters):
    results = []
    for profile in profiles:
        migrate_json_if_needed(profile["id"], profile["base_url"])
        base = get_base_url(profile["id"]) or profile["base_url"]
        for node in search(profile["id"], query, limit_per_profile, **filters):
            if node["url"] == base:
                continue
            results.append((profile, node))
            if len(results) >= limit_per_profile:
                return results
    return results


def count_nodes(profile_id: str):
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM nodes").fetchone()
        return int(row["total"])


def count_summary(profile_id: str) -> dict:
    """Return entry, folder, and file totals with one indexed database read."""
    with _reader(profile_id) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS entries,
                      SUM(CASE WHEN is_dir=1 THEN 1 ELSE 0 END) AS folders,
                      SUM(CASE WHEN is_dir=0 THEN 1 ELSE 0 END) AS files
               FROM nodes"""
        ).fetchone()
        return {
            "entries": int(row["entries"] or 0),
            "folders": int(row["folders"] or 0),
            "files": int(row["files"] or 0),
        }


def count_dirs(profile_id: str):
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM nodes WHERE is_dir=1").fetchone()
        return int(row["total"])


def count_crawled_dirs(profile_id: str):
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM nodes WHERE is_dir=1 AND crawled=1").fetchone()
        return int(row["total"])


def count_files(profile_id: str):
    with _reader(profile_id) as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM nodes WHERE is_dir=0").fetchone()
        return int(row["total"])


def descendant_files(profile_id: str, folder_url: str):
    with _reader(profile_id) as conn:
        rows = conn.execute(
            """WITH RECURSIVE tree(url) AS (
                   SELECT url FROM nodes WHERE url=?
                   UNION ALL
                   SELECT n.url FROM nodes n JOIN tree t ON n.parent_url=t.url
               )
               SELECT url,name,parent_url FROM nodes
               WHERE is_dir=0 AND url IN (SELECT url FROM tree)
               ORDER BY parent_url, name COLLATE NOCASE""",
            (folder_url,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_all_dirs_pending(profile_id: str) -> int:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            count = conn.execute("SELECT COUNT(*) FROM nodes WHERE is_dir=1").fetchone()[0]
            conn.execute("UPDATE nodes SET crawled=0 WHERE is_dir=1")
            conn.commit()
            return int(count)
        finally:
            conn.close()


def mark_stale_dirs_pending(profile_id: str, max_age_days: int = 7) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - max(0, int(max_age_days)) * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat()
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE is_dir=1 AND (last_scanned IS NULL OR last_scanned<?)",
                (cutoff_iso,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE nodes SET crawled=0 WHERE is_dir=1 AND (last_scanned IS NULL OR last_scanned<?)",
                (cutoff_iso,),
            )
            conn.commit()
            return int(count)
        finally:
            conn.close()


def begin_snapshot(profile_id: str, mode: str, root_url: str | None = None) -> str:
    run_id = uuid.uuid4().hex
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            if root_url and mode == "folder":
                # A single-folder refresh only changes its direct listing.
                # Copying the entire cached subtree made the action appear to
                # hang before its first request on large libraries.
                scope = "parent_url=?"
                params = (root_url,)
            elif root_url and mode == "grow":
                # Grow fetches the requested folder and each immediate child
                # directory, so only those two visible levels can change.
                scope = (
                    "(parent_url=? OR parent_url IN "
                    "(SELECT url FROM nodes WHERE parent_url=? AND is_dir=1))"
                )
                params = (root_url, root_url)
            elif root_url:
                scope = "substr(url,1,length(?))=?"
                params = (root_url, root_url)
            else:
                scope = "1=1"
                params = ()
            before = conn.execute(f"SELECT COUNT(*) FROM nodes WHERE {scope}", params).fetchone()[0]
            conn.execute(
                "INSERT INTO scan_runs(id,started_at,mode,root_url,status,before_count) VALUES(?,?,?,?,?,?)",
                (run_id, _now_iso(), mode, root_url, "running", int(before)),
            )
            conn.execute(
                f"INSERT INTO snapshot_baseline(run_id,url,name,is_dir,size,size_bytes,parent_url) "
                f"SELECT ?,url,name,is_dir,size,size_bytes,parent_url FROM nodes WHERE {scope}",
                (run_id,) + params,
            )
            conn.commit()
            return run_id
        finally:
            conn.close()


def finish_snapshot(profile_id: str, run_id: str, status: str = "completed", change_limit: int = 10000) -> dict:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            run = conn.execute("SELECT * FROM scan_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return {"id": run_id, "new_count": 0, "removed_count": 0, "changed_count": 0}
            root_url = run["root_url"]
            if root_url and run["mode"] == "folder":
                current_scope = "n.parent_url=?"
                scope_params = (root_url,)
            elif root_url and run["mode"] == "grow":
                current_scope = (
                    "(n.parent_url=? OR n.parent_url IN "
                    "(SELECT d.url FROM nodes d WHERE d.parent_url=? AND d.is_dir=1))"
                )
                scope_params = (root_url, root_url)
            elif root_url:
                current_scope = "substr(n.url,1,length(?))=?"
                scope_params = (root_url, root_url)
            else:
                current_scope = "1=1"
                scope_params = ()
            new_count = conn.execute(
                f"SELECT COUNT(*) FROM nodes n WHERE {current_scope} AND NOT EXISTS "
                "(SELECT 1 FROM snapshot_baseline b WHERE b.run_id=? AND b.url=n.url)",
                scope_params + (run_id,),
            ).fetchone()[0]
            removed_count = conn.execute(
                "SELECT COUNT(*) FROM snapshot_baseline b WHERE b.run_id=? AND NOT EXISTS "
                "(SELECT 1 FROM nodes n WHERE n.url=b.url)", (run_id,),
            ).fetchone()[0]
            changed_count = conn.execute(
                """SELECT COUNT(*) FROM snapshot_baseline b JOIN nodes n ON n.url=b.url
                   WHERE b.run_id=? AND (b.name<>n.name OR b.is_dir<>n.is_dir OR
                   COALESCE(b.size_bytes,-1)<>COALESCE(n.size_bytes,-1) OR
                   COALESCE(b.parent_url,'')<>COALESCE(n.parent_url,''))""", (run_id,),
            ).fetchone()[0]
            remaining = max(0, int(change_limit))
            if remaining:
                conn.execute(
                    f"""INSERT INTO changes(run_id,change_type,url,name,is_dir,old_size,new_size)
                        SELECT ?,'new',n.url,n.name,n.is_dir,NULL,n.size FROM nodes n
                        WHERE {current_scope} AND NOT EXISTS
                        (SELECT 1 FROM snapshot_baseline b WHERE b.run_id=? AND b.url=n.url)
                        ORDER BY n.is_dir DESC,n.name COLLATE NOCASE LIMIT ?""",
                    (run_id,) + scope_params + (run_id, remaining),
                )
                remaining -= min(remaining, int(new_count))
            if remaining:
                conn.execute(
                    """INSERT INTO changes(run_id,change_type,url,name,is_dir,old_size,new_size)
                       SELECT ?,'removed',b.url,b.name,b.is_dir,b.size,NULL FROM snapshot_baseline b
                       WHERE b.run_id=? AND NOT EXISTS (SELECT 1 FROM nodes n WHERE n.url=b.url)
                       ORDER BY b.is_dir DESC,b.name COLLATE NOCASE LIMIT ?""",
                    (run_id, run_id, remaining),
                )
                remaining -= min(remaining, int(removed_count))
            if remaining:
                conn.execute(
                    """INSERT INTO changes(run_id,change_type,url,name,is_dir,old_size,new_size)
                       SELECT ?,'changed',n.url,n.name,n.is_dir,b.size,n.size
                       FROM snapshot_baseline b JOIN nodes n ON n.url=b.url
                       WHERE b.run_id=? AND (b.name<>n.name OR b.is_dir<>n.is_dir OR
                       COALESCE(b.size_bytes,-1)<>COALESCE(n.size_bytes,-1) OR
                       COALESCE(b.parent_url,'')<>COALESCE(n.parent_url,''))
                       ORDER BY n.is_dir DESC,n.name COLLATE NOCASE LIMIT ?""",
                    (run_id, run_id, remaining),
                )
            recorded = conn.execute("SELECT COUNT(*) FROM changes WHERE run_id=?", (run_id,)).fetchone()[0]
            if root_url and run["mode"] == "folder":
                after = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE parent_url=?", (root_url,)
                ).fetchone()[0]
            elif root_url and run["mode"] == "grow":
                after = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE parent_url=? OR parent_url IN "
                    "(SELECT url FROM nodes WHERE parent_url=? AND is_dir=1)",
                    (root_url, root_url),
                ).fetchone()[0]
            elif root_url:
                after = conn.execute(
                    "SELECT COUNT(*) FROM nodes WHERE substr(url,1,length(?))=?", (root_url, root_url)
                ).fetchone()[0]
            else:
                after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            conn.execute(
                """UPDATE scan_runs SET finished_at=?,status=?,after_count=?,new_count=?,
                   removed_count=?,changed_count=?,recorded_changes=? WHERE id=?""",
                (_now_iso(), status, int(after), int(new_count), int(removed_count),
                 int(changed_count), int(recorded), run_id),
            )
            conn.execute("DELETE FROM snapshot_baseline WHERE run_id=?", (run_id,))
            conn.commit()
            return {
                "id": run_id, "status": status, "mode": run["mode"], "root_url": root_url,
                "before_count": int(run["before_count"]), "after_count": int(after),
                "new_count": int(new_count), "removed_count": int(removed_count),
                "changed_count": int(changed_count), "recorded_changes": int(recorded),
            }
        finally:
            conn.close()


def list_snapshots(profile_id: str, limit: int = 50) -> list[dict]:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            rows = conn.execute(
                "SELECT * FROM scan_runs WHERE status<>'running' ORDER BY started_at DESC LIMIT ?",
                (max(1, min(500, int(limit))),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def snapshot_changes(profile_id: str, run_id: str, limit: int = 10000) -> list[dict]:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            rows = conn.execute(
                "SELECT change_type,url,name,is_dir,old_size,new_size FROM changes WHERE run_id=? "
                "ORDER BY CASE change_type WHEN 'new' THEN 0 WHEN 'changed' THEN 1 ELSE 2 END, "
                "is_dir DESC,name COLLATE NOCASE LIMIT ?",
                (run_id, max(1, min(100000, int(limit)))),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def subtree_counts(profile_id: str, root_url: str) -> dict:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            row = conn.execute(
                """WITH RECURSIVE tree(url) AS (
                       SELECT url FROM nodes WHERE url=?
                       UNION ALL SELECT n.url FROM nodes n JOIN tree t ON n.parent_url=t.url
                   )
                   SELECT COUNT(*) entries,
                          SUM(CASE WHEN is_dir=1 THEN 1 ELSE 0 END) folders,
                          SUM(CASE WHEN is_dir=0 THEN 1 ELSE 0 END) files
                   FROM nodes WHERE url IN (SELECT url FROM tree)""", (root_url,),
            ).fetchone()
            return {"entries": int(row["entries"] or 0), "folders": int(row["folders"] or 0),
                    "files": int(row["files"] or 0)}
        finally:
            conn.close()


def storage_stats(profile_id: str) -> dict:
    path = profile_cache_db_path(profile_id)
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            counts = conn.execute(
                """SELECT COUNT(*) entries,
                   SUM(CASE WHEN is_dir=1 THEN 1 ELSE 0 END) folders,
                   SUM(CASE WHEN is_dir=0 THEN 1 ELSE 0 END) files,
                   SUM(CASE WHEN is_dir=1 AND crawled=0 THEN 1 ELSE 0 END) pending,
                   MAX(last_scanned) last_scanned FROM nodes"""
            ).fetchone()
            fts = conn.execute("SELECT value FROM meta WHERE key='fts_available'").fetchone()
            snapshots = conn.execute("SELECT COUNT(*) FROM scan_runs WHERE status<>'running'").fetchone()[0]
            return {
                "entries": int(counts["entries"] or 0), "folders": int(counts["folders"] or 0),
                "files": int(counts["files"] or 0), "pending": int(counts["pending"] or 0),
                "last_scanned": counts["last_scanned"], "snapshots": int(snapshots),
                "fts": bool(fts and fts[0] == "1"),
                "bytes": os.path.getsize(path) if os.path.exists(path) else 0,
            }
        finally:
            conn.close()


def optimize_database(profile_id: str) -> dict:
    with _lock(profile_id):
        conn = _connect(profile_id)
        try:
            check = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
            conn.execute("REINDEX")
            fts = conn.execute("SELECT value FROM meta WHERE key='fts_available'").fetchone()
            if fts and fts[0] == "1":
                conn.execute("DELETE FROM nodes_fts")
                conn.execute("INSERT INTO nodes_fts(url,name) SELECT url,name FROM nodes")
            conn.commit()
            conn.execute("VACUUM")
            return {"integrity": check, "bytes": database_size(profile_id)}
        finally:
            conn.close()


def clear_database(profile_id: str, base_url: str) -> None:
    path = profile_cache_db_path(profile_id)
    with _lock(profile_id):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass
        with _SCHEMA_GUARD:
            _SCHEMA_READY.discard(profile_id)
    initialize(profile_id, base_url)


def database_exists(profile_id: str) -> bool:
    """Return whether a profile has a SQLite cache without opening it."""
    return os.path.isfile(profile_cache_db_path(profile_id))


def database_size(profile_id: str) -> int:
    path = profile_cache_db_path(profile_id)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def backup_database(profile_id: str, destination: str) -> None:
    """Create a consistent SQLite snapshot, including committed WAL changes."""
    source_path = profile_cache_db_path(profile_id)
    if not os.path.isfile(source_path):
        raise FileNotFoundError("This directory does not have a cached index yet.")
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    with _lock(profile_id):
        source = sqlite3.connect(source_path, timeout=30)
        target = sqlite3.connect(destination, timeout=30)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()


def begin_full_update(profile_id: str) -> str:
    """Checkpoint the current cache before an all-or-nothing full update."""
    checkpoint = profile_cache_checkpoint_path(profile_id)
    temporary = checkpoint + f".creating-{uuid.uuid4().hex}"
    with _lock(profile_id):
        with _CHECKPOINT_GUARD:
            if profile_id in _ACTIVE_FULL_UPDATES:
                raise RuntimeError("A protected full update is already active for this directory.")
        if os.path.exists(checkpoint):
            # A stale checkpoint means a previous process stopped before it
            # could commit. Restore it before starting a new full update.
            replace_database(profile_id, checkpoint)
            os.remove(checkpoint)
        try:
            backup_database(profile_id, temporary)
            os.replace(temporary, checkpoint)
            with _CHECKPOINT_GUARD:
                _ACTIVE_FULL_UPDATES.add(profile_id)
            return checkpoint
        finally:
            try:
                os.remove(temporary)
            except FileNotFoundError:
                pass


def commit_full_update(profile_id: str) -> None:
    """Commit a successful protected full update by removing its checkpoint."""
    checkpoint = profile_cache_checkpoint_path(profile_id)
    with _lock(profile_id):
        try:
            os.remove(checkpoint)
        except FileNotFoundError:
            pass
        finally:
            with _CHECKPOINT_GUARD:
                _ACTIVE_FULL_UPDATES.discard(profile_id)


def rollback_full_update(profile_id: str) -> bool:
    """Restore the cache saved by ``begin_full_update``."""
    checkpoint = profile_cache_checkpoint_path(profile_id)
    with _lock(profile_id):
        restored = False
        try:
            if os.path.isfile(checkpoint):
                replace_database(profile_id, checkpoint)
                os.remove(checkpoint)
                restored = True
            return restored
        finally:
            with _CHECKPOINT_GUARD:
                _ACTIVE_FULL_UPDATES.discard(profile_id)


def backup_subtree(profile_id: str, root_url: str, destination: str) -> None:
    """Create a standalone cache whose root is one folder from a larger cache."""
    os.makedirs(os.path.dirname(os.path.abspath(destination)), exist_ok=True)
    try:
        os.remove(destination)
    except FileNotFoundError:
        pass
    with _lock(profile_id):
        source = _connect(profile_id)
        target = sqlite3.connect(destination, timeout=30)
        try:
            target.executescript(
                """CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT);
                   CREATE TABLE nodes (
                       url TEXT PRIMARY KEY,name TEXT NOT NULL,is_dir INTEGER NOT NULL,size TEXT,
                       parent_url TEXT,crawled INTEGER NOT NULL DEFAULT 0,size_bytes INTEGER,
                       last_seen TEXT,last_scanned TEXT
                   );
                   CREATE INDEX idx_nodes_parent ON nodes(parent_url,name COLLATE NOCASE);
                   CREATE INDEX idx_nodes_name ON nodes(name COLLATE NOCASE);
                   CREATE INDEX idx_nodes_crawled_dir ON nodes(is_dir,crawled);"""
            )
            rows = source.execute(
                """WITH RECURSIVE tree(url) AS (
                       SELECT url FROM nodes WHERE url=?
                       UNION ALL SELECT n.url FROM nodes n JOIN tree t ON n.parent_url=t.url
                   )
                   SELECT url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen,last_scanned
                   FROM nodes WHERE url IN (SELECT url FROM tree)""", (root_url,),
            ).fetchall()
            if not rows:
                raise ValueError("The selected subtree is not present in the cache.")
            prepared = []
            for row in rows:
                values = list(row)
                if values[0] == root_url:
                    values[1] = "/"
                    values[4] = None
                prepared.append(tuple(values))
            target.executemany(
                "INSERT INTO nodes(url,name,is_dir,size,parent_url,crawled,size_bytes,last_seen,last_scanned) "
                "VALUES(?,?,?,?,?,?,?,?,?)", prepared,
            )
            target.execute("INSERT INTO meta(key,value) VALUES('base_url',?)", (root_url,))
            target.commit()
        finally:
            target.close()
            source.close()


def replace_database(profile_id: str, source_path: str) -> None:
    """Atomically replace a profile cache with a validated SQLite file."""
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    destination = profile_cache_db_path(profile_id)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    incoming = destination + f".incoming-{uuid.uuid4().hex}"
    previous = destination + f".previous-{uuid.uuid4().hex}"
    with _lock(profile_id):
        with _SCHEMA_GUARD:
            _SCHEMA_READY.discard(profile_id)
        shutil.copy2(source_path, incoming)
        had_previous = os.path.exists(destination)
        try:
            for sidecar in (destination + "-wal", destination + "-shm"):
                try:
                    os.remove(sidecar)
                except FileNotFoundError:
                    pass
            if had_previous:
                os.replace(destination, previous)
            os.replace(incoming, destination)
        except Exception:
            try:
                os.remove(incoming)
            except FileNotFoundError:
                pass
            if had_previous and os.path.exists(previous):
                os.replace(previous, destination)
            raise
        else:
            try:
                os.remove(previous)
            except FileNotFoundError:
                pass
