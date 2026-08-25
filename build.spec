# Build with: pyinstaller build.spec
# Produces the private executable payload consumed by the Windows installer.

block_cipher = None

from core.version import APP_VERSION, windows_version_tuple
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VSVersionInfo,
    VarFileInfo,
    VarStruct,
)

version_tuple = windows_version_tuple()
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
                StringStruct("OriginalFilename", "ODeR.exe"),
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
    hiddenimports=['libtorrent'],
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
    name='ODeR',
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
# The one-file executable is an installer payload, not a separately supported
# portable distribution.
