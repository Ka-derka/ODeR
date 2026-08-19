"""
Central application logging.

Every background worker in this app (crawler, downloader, dispatcher) was
already built around a `log(message)` callback — this module gives that
callback somewhere real to go:

  - a rotating log file on disk (data/logs/app.log, a few MB x 5 backups)
  - a small thread-safe in-memory ring buffer that the GUI's Logs page
    polls from (same polling pattern the rest of the app already uses for
    crawl/queue status, so no cross-thread Qt signal plumbing is needed)

Usage elsewhere in the app is just: `from core import applog` and pass
`log=applog.log` wherever a `log=` callback is expected, or call
`applog.log(...)` directly for one-off events (site added, crawl started,
tray actions, etc).
"""
import logging
import logging.handlers
import os
import threading
from collections import deque

from core.paths import data_dir

_MAX_MEMORY_LINES = 5000

_buffer = deque(maxlen=_MAX_MEMORY_LINES)
_buffer_lock = threading.Lock()
_seq = 0

_logger = None
_logger_lock = threading.Lock()


class _MemoryHandler(logging.Handler):
    """Feeds formatted log lines into the in-memory ring buffer the GUI reads."""

    def emit(self, record):
        global _seq
        try:
            line = self.format(record)
        except Exception:
            return
        with _buffer_lock:
            _seq += 1
            _buffer.append((_seq, line))


def log_dir():
    d = os.path.join(data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def log_file_path():
    return os.path.join(log_dir(), "app.log")


def setup_logging(level=logging.INFO):
    """Idempotent — safe to call from multiple modules/threads at import time."""
    global _logger
    with _logger_lock:
        if _logger is not None:
            return _logger

        logger = logging.getLogger("odb")
        logger.setLevel(level)
        logger.propagate = False

        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path(), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

        mem_handler = _MemoryHandler()
        mem_handler.setFormatter(fmt)
        logger.addHandler(mem_handler)

        _logger = logger
        return logger


def log(message, level="info"):
    """Drop-in replacement for the `log=print` callbacks used throughout
    core/crawl.py and core/downloader.py, plus the general-purpose call for
    one-off events elsewhere in the app."""
    logger = setup_logging()
    getattr(logger, level, logger.info)(str(message))


def get_new_lines(since_seq=0):
    """Every buffered line after `since_seq`, plus the latest seq number
    (pass that back in next time to get only what's new)."""
    with _buffer_lock:
        lines = [(s, l) for s, l in _buffer if s > since_seq]
        latest = _buffer[-1][0] if _buffer else since_seq
    return lines, latest


def get_all_lines():
    with _buffer_lock:
        return list(_buffer)


def clear_memory_buffer():
    """Clears only the in-memory buffer the GUI reads from — the log file
    on disk is untouched."""
    with _buffer_lock:
        _buffer.clear()
