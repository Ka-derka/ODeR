"""Application paths.

Runtime data remains beside the executable in portable mode, while bundled
read-only assets (such as the icon) are resolved from PyInstaller's extracted
resource directory when running as a one-file build.
"""
import os
import sys


def app_root():
    """Directory containing the running exe (frozen) or source tree (dev)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_root():
    """Directory containing read-only bundled resources."""
    return getattr(sys, "_MEIPASS", app_root())


def resource_path(filename):
    return os.path.join(resource_root(), filename)


def data_dir():
    d = os.path.join(app_root(), "data")
    os.makedirs(d, exist_ok=True)
    return d


def profiles_index_path():
    return os.path.join(data_dir(), "profiles.json")


def queue_path():
    return os.path.join(data_dir(), "queue.json")


def favorites_path():
    return os.path.join(data_dir(), "favorites.json")


def package_history_path():
    return os.path.join(data_dir(), "package_history.json")


def profile_dir(profile_id):
    d = os.path.join(data_dir(), "profiles", profile_id)
    os.makedirs(d, exist_ok=True)
    return d


def profile_cache_path(profile_id):
    return os.path.join(profile_dir(profile_id), "cache.json")


def downloads_dir(profile_name):
    safe = "".join(c for c in profile_name if c not in '<>:"/\\|?*').strip() or "profile"
    d = os.path.join(data_dir(), "downloads", safe)
    os.makedirs(d, exist_ok=True)
    return d


def profile_cache_db_path(profile_id):
    return os.path.join(profile_dir(profile_id), "cache.sqlite3")


def profile_crawl_state_path(profile_id):
    return os.path.join(profile_dir(profile_id), "crawl_state.json")
