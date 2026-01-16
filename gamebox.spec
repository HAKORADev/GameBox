# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for GameBox
==========================================

Build command:
    pyinstaller gamebox.spec

Or simply:
    pyinstaller --onefile --name GameBox --windowed --hide-console hide-early --icon app_icon.ico --add-data "logo.png;." gamebox.py
"""

import os

block_cipher = None

# Use local UPX if available in the same directory
upx_dir = os.path.dirname(os.path.abspath(__file__))
upx_path = os.path.join(upx_dir, 'upx.exe')

a = Analysis(
    ['gamebox.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.png', '.')],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngineCore',
        'keyboard',
        'pyperclip',
        'google.generativeai',
        'PIL.Image',
        'PIL.PngImagePlugin',
        'qscintilla',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GameBox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    upx_path=upx_path,  # Use local UPX executable
    runtime_tmpdir=None,
    console=False,  # Windowed mode - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
    # Hide console early - reduces flickering
    hide_console=True,
)
