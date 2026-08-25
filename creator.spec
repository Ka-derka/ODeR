# Build with: pyinstaller creator.spec
# Produces the private executable payload used by the Creator installer.

from core.version import CREATOR_VERSION, windows_version_tuple
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VSVersionInfo,
    VarFileInfo, VarStruct,
)


version_tuple = windows_version_tuple(CREATOR_VERSION)
windows_version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "kaderka"),
                StringStruct("FileDescription", "ODeR Creator — Library authoring workstation"),
                StringStruct("FileVersion", CREATOR_VERSION),
                StringStruct("InternalName", "ODeR Creator"),
                StringStruct("LegalCopyright", "Copyright © 2026 kaderka"),
                StringStruct("OriginalFilename", "ODeR Creator.exe"),
                StringStruct("ProductName", "ODeR Creator"),
                StringStruct("ProductVersion", CREATOR_VERSION),
            ]),
        ]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

a = Analysis(
    ["creator_main.py"],
    pathex=[],
    binaries=[],
    datas=[("icon.png", ".")],
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
    name="ODeR Creator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon="icon.ico",
    version=windows_version_info,
)
