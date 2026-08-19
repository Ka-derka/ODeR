"""Global application settings."""
import os
from core.paths import data_dir
from core.persistence import load_json, save_json
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
    "last_update_attempt_at": None,
    "last_update_check_at": None,
    "last_update_error": None,
    "skipped_update_version": None,
}


def load_settings():
    data = load_json(settings_path(), {}, dict)
    out = dict(DEFAULTS)
    out.update(data)
    custom = dict(DEFAULTS["custom_theme"])
    if isinstance(data.get("custom_theme"), dict):
        custom.update(data["custom_theme"])
    out["custom_theme"] = custom
    return out


def save_settings(data):
    settings = load_settings()
    settings.update(data or {})
    p = settings_path()
    save_json(p, settings)
    return settings
