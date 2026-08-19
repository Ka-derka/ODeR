"""Global application settings."""
import json, os
from core.paths import data_dir
from core.version import APP_VERSION


def settings_path():
    return os.path.join(data_dir(), "settings.json")


def downloads_root():
    return os.path.join(data_dir(), "downloads")

DEFAULTS = {
    "download_dir": downloads_root(),
    "download_concurrency": 2,
    "download_start_delay": 0.5,
    "skip_existing_downloads": True,
    "request_timeout_seconds": 20,
    "network_max_connections": 12,
    "network_backoff_seconds": 60,
    "user_agent": f"ODeR/{APP_VERSION}",
    "open_external_downloads_in_browser": True,
    "follow_redirects": True,
    "theme": "dark",
    "custom_theme": {"background":"#0F1115","panel":"#151922","card":"#1B202A","text":"#F2F4F7","muted":"#98A2B3","accent":"#7C5CFF","button":"#202632","button_hover":"#2A3240","button_pressed":"#343E4F","button_text":"#F2F4F7","button_border":"#343C4A"},
    "sidebar_collapsed": False,
    "lazy_directory_browsing": True,
    "startup_check_directories": True,
    "startup_initialize_caches": True,
    "confirm_full_updates": True,
    "resume_crawls_at_startup": False,
    "incremental_stale_days": 7,
    "notify_directory_changes": True,
    "browser_page_size": 500,
    "automatic_update_checks": True,
    "update_channel": "stable",
    "last_update_check_at": None,
    "skipped_update_version": None,
}


def load_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        out.update(data)
    return out


def save_settings(data):
    settings = load_settings()
    settings.update(data or {})
    p = settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, p)
    return settings
