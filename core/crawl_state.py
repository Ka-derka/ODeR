"""Small restart-visible state record for resumable crawls."""
from datetime import datetime, timezone

from core.paths import profile_crawl_state_path
from core.state_schema import load_document, save_document


def _now():
    return datetime.now(timezone.utc).isoformat()


def load(profile_id):
    return load_document(profile_crawl_state_path(profile_id), "crawl-state", None, dict)


def save(profile_id, **fields):
    value = load(profile_id) or {}
    value.update(fields)
    value["profile_id"] = profile_id
    value["updated_at"] = _now()
    path = profile_crawl_state_path(profile_id)
    save_document(path, "crawl-state", value, dict)
    return value


def mark_started(profile_id, mode, started_at, pending_count, root_url=None):
    return save(profile_id, status="running", mode=mode, started_at=started_at,
                pending_count=int(pending_count), current_url=None, root_url=root_url,
                completed_count=0, error=None)


def mark_progress(profile_id, current_url, pending_count, completed_count):
    return save(profile_id, status="running", current_url=current_url,
                pending_count=int(pending_count), completed_count=int(completed_count))


def mark_resumable(profile_id, pending_count, completed_count, error=None):
    return save(profile_id, status="resumable", current_url=None,
                pending_count=int(pending_count), completed_count=int(completed_count), error=error)


def mark_completed(profile_id, completed_count):
    return save(profile_id, status="completed", current_url=None, pending_count=0,
                completed_count=int(completed_count), finished_at=_now(), error=None)


def resumable(profiles):
    result = []
    for profile in profiles:
        state = load(profile.get("id"))
        # A process terminated mid-crawl leaves the last durable state as
        # ``running``. On the next launch it is as resumable as an orderly stop.
        if state and state.get("status") in {"running", "resumable"}:
            result.append((profile, state))
    return result
