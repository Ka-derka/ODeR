"""Reject macOS release bundles that cannot run on the advertised target."""
from __future__ import annotations

import argparse
import plistlib
from pathlib import Path
import subprocess
import sys


MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in str(value).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def command(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout


def is_macho(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    if magic not in MACHO_MAGICS:
        return False
    return "Mach-O" in command("file", "-b", str(path))


def deployment_targets(path: Path, architecture: str) -> list[str]:
    output = command("otool", "-arch", architecture, "-l", str(path))
    targets: list[str] = []
    load_command = ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("cmd "):
            load_command = stripped.split(maxsplit=1)[1]
        elif load_command == "LC_BUILD_VERSION" and stripped.startswith("minos "):
            targets.append(stripped.split(maxsplit=1)[1])
        elif load_command == "LC_VERSION_MIN_MACOSX" and stripped.startswith("version "):
            targets.append(stripped.split(maxsplit=1)[1])
    return targets


def verify_bundle(bundle: Path, architecture: str, maximum: str) -> tuple[int, str]:
    plist_path = bundle / "Contents" / "Info.plist"
    if not plist_path.is_file():
        raise ValueError(f"{bundle}: missing Contents/Info.plist")
    with plist_path.open("rb") as handle:
        plist = plistlib.load(handle)
    declared = str(plist.get("LSMinimumSystemVersion") or "")
    if declared != maximum:
        raise ValueError(
            f"{bundle}: LSMinimumSystemVersion is {declared or 'missing'}, expected {maximum}"
        )

    maximum_tuple = version_tuple(maximum)
    checked = 0
    highest = "0.0"
    for path in (candidate for candidate in bundle.rglob("*") if candidate.is_file()):
        if not is_macho(path):
            continue
        architectures = set(command("lipo", "-archs", str(path)).split())
        if architecture not in architectures:
            raise ValueError(f"{path}: missing required {architecture} slice ({sorted(architectures)})")
        targets = deployment_targets(path, architecture)
        if not targets:
            raise ValueError(f"{path}: has no readable macOS deployment target")
        for target in targets:
            if version_tuple(target) > maximum_tuple:
                raise ValueError(
                    f"{path}: requires macOS {target}, newer than advertised {maximum}"
                )
            if version_tuple(target) > version_tuple(highest):
                highest = target
        checked += 1
    if not checked:
        raise ValueError(f"{bundle}: no Mach-O binaries were found")
    return checked, highest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundles", nargs="+", type=Path)
    parser.add_argument("--architecture", default="x86_64")
    parser.add_argument("--maximum-deployment-target", default="12.0")
    args = parser.parse_args()
    try:
        for bundle in args.bundles:
            count, highest = verify_bundle(
                bundle.resolve(), args.architecture, args.maximum_deployment_target
            )
            print(
                f"{bundle}: {count} Mach-O files include {args.architecture}; "
                f"highest deployment target is macOS {highest}"
            )
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"macOS bundle verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
