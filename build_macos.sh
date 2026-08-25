#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")" && pwd)"
cd "$project_root"

python3 tools/verify_release.py
python3 -m pip install -r requirements.txt
python3 -m pip install pyinstaller pillow

rm -rf build dist release-dist dmg-stage
python3 -m PyInstaller --noconfirm build_macos.spec
python3 -m PyInstaller --noconfirm creator_macos.spec

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
