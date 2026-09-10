# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir build (optional .app / .exe). See build.sh.
import sys

_hidden = [
    'platform_utils', 'app_config', 'hotkeys', 'hotkey_mac', 'history', 'watcher', 'panel',
    'objc', 'Foundation', 'AppKit', 'Cocoa', 'Quartz', 'ApplicationServices',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_file = ['assets/icon.icns'] if sys.platform == 'darwin' else ['assets\\icon.ico']

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClipboardHistory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClipboardHistory',
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='ClipboardHistory.app',
        icon='assets/icon.icns',
        bundle_identifier='com.clipboardhistory.app',
        info_plist={
            'LSUIElement': True,
            'NSHighResolutionCapable': True,
        },
    )
