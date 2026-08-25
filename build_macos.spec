# Build on macOS with: pyinstaller --noconfirm build_macos.spec

from core.version import APP_VERSION, windows_version_tuple


numeric_version = ".".join(str(part) for part in windows_version_tuple()[:3])

a = Analysis(
    ["main.py"],
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
    name="ODeR",
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
    name="ODeR",
)
app = BUNDLE(
    coll,
    name="ODeR.app",
    icon="icon.png",
    bundle_identifier="io.github.ka-derka.oder",
    info_plist={
        "CFBundleDisplayName": "ODeR",
        "CFBundleShortVersionString": numeric_version,
        "CFBundleVersion": numeric_version,
        "CFBundleGetInfoString": f"ODeR {APP_VERSION}",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "ODeR Directory Package",
                "CFBundleTypeExtensions": ["oder"],
                "CFBundleTypeRole": "Viewer",
            },
            {
                "CFBundleTypeName": "ODeR Library",
                "CFBundleTypeExtensions": ["odrlib"],
                "CFBundleTypeRole": "Viewer",
            },
        ],
    },
)
