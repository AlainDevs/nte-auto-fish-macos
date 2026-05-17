# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path.cwd()


a = Analysis(
    ["nte_fisher_app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "images"), "images"),
    ],
    hiddenimports=[
        "customtkinter",
        "darkdetect",
        "PIL._tkinter_finder",
        "Quartz",
        "ApplicationServices",
        "AppKit",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NTE Auto Fisher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file="entitlements.plist",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NTE Auto Fisher",
)
app = BUNDLE(
    coll,
    name="NTE Auto Fisher.app",
    icon=None,
    bundle_identifier="com.nte.autofisher",
    info_plist={
        "CFBundleName": "NTE Auto Fisher",
        "CFBundleDisplayName": "NTE Auto Fisher",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1",
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "NTE Auto Fisher activates the target game window before foreground mouse clicks.",
        "NSScreenCaptureUsageDescription": "NTE Auto Fisher captures the NTE window to detect fishing UI templates.",
    },
)
