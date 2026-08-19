"""
Crawls a directory-listing site for one profile, exactly like the
original standalone version, but:
  - profile-scoped (own cache file, own settings)
  - tries index auto-detection first (core.index_detect) and remembers
    the result on the profile so future re-crawls skip straight to the
    fast path instead of re-probing every time
"""
import re
import time
import heapq
import itertools
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import html
from urllib.parse import urljoin, urlparse, unquote
from datetime import datetime, timezone

import requests

from core import index_detect
from core.profiles import update_profile
from core import cache
from core import crawl_state
from core.settings import load_settings

LINK_RE = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?\s?[KMGT]B?)\b", re.IGNORECASE)

BLOCK_MARKERS = ["temporarily banned", "rate limit", "slow down", "too many requests", "access denied", "blocked"]


class CrawlBlocked(Exception):
    pass


def strip_tags(s):
    return html.unescape(TAG_RE.sub("", s)).strip()


def looks_blocked(status_code, text):
    if status_code in (403, 429, 503):
        return True
    return any(marker in text[:2000].lower() for marker in BLOCK_MARKERS)


def _url_depth(url, base_url):
    """0 for the base folder itself, 1 for its direct children, etc. Used
    to crawl breadth-first (shallowest folders first) instead of whatever
    order a hash-based set happens to yield."""
    if url == base_url:
        return 0
    rel = url[len(base_url):] if url.startswith(base_url) else url
    return rel.rstrip("/").count("/") + 1


def parse_listing(page_url, page_html):
    entries = []
    seen = set()
    for m in LINK_RE.finditer(page_html):
        href, inner = m.group(1), m.group(2)
        name = strip_tags(inner)
        if not href or href.startswith("?") or href.startswith("#") or href in ("../", "..", "/"):
            continue
        full_url = urljoin(page_url, href)
        if urlparse(full_url).netloc != urlparse(page_url).netloc:
            continue
        if not full_url.startswith(page_url) or full_url == page_url or full_url in seen:
            continue
        seen.add(full_url)

        is_dir = full_url.endswith("/")
        display_name = name if name and name not in ("../", "..") else unquote(href.rstrip("/").split("/")[-1])
        if not display_name:
            continue

        window = page_html[m.end(): m.end() + 200]
        newline_pos = window.find("\n")
        next_tag_pos = window.find("<")
        cutoffs = [p for p in (newline_pos, next_tag_pos) if p != -1]
        tail = window[: min(cutoffs)] if cutoffs else window
        size_match = SIZE_RE.search(strip_tags(tail))

        entries.append({
            "name": display_name,
            "url": full_url,
            "is_dir": is_dir,
            "size": size_match.group(1) if size_match else None,
        })
    return entries


def make_session(settings):
    global_settings = load_settings()
    s = requests.Session()
    s.headers.update({"User-Agent": settings.get("user_agent") or global_settings.get("user_agent", "Mozilla/5.0 (offline-directory-browser)")})
    return s


def fetch_html_with_backoff(session, url, settings, log, stop_check):
    delay = settings["crawl_delay_seconds"]
    max_retries = settings.get("max_crawl_retries", 3)
    backoff = settings.get("crawl_retry_on_block_seconds", 60)
    attempt = 0
    while True:
        if stop_check and stop_check():
            raise CrawlBlocked("stopped by user")
        resp = session.get(url, timeout=settings.get("request_timeout_seconds") or load_settings().get("request_timeout_seconds", 20))
        if looks_blocked(resp.status_code, resp.text):
            attempt += 1
            if attempt > max_retries:
                raise CrawlBlocked(f"Blocked repeatedly at {url} (status {resp.status_code})")
            wait = backoff * attempt
            log(f"  [blocked] status={resp.status_code} at {url} -- backing off {wait}s (retry {attempt}/{max_retries})")
            for _ in range(int(wait * 10)):
                if stop_check and stop_check():
                    raise CrawlBlocked("stopped by user")
                time.sleep(0.1)
            continue
        resp.raise_for_status()
        time.sleep(delay)
        return resp.text


def crawl_folder(profile, folder_url, progress_cb=None, log=print, stop_check=None, grow_one_level=False):
    """Update one cached directory, optionally growing one level deeper.

    Unlike crawl_profile(), this performs a bounded operation: the requested
    folder is fetched and saved, and when ``grow_one_level`` is true its
    immediate child directories are fetched once as well.  It never walks the
    entire site's pending-directory queue.
    """
    settings = profile["settings"]
    base_url = profile["base_url"]
    if not base_url.endswith("/"):
        base_url += "/"
    cache.migrate_json_if_needed(profile["id"], base_url)
    cache.initialize(profile["id"], base_url)
    folder_url = folder_url if folder_url.endswith("/") else folder_url + "/"
    node = cache.get_node(profile["id"], folder_url)
    if not node or not node.get("is_dir"):
        if folder_url == base_url:
            cache.upsert_nodes(profile["id"], [(base_url, "/", 1, None, None, 0)])
            node = cache.get_node(profile["id"], folder_url)
        else:
            msg = f"Folder is not cached: {folder_url}"
            if progress_cb:
                progress_cb({"done": True, "running": False, "error": msg,
                             "mode": "grow" if grow_one_level else "folder",
                             "folder_url": folder_url, "crawled": 0, "requests": 0,
                             "queued": 0, "current": None, "elapsed": 0.0})
            return False

    started_at = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    global_settings = load_settings()
    workers = max(1, min(32, int(settings.get("crawl_concurrency", 8)),
                          int(global_settings.get("network_max_connections", 12))))
    delay = max(0.0, float(settings.get("crawl_delay_seconds", 0.25)))
    mode = "grow" if grow_one_level else "folder"
    snapshot_id = cache.begin_snapshot(profile["id"], mode, folder_url)

    def emit(p):
        if progress_cb:
            p.setdefault("mode", mode)
            p.setdefault("folder_url", folder_url)
            progress_cb(p)

    emit({"done": False, "running": True, "started_at": started_at,
          "started_iso": started_iso, "crawled": 0, "current": folder_url,
          "queued": 0, "requests": 0,
          "folders_discovered": cache.count_dirs(profile["id"]),
          "files_discovered": cache.count_files(profile["id"]),
          "elapsed": 0.0, "rate": 0.0, "workers": workers})

    index_source = profile.get("index_source") or {}
    use_json = index_source.get("mode") == "json_listing"
    json_headers = {"Accept": "application/json"} if (use_json and index_source.get("accept_header")) else None

    def fetch_one(url):
        if stop_check and stop_check():
            raise CrawlBlocked("stopped by user")
        session = make_session(settings)
        try:
            if use_json:
                entries = index_detect.fetch_json_listing(
                    session, url, settings.get("request_timeout_seconds", 20), headers=json_headers)
                if entries is None:
                    page_html = fetch_html_with_backoff(session, url, settings, log, stop_check)
                    entries = parse_listing(url, page_html)
            else:
                page_html = fetch_html_with_backoff(session, url, settings, log, stop_check)
                entries = parse_listing(url, page_html)
            return entries
        finally:
            session.close()

    targets = [folder_url]
    requests_done = 0
    crawled = 0
    child_dirs = []

    try:
        # Always fetch the requested folder. This is the single-folder action
        # and is also the first step of the one-level grow action.
        entries = fetch_one(folder_url)
        requests_done += 1
        rows = []
        for entry in entries:
            rows.append((entry["url"], entry["name"], 1 if entry["is_dir"] else 0,
                         entry["size"], folder_url, 0))
            if entry["is_dir"]:
                child_dirs.append(entry["url"])
        cache.replace_children(profile["id"], folder_url, rows)
        cache.mark_crawled(profile["id"], folder_url, True)
        crawled += 1

        if grow_one_level:
            # Fetch each immediate child directory once, bounded by the normal
            # profile/global concurrency settings. This grows the tree by one
            # visible level without scheduling grandchildren.
            child_targets = [u for u in child_dirs
                             if not bool((cache.get_node(profile["id"], u) or {}).get("crawled"))]
            completed = 0

            def one_child(url):
                return url, fetch_one(url)

            with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="grow") as executor:
                futures = {executor.submit(one_child, url): url for url in child_targets}
                while futures:
                    if stop_check and stop_check():
                        for f in futures:
                            f.cancel()
                        break
                    done_set, _ = wait(tuple(futures), timeout=0.25, return_when=FIRST_COMPLETED)
                    if not done_set:
                        elapsed = max(0.001, time.time() - started_at)
                        emit({"elapsed": elapsed, "rate": crawled / elapsed,
                              "queued": len(futures), "requests": requests_done,
                              "current": folder_url})
                        continue
                    for future in done_set:
                        url = futures.pop(future)
                        try:
                            _, child_entries = future.result()
                            child_rows = []
                            for entry in child_entries:
                                child_rows.append((entry["url"], entry["name"], 1 if entry["is_dir"] else 0,
                                                   entry["size"], url, 0))
                            cache.replace_children(profile["id"], url, child_rows)
                            cache.mark_crawled(profile["id"], url, True)
                            crawled += 1
                        except Exception as exc:
                            log(f"failed: {url} — {exc}")
                        requests_done += 1
                        completed += 1
                        elapsed = max(0.001, time.time() - started_at)
                        emit({"crawled": crawled, "requests": requests_done,
                              "queued": len(futures), "current": url,
                              "folders_discovered": cache.count_dirs(profile["id"]),
                              "files_discovered": cache.count_files(profile["id"]),
                              "elapsed": elapsed, "rate": crawled / elapsed,
                              "grow_completed": completed,
                              "grow_total": len(child_targets)})

        elapsed = max(0.001, time.time() - started_at)
        stats = {"done": True, "running": False, "crawled": crawled,
                 "requests": requests_done, "queued": 0, "current": None,
                 "folders_discovered": cache.count_dirs(profile["id"]),
                 "files_discovered": cache.count_files(profile["id"]),
                 "elapsed": elapsed, "rate": crawled / elapsed,
                 "mode": mode, "folder_url": folder_url}
        stats["changes"] = cache.finish_snapshot(profile["id"], snapshot_id, "completed")
        emit(stats)
        if grow_one_level:
            log(f"grew {folder_url} by one level — {crawled} folder(s), {requests_done} request(s)")
        else:
            log(f"updated folder {folder_url} — {crawled} folder(s), {requests_done} request(s)")
        return True
    except Exception as exc:
        elapsed = max(0.001, time.time() - started_at)
        stats = {"done": False, "running": False, "error": str(exc), "crawled": crawled,
                 "requests": requests_done, "queued": 0, "current": folder_url,
                 "folders_discovered": cache.count_dirs(profile["id"]),
                 "files_discovered": cache.count_files(profile["id"]),
                 "elapsed": elapsed, "rate": crawled / elapsed,
                 "mode": mode, "folder_url": folder_url}
        stats["changes"] = cache.finish_snapshot(profile["id"], snapshot_id, "partial")
        emit(stats)
        log(f"folder update failed: {folder_url} — {exc}")
        return False


def _save_history(profile, stats, started_iso):
    finished_iso = datetime.now(timezone.utc).isoformat()
    changes = stats.get("changes") or {}
    entry = {
        "started_at": started_iso,
        "finished_at": finished_iso,
        "duration_seconds": round(float(stats.get("elapsed", 0.0)), 1),
        "directories": int(stats.get("crawled", 0)),
        "files": int(stats.get("files_discovered", 0)),
        "requests": int(stats.get("requests", stats.get("crawled", 0))),
        "error": stats.get("error"),
        "mode": "completed" if stats.get("done") else ("stopped" if stats.get("stopped") or stats.get("error") == "stopped by user" else "failed"),
        "update_mode": stats.get("mode", "resume"),
        "new_count": int(changes.get("new_count", 0)),
        "removed_count": int(changes.get("removed_count", 0)),
        "changed_count": int(changes.get("changed_count", 0)),
    }
    history = list(profile.get("crawl_history") or [])
    history.insert(0, entry)
    update_profile(profile["id"], last_crawled=finished_iso, folders_cached=int(stats.get("crawled", 0)),
                   last_crawl_stats=entry, crawl_history=history[:20])


def crawl_profile(profile, progress_cb=None, log=print, stop_check=None, mode="resume"):
    """Crawl a profile into SQLite incrementally using a bounded worker pool.

    Directory listings are largely I/O bound, so a handful of concurrent
    requests can reduce a multi-hour serial crawl to minutes without loading
    the whole tree into memory.  The concurrency and per-request delay are
    user-configurable and can be reduced for servers that rate-limit.
    """
    settings = profile["settings"]
    base_url = profile["base_url"]
    if not base_url.endswith("/"):
        base_url += "/"
    cache.migrate_json_if_needed(profile["id"], base_url)
    cache.initialize(profile["id"], base_url)
    started_at = time.time()
    started_iso = datetime.now(timezone.utc).isoformat()
    mode = mode if mode in {"resume", "incremental", "full"} else "resume"
    snapshot_id = cache.begin_snapshot(profile["id"], mode, base_url)

    global_settings = load_settings()
    if mode == "full":
        cache.mark_all_dirs_pending(profile["id"])
    elif mode == "incremental":
        cache.mark_stale_dirs_pending(
            profile["id"], int(global_settings.get("incremental_stale_days", 7))
        )
    crawl_state.mark_started(
        profile["id"], mode, started_iso, max(1, len(cache.pending_dirs(profile["id"]))), base_url
    )
    workers = max(1, min(32, int(settings.get("crawl_concurrency", 8)), int(global_settings.get("network_max_connections", 12))))
    delay = max(0.0, float(settings.get("crawl_delay_seconds", 0.25)))

    def emit(p):
        if progress_cb:
            progress_cb(p)

    emit({"done": False, "running": True, "started_at": started_at, "mode": mode,
          "started_iso": started_iso, "crawled": 0, "current": None,
          "queued": 0, "requests": 0, "folders_discovered": cache.count_dirs(profile["id"]),
          "files_discovered": cache.count_files(profile["id"]), "elapsed": 0.0,
          "rate": 0.0, "workers": workers})

    index_source = profile.get("index_source")
    if index_source is None and settings.get("auto_detect_index", True):
        try:
            log("checking for an existing index/listing before crawling…")
            detect_session = make_session(settings)
            detected = index_detect.detect_index(detect_session, base_url,
                                                  timeout=settings.get("request_timeout_seconds", 20))
            index_source = detected if detected else {"mode": "html"}
            persisted_source = {k: v for k, v in index_source.items() if k != "nodes"}
            update_profile(profile["id"], index_source=persisted_source)
            log(f"  using mode: {index_source['mode']}"
                + (f" (from {index_source.get('source')})" if index_source.get("source") else ""))
        except Exception as exc:
            pending_after = max(1, len(cache.pending_dirs(profile["id"])))
            elapsed = max(0.001, time.time() - started_at)
            stats = {"done": False, "error": str(exc), "crawled": 0, "current": None,
                     "queued": pending_after, "requests": 0,
                     "folders_discovered": cache.count_dirs(profile["id"]),
                     "files_discovered": cache.count_files(profile["id"]), "elapsed": elapsed,
                     "rate": 0.0, "workers": workers, "mode": mode}
            stats["changes"] = cache.finish_snapshot(profile["id"], snapshot_id, "partial")
            crawl_state.mark_resumable(profile["id"], pending_after, 0, str(exc))
            emit(stats)
            _save_history(profile, stats, started_iso)
            log(f"crawl setup failed: {exc}")
            return False

    if index_source and index_source.get("mode") == "full_tree":
        nodes = index_source.get("nodes", {})
        rows = ((url, node.get("name", "/"), 1 if node.get("is_dir") else 0,
                 node.get("size"), cache._parent_url(url, base_url),
                 1 if node.get("crawled", node.get("is_dir")) else 0)
                for url, node in nodes.items())
        cache.replace_all_nodes(profile["id"], base_url, rows)
        crawled_dirs = cache.count_dirs(profile["id"])
        elapsed = max(0.001, time.time() - started_at)
        stats = {"done": True, "crawled": crawled_dirs, "current": None, "queued": 0,
                 "requests": 0, "folders_discovered": crawled_dirs,
                 "files_discovered": cache.count_files(profile["id"]),
                 "elapsed": elapsed, "rate": 0.0, "workers": workers, "mode": mode}
        changes = cache.finish_snapshot(profile["id"], snapshot_id, "completed")
        stats["changes"] = changes
        emit(stats)
        crawl_state.mark_completed(profile["id"], crawled_dirs)
        _save_history(profile, stats, started_iso)
        log(f"done — full tree pulled directly, {crawled_dirs} folders, "
            f"{cache.count_files(profile['id'])} files, no crawling needed.")
        return True

    use_json = bool(index_source and index_source.get("mode") == "json_listing")
    json_headers = {"Accept": "application/json"} if (use_json and index_source.get("accept_header")) else None

    pending_counter = itertools.count()
    pending_heap = []  # heap of (depth, insertion_order, url) — always pops the shallowest folder

    def push_pending(url):
        heapq.heappush(pending_heap, (_url_depth(url, base_url), next(pending_counter), url))

    initial = set(cache.pending_dirs(profile["id"]))
    if not cache.get_node(profile["id"], base_url):
        cache.upsert_nodes(profile["id"], [(base_url, "/", 1, None, None, 0)])
        initial.add(base_url)
    if not initial:
        initial.add(base_url)
    for u in initial:
        push_pending(u)

    count = 0
    requests_done = 0
    last_counts = (None, None)
    failed_this_run = set()
    last_state_save = 0.0
    crawl_state.mark_started(profile["id"], mode, started_iso, len(initial), base_url)

    def crawl_one(current):
        if stop_check and stop_check():
            return current, None, "stopped by user"
        session = make_session(settings)
        try:
            if use_json:
                entries = index_detect.fetch_json_listing(
                    session, current, settings.get("request_timeout_seconds", 20), headers=json_headers)
                if delay:
                    time.sleep(delay)
                if entries is None:
                    page_html = fetch_html_with_backoff(session, current, settings, log, stop_check)
                    entries = parse_listing(current, page_html)
            else:
                page_html = fetch_html_with_backoff(session, current, settings, log, stop_check)
                entries = parse_listing(current, page_html)
            return current, entries, None
        except CrawlBlocked as e:
            return current, None, str(e)
        except Exception as e:
            return current, None, str(e)
        finally:
            session.close()

    # Maintain a bounded number of in-flight directory requests. New folders
    # discovered by completed requests are immediately fed back into the pool.
    futures = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="crawl") as executor:
        while pending_heap or futures:
            if stop_check and stop_check():
                for future in futures:
                    future.cancel()
                break

            while pending_heap and len(futures) < workers:
                _, _, current = heapq.heappop(pending_heap)
                if current in failed_this_run:
                    continue
                node = cache.get_node(profile["id"], current)
                if not node or not node["is_dir"] or node.get("crawled"):
                    continue
                futures[executor.submit(crawl_one, current)] = current

            if not futures:
                continue

            done_set, _ = wait(tuple(futures), timeout=0.5, return_when=FIRST_COMPLETED)
            if not done_set:
                # Nothing finished within the timeout — still emit a light
                # heartbeat (wall-clock only, no DB queries) so the Activity
                # page keeps moving instead of appearing frozen between
                # folder completions (e.g. during a slow crawl_delay or a
                # backoff wait).
                elapsed = max(0.001, time.time() - started_at)
                emit({"elapsed": elapsed, "rate": (count / elapsed) if elapsed > 0 else 0.0,
                      "queued": len(pending_heap) + len(futures)})
                continue
            for future in done_set:
                current = futures.pop(future)
                _, entries, error = future.result()
                requests_done += 1

                if error:
                    if error == "stopped by user":
                        continue
                    log(f"failed: {current} — {error}")
                    # The node remains crawled=0 in SQLite, but is not retried
                    # endlessly in this run. A later Resume starts here again.
                    failed_this_run.add(current)
                    continue

                rows = []
                for entry in entries:
                    u = entry["url"]
                    rows.append((u, entry["name"], 1 if entry["is_dir"] else 0,
                                 entry["size"], current, 0))
                    if entry["is_dir"]:
                        push_pending(u)
                cache.replace_children(profile["id"], current, rows)
                cache.mark_crawled(profile["id"], current, True)
                count += 1

                found_dirs = sum(1 for e in entries if e["is_dir"])
                found_files = len(entries) - found_dirs
                log(f"crawled: {current} — {found_dirs} folder(s), {found_files} file(s) found")

                # Database COUNTs are noticeably more expensive than the HTTP
                # work at high concurrency, so only refresh them when a request
                # completes, and reuse them for the emitted state below.
                discovered = cache.count_dirs(profile["id"])
                files = cache.count_files(profile["id"])
                last_counts = (discovered, files)
                elapsed = max(0.001, time.time() - started_at)
                emit({"done": False, "crawled": count, "current": current,
                      "queued": len(pending_heap) + len(futures), "requests": requests_done,
                      "folders_discovered": discovered, "files_discovered": files,
                      "elapsed": elapsed, "rate": count / elapsed,
                      "workers": workers, "mode": mode})
                if time.time() - last_state_save >= 2.0:
                    crawl_state.mark_progress(
                        profile["id"], current, len(pending_heap) + len(futures) + len(failed_this_run), count
                    )
                    last_state_save = time.time()

    stopped = bool(stop_check and stop_check())
    elapsed = max(0.001, time.time() - started_at)
    discovered, files = last_counts
    if discovered is None:
        discovered = cache.count_dirs(profile["id"])
        files = cache.count_files(profile["id"])
    pending_after = len(cache.pending_dirs(profile["id"]))
    stats = {"done": (not stopped and pending_after == 0), "stopped": stopped,
             "crawled": count, "current": None, "queued": pending_after,
             "requests": requests_done, "folders_discovered": discovered,
             "files_discovered": files, "elapsed": elapsed,
             "rate": count / elapsed, "workers": workers, "mode": mode}
    if pending_after and not stopped:
        stats["error"] = "some directories failed and remain queued"
    snapshot_status = "completed" if stats["done"] else ("stopped" if stopped else "partial")
    stats["changes"] = cache.finish_snapshot(profile["id"], snapshot_id, snapshot_status)
    if stats["done"]:
        crawl_state.mark_completed(profile["id"], count)
    else:
        crawl_state.mark_resumable(profile["id"], pending_after, count, stats.get("error"))
    emit(stats)
    _save_history(profile, stats, started_iso)
    log(("stopped" if stopped else "done") + f". {count} directories crawled this run with up to {workers} concurrent requests "
        f"({discovered} folders, {files} files discovered in total).")
    return bool(stats["done"])
