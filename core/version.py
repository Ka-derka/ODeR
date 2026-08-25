"""Independent release versions for ODeR and ODeR Creator."""
from __future__ import annotations

import re


APP_NAME = "ODeR"
CREATOR_NAME = "ODeR Creator"
APP_VERSION = "1.1.0-alpha.3"
CREATOR_VERSION = "2026.0.2a"


def windows_version_tuple(value=APP_VERSION):
    """Return the numeric four-part version required by Windows resources."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or ""))
    if not match:
        raise ValueError(f"Version {value!r} does not begin with three numeric parts.")
    return tuple(int(part) for part in match.groups()) + (0,)
