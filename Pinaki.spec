# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys
import importlib.util

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

python_base = Path(sys.base_prefix)
tk_root = python_base / "tcl"
tk_binaries = []
if importlib.util.find_spec("tkinter") is not None:
    hiddenimports += ["tkinter", "tkinter.ttk"]
    if tk_root.exists():
        datas += [(str(tk_root), "tcl")]
    for binary_name in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
        binary_path = python_base / "DLLs" / binary_name
        if binary_path.exists():
            tk_binaries.append((str(binary_path), "."))

icon_path = "static/app_icon.ico" if Path("static/app_icon.ico").exists() else None


a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=tk_binaries,
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
    name="Pinaki",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Pinaki",
)
