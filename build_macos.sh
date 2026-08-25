#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script must be run on macOS." >&2
    exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "The release build must run on an Intel Mac (x86_64), or in an x86_64 CI runner." >&2
    exit 1
fi

host_python="${ODER_BUILD_PYTHON:-python3}"
"$host_python" -c 'import platform, sys; assert sys.version_info[:2] == (3, 10), "The Intel macOS build requires Python 3.10"; assert platform.machine() == "x86_64", "Python must be an x86_64 build"'

export MACOSX_DEPLOYMENT_TARGET=12.0
"$host_python" -m venv --clear .macos-build-venv
build_python="$project_root/.macos-build-venv/bin/python"
"$build_python" -m pip install --upgrade pip
"$build_python" -m pip install -r requirements-macos-intel.txt
"$build_python" -c 'import platform, PySide6, libtorrent; print("architecture", platform.machine()); print("PySide6", PySide6.__version__); print("libtorrent", libtorrent.__version__)'
"$build_python" tools/verify_release.py
QT_QPA_PLATFORM=offscreen "$build_python" -m unittest discover -s tests -v

rm -rf build dist release-dist dmg-stage
"$build_python" -m PyInstaller --noconfirm build_macos.spec
"$build_python" -m PyInstaller --noconfirm creator_macos.spec
"$build_python" tools/verify_macos_bundle.py \
    "dist/ODeR.app" "dist/ODeR Creator.app" \
    --architecture x86_64 --maximum-deployment-target 12.0

mkdir -p release-dist
mkdir -p "dmg-stage/ODeR" "dmg-stage/ODeR Creator"
cp -R "dist/ODeR.app" "dmg-stage/ODeR/"
cp -R "dist/ODeR Creator.app" "dmg-stage/ODeR Creator/"
ln -s /Applications "dmg-stage/ODeR/Applications"
ln -s /Applications "dmg-stage/ODeR Creator/Applications"
hdiutil create -volname "ODeR" -srcfolder "dmg-stage/ODeR" -ov -format UDZO "release-dist/ODeR.dmg"
hdiutil create -volname "ODeR Creator" -srcfolder "dmg-stage/ODeR Creator" -ov -format UDZO "release-dist/ODeR Creator.dmg"

(cd release-dist && shasum -a 256 "ODeR.dmg" "ODeR Creator.dmg" > "SHA256SUMS.txt")
rm -rf dmg-stage
echo "macOS applications and disk images are in release-dist/"
