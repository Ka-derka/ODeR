# Build with:  pyinstaller build.spec
# Produces a single windowed exe (no console window) with the icon embedded.
# The "data" folder is created next to the exe on first run — nothing needs
# to be bundled for it.

block_cipher = None

from core.version import APP_VERSION
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VSVersionInfo,
    VarFileInfo,
    VarStruct,
)

version_numbers = tuple(int(part) for part in APP_VERSION.split("-", 1)[0].split("+", 1)[0].split("."))
version_tuple = (version_numbers + (0, 0, 0, 0))[:4]
windows_version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "kaderka"),
                StringStruct("FileDescription", "ODeR — Offline Directory Browser"),
                StringStruct("FileVersion", APP_VERSION),
                StringStruct("InternalName", "ODeR"),
                StringStruct("LegalCopyright", "Copyright © 2026 kaderka"),
                StringStruct("OriginalFilename", "ODeR-Portable.exe"),
                StringStruct("ProductName", "ODeR"),
                StringStruct("ProductVersion", APP_VERSION),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ODeR-Portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon='icon.ico',
    version=windows_version_info,
)
# Passing a.binaries / a.datas directly into EXE() (rather than COLLECT())
# is what makes this a single-file build.
