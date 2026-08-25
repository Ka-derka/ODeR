# Build on macOS with: pyinstaller --noconfirm creator_macos.spec

from core.version import CREATOR_VERSION, windows_version_tuple


numeric_version = ".".join(str(part) for part in windows_version_tuple(CREATOR_VERSION)[:3])

a = Analysis(
    ["creator_main.py"],
    pathex=[],
    binaries=[],
    datas=[("icon.png", ".")],
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
    [],
    exclude_binaries=True,
    name="ODeR Creator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=True,
    icon="icon.png",
    target_arch="x86_64",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ODeR Creator",
)
app = BUNDLE(
    coll,
    name="ODeR Creator.app",
    icon="icon.png",
    bundle_identifier="io.github.ka-derka.oder-creator",
    info_plist={
        "CFBundleDisplayName": "ODeR Creator",
        "CFBundleShortVersionString": numeric_version,
        "CFBundleVersion": numeric_version,
        "CFBundleGetInfoString": f"ODeR Creator {CREATOR_VERSION}",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "ODeR Creator Project",
                "CFBundleTypeExtensions": ["odrproj"],
                "CFBundleTypeRole": "Editor",
            },
        ],
    },
)
