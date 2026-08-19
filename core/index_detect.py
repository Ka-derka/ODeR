"""
Before crawling a site folder-by-folder, check whether it already exposes
a machine-readable listing we can use instead — much cheaper than scraping
HTML page by page.

Two things are checked, cheaply (a handful of requests total):

1. A **full recursive tree dump** at the base URL (some directory-listing
   generators — h5ai, some custom setups — expose one JSON file describing
   the whole tree). If found, the entire cache can be built from a single
   request, no crawling needed at all.

2. A **per-directory JSON listing** (nginx `autoindex_format json;`, and
   similar). This doesn't cut down the number of requests during a crawl
   (still one request per folder, same delay/backoff), but it's far more
   reliable than scraping HTML and gives exact sizes. If detected, the
   crawler uses this instead of HTML parsing for every folder.

3. A `sitemap.xml`, which — if present — often lists every file URL on
   the site in one or two requests, letting us skip crawling almost
   entirely (directory structure is inferred from the URL paths).

Returns None if nothing usable is found, so the caller falls back to a
normal HTML crawl.
"""
import json
import re
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

CANDIDATE_INDEX_FILES = ["index.json", "files.json", "listing.json", "directory.json", ".index.json"]


def _try_get(session, url, timeout, headers=None):
    try:
        resp = session.get(url, timeout=timeout, headers=headers or {})
        if resp.status_code == 200:
            return resp
    except Exception:
        pass
    return None


def _looks_like_json_entries(data):
    """True if `data` is a list of dict entries with recognizable name/type keys."""
    if not isinstance(data, list) or not data:
        return False
    sample = data[0]
    if not isinstance(sample, dict):
        return False
    name_keys = {"name", "filename", "file"}
    return bool(name_keys & set(k.lower() for k in sample.keys()))


def _entry_is_dir(entry):
    t = str(entry.get("type", entry.get("kind", ""))).lower()
    if t in ("directory", "dir", "folder"):
        return True
    if t in ("file",):
        return False
    name = entry.get("name") or entry.get("filename") or entry.get("file") or ""
    return name.endswith("/")


def _entry_name(entry):
    name = entry.get("name") or entry.get("filename") or entry.get("file") or ""
    return name.rstrip("/")


def _entry_size(entry):
    for key in ("size", "filesize", "bytes", "length"):
        if key in entry and entry[key] not in (None, ""):
            v = entry[key]
            return _human_size(int(v)) if isinstance(v, (int, float)) or str(v).isdigit() else str(v)
    return None


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def fetch_json_listing(session, dir_url, timeout, headers=None):
    """Fetch one directory's contents via JSON (used when json_autoindex mode
    was detected). Returns a list of entries like parse_listing() in crawl.py,
    or None if this directory didn't return usable JSON."""
    resp = _try_get(session, dir_url, timeout, headers=headers)
    if resp is None:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not _looks_like_json_entries(data):
        return None
    entries = []
    for e in data:
        name = _entry_name(e)
        if not name or name in ("..", "."):
            continue
        is_dir = _entry_is_dir(e)
        href = name + ("/" if is_dir else "")
        entries.append({
            "name": name + ("/" if is_dir else ""),
            "url": urljoin(dir_url, href),
            "is_dir": is_dir,
            "size": None if is_dir else _entry_size(e),
        })
    return entries


def _build_full_tree_from_json(base_url, data):
    """Handles a single JSON document that recursively describes the whole
    tree, e.g. {"name":"root","type":"directory","children":[...]}"""
    nodes = {}

    def walk(node, url):
        is_dir = str(node.get("type", "")).lower() in ("directory", "dir", "folder") or "children" in node
        children = node.get("children") or []
        child_urls = []
        for child in children:
            cname = _entry_name(child)
            if not cname:
                continue
            c_is_dir = str(child.get("type", "")).lower() in ("directory", "dir", "folder") or "children" in child
            c_url = urljoin(url, cname + ("/" if c_is_dir else ""))
            child_urls.append(c_url)
            nodes[c_url] = {
                "name": cname + ("/" if c_is_dir else ""),
                "is_dir": c_is_dir,
                "size": None if c_is_dir else _entry_size(child),
                "children": [] if c_is_dir else None,
                "crawled": True,
            }
            if c_is_dir:
                walk(child, c_url)
        nodes[url]["children"] = child_urls

    nodes[base_url] = {"name": "/", "is_dir": True, "size": None, "children": [], "crawled": True}
    walk(data, base_url)
    return nodes


def _try_full_tree_dump(session, base_url, timeout):
    for fname in CANDIDATE_INDEX_FILES:
        url = urljoin(base_url, fname)
        resp = _try_get(session, url, timeout)
        if resp is None:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        if isinstance(data, dict) and ("children" in data or str(data.get("type", "")).lower() in ("directory", "dir")):
            nodes = _build_full_tree_from_json(base_url, data)
            return {"mode": "full_tree", "source": url, "nodes": nodes}
        if _looks_like_json_entries(data):
            # a flat listing of just the base folder, not a full recursive dump —
            # useful as a per-directory json listing hint, not a full-tree skip
            return {"mode": "json_listing", "source": url}
    return None


def _try_per_dir_json(session, base_url, timeout):
    # nginx autoindex_format json; and similar respond to a normal GET
    # with an Accept: application/json header
    resp = _try_get(session, base_url, timeout, headers={"Accept": "application/json"})
    if resp is not None:
        try:
            data = resp.json()
            if _looks_like_json_entries(data):
                return {"mode": "json_listing", "source": base_url, "accept_header": True}
        except Exception:
            pass
    return None


def _try_sitemap(session, base_url, timeout):
    parsed = urlparse(base_url)
    candidates = [urljoin(base_url, "sitemap.xml"), f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
    seen = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        resp = _try_get(session, url, timeout)
        if resp is None:
            continue
        try:
            root = ET.fromstring(resp.content)
        except Exception:
            continue
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text for el in root.findall(".//sm:loc", ns)] or \
               [el.text for el in root.findall(".//loc")]
        urls_under_base = [u for u in locs if u and u.startswith(base_url)]
        if not urls_under_base:
            continue
        nodes = _build_tree_from_flat_urls(base_url, urls_under_base)
        return {"mode": "full_tree", "source": url, "nodes": nodes}
    return None


def _build_tree_from_flat_urls(base_url, urls):
    """Synthesize a directory tree from a flat list of file URLs (from a
    sitemap). Directories are inferred from URL path segments. Note: this
    can only know about folders that contain at least one listed file —
    genuinely empty folders won't appear."""
    nodes = {base_url: {"name": "/", "is_dir": True, "size": None, "children": [], "crawled": True}}

    def ensure_dir(url):
        if url not in nodes:
            name = url.rstrip("/").split("/")[-1] + "/"
            nodes[url] = {"name": name, "is_dir": True, "size": None, "children": [], "crawled": True}
        return nodes[url]

    for full_url in urls:
        rel = full_url[len(base_url):]
        parts = [p for p in rel.split("/") if p]
        if not parts:
            continue
        acc = base_url
        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            parent = acc
            acc = acc + part + ("" if is_last else "/")
            if is_last:
                nodes[acc] = {"name": part, "is_dir": False, "size": None, "children": None, "crawled": False}
            else:
                ensure_dir(acc + "/" if not acc.endswith("/") else acc)
                acc = acc if acc.endswith("/") else acc + "/"
            if acc not in nodes[parent]["children"]:
                nodes[parent]["children"].append(acc)
    return nodes


def detect_index(session, base_url, timeout=15):
    """Try each detection strategy in order of usefulness (skip crawling
    entirely > skip HTML parsing) and return the first hit, or None."""
    for fn in (_try_full_tree_dump, _try_sitemap, _try_per_dir_json):
        try:
            result = fn(session, base_url, timeout)
        except Exception:
            result = None
        if result:
            return result
    return None
