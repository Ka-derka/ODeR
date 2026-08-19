"""Fail a release build when user-visible version metadata disagrees."""
from pathlib import Path
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.version import APP_VERSION  # noqa: E402


CANONICAL_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def verify_release_metadata(root=ROOT):
    root = Path(root)
    errors = []
    if not CANONICAL_VERSION.fullmatch(APP_VERSION):
        errors.append(f"core/version.py must use MAJOR.MINOR.PATCH, not {APP_VERSION!r}")

    installer = (root / "installer.iss").read_text(encoding="utf-8")
    match = re.search(r'^#define MyAppVersion "([^"]+)"', installer, re.MULTILINE)
    if not match or match.group(1) != APP_VERSION:
        errors.append("installer.iss does not match core/version.py")

    readme = (root / "README.md").read_text(encoding="utf-8")
    if f"Current version: **{APP_VERSION}**" not in readme:
        errors.append("README.md does not identify the current application version")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(APP_VERSION)}(?:\s|—)", changelog, re.MULTILINE):
        errors.append("CHANGELOG.md has no section for the current application version")

    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if ref_type == "tag" and ref_name != f"v{APP_VERSION}":
        errors.append(
            f"Git tag {ref_name!r} does not match the required release tag v{APP_VERSION}"
        )

    if errors:
        raise RuntimeError("Release metadata check failed:\n- " + "\n- ".join(errors))
    return APP_VERSION


if __name__ == "__main__":
    try:
        version = verify_release_metadata()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
    print(f"Release metadata verified for ODeR {version}.")
