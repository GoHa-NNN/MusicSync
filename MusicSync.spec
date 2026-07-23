# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — MusicSync 绿色便携打包（--onedir）。"""
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('E:\\Develop\\Android\\Sdk\\platform-tools\\adb.exe', '.')],
    datas=[],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'email.mime', 'http', 'xml', 'pydoc',
              'lib2to3', 'distutils', 'test'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name='MusicSync',
    icon=None,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # GUI 应用，不显示控制台窗口
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name='MusicSync',
)
