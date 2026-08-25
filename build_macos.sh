#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

brew install python@3.14 libtorrent-rasterbar
build_python="$(brew --prefix python@3.14)/bin/python3.14"
torrent_site="$(brew --prefix libtorrent-rasterbar)/lib/python3.14/site-packages"
export PYTHONPATH="$torrent_site${PYTHONPATH:+:$PYTHONPATH}"
"$build_python" -m venv --system-site-packages .macos-build-venv
build_python="$project_root/.macos-build-venv/bin/python"
"$build_python" -m pip install -r requirements.txt
"$build_python" -m pip install pyinstaller pillow
"$build_python" -c "import libtorrent; print('libtorrent', libtorrent.__version__)"
"$build_python" tools/verify_release.py

rm -rf build dist release-dist dmg-stage
"$build_python" -m PyInstaller --noconfirm build_macos.spec
"$build_python" -m PyInstaller --noconfirm creator_macos.spec

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
