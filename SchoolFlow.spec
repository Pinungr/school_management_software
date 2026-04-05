# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules, copy_metadata


hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("sqlalchemy")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("jinja2")
    + collect_submodules("multipart")
)

datas = [
    ("templates", "templates"),
    ("static", "static"),
] + copy_metadata("fastapi") + copy_metadata("sqlalchemy") + copy_metadata("jinja2") + copy_metadata("uvicorn") + copy_metadata("starlette") + copy_metadata("python-multipart")


a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="SchoolFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SchoolFlow",
)
