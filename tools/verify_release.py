"""Fail a release build when user-visible version metadata disagrees."""
from pathlib import Path
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.version import APP_VERSION, CREATOR_VERSION  # noqa: E402


CANONICAL_VERSION = re.compile(
    r"^(?:\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?|\d{4}\.\d+\.\d+(?:a|b|rc)\d*)$",
    re.IGNORECASE,
)


def verify_release_metadata(root=ROOT):
    root = Path(root)
    errors = []
    if not CANONICAL_VERSION.fullmatch(APP_VERSION):
        errors.append(
            "core/version.py must use canonical SemVer or ODeR calendar versioning "
            f"prerelease suffix, not {APP_VERSION!r}"
        )
    if not CANONICAL_VERSION.fullmatch(CREATOR_VERSION):
        errors.append(
            "core/version.py must use canonical Creator calendar versioning, "
            f"not {CREATOR_VERSION!r}"
        )

    installers = {
        "installer.iss": APP_VERSION,
        "creator_installer.iss": CREATOR_VERSION,
    }
    for filename, expected_version in installers.items():
        path = root / filename
        if not path.exists():
            if filename == "creator_installer.iss":
                continue
            errors.append(f"{filename} is missing")
            continue
        installer = path.read_text(encoding="utf-8")
        match = re.search(r'^#define MyAppVersion "([^"]+)"', installer, re.MULTILINE)
        if not match or match.group(1) != expected_version:
            errors.append(f"{filename} does not match its version in core/version.py")

    readme = (root / "README.md").read_text(encoding="utf-8")
    if f"Current version: **{APP_VERSION}**" not in readme:
        errors.append("README.md does not identify the current application version")
    if f"Current Creator version: **{CREATOR_VERSION}**" not in readme:
        errors.append("README.md does not identify the current Creator version")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"^## {re.escape(APP_VERSION)}(?:\s|—)", changelog, re.MULTILINE):
        errors.append("CHANGELOG.md has no section for the current application version")

    windows_spec = (root / "build.spec").read_text(encoding="utf-8")
    windows_script = (root / "build_windows.ps1").read_text(encoding="utf-8")
    if "name='ODeR'" not in windows_spec or "ODeR-Portable" in windows_spec:
        errors.append("build.spec must produce the private ODeR installer payload")
    if "ODeR-Portable" in windows_script:
        errors.append("build_windows.ps1 must not publish portable release artifacts")
    for filename in ("build_macos.spec", "creator_macos.spec", "build_macos.sh"):
        if not (root / filename).is_file():
            errors.append(f"{filename} is missing")

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
