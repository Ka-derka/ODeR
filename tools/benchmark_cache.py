"""Repeatable synthetic benchmark for ODeR's large-cache hot paths."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import cache  # noqa: E402


def timed(label, operation):
    started = time.perf_counter()
    result = operation()
    elapsed = time.perf_counter() - started
    print(f"{label:<24} {elapsed:8.3f}s")
    return result, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entries", type=int, default=100_000)
    args = parser.parse_args()
    entries = max(1, args.entries)
    profile_id = "synthetic-benchmark"
    base_url = "https://benchmark.invalid/"

    with tempfile.TemporaryDirectory(prefix="oder-benchmark-") as temp_dir:
        original_path = cache.profile_cache_db_path
        cache.profile_cache_db_path = lambda _profile_id: os.path.join(temp_dir, "cache.sqlite3")
        cache._SCHEMA_READY.discard(profile_id)
        try:
            timed("initialize", lambda: cache.initialize(profile_id, base_url))
            folder_count = min(1_000, max(1, entries // 100))
            def synthetic_rows():
                for number in range(entries):
                    is_dir = number < folder_count
                    if is_dir:
                        name = f"folder-{number:08d}"
                        url = base_url + name + "/"
                        parent_url = base_url
                    else:
                        name = f"file-{number:08d}.bin"
                        parent_url = base_url + f"folder-{number % folder_count:08d}/"
                        url = parent_url + name
                    yield (url, name, int(is_dir), None if is_dir else "1 MB",
                           parent_url, int(is_dir))

            timed(
                "bulk replace entries",
                lambda: cache.replace_all_nodes(profile_id, base_url, synthetic_rows()),
            )

            summary, _ = timed("aggregate counts", lambda: cache.count_summary(profile_id))
            page, _ = timed(
                "browse 500-row page",
                lambda: cache.get_children(profile_id, base_url, limit=500),
            )
            matches, _ = timed("search cache", lambda: cache.search(profile_id, "file", limit=500))
            run_id, _ = timed(
                "folder snapshot start",
                lambda: cache.begin_snapshot(profile_id, "folder", base_url),
            )
            timed("folder snapshot finish", lambda: cache.finish_snapshot(profile_id, run_id))
            print(
                f"verified: {summary['entries']:,} rows, "
                f"{len(page):,}-row page, {len(matches):,} search results"
            )
        finally:
            cache._SCHEMA_READY.discard(profile_id)
            cache.profile_cache_db_path = original_path


if __name__ == "__main__":
    main()
