# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Qt edition.

Not to be confused with `pdfarranger.spec` in the repository root, which is an
RPM spec for packaging the GTK application on Fedora.

Build from the repository root:

    pip install -e ".[packaging]"
    python tools/build_mo.py            # translations must exist first
    pyinstaller packaging/pdfarranger-qt.spec
"""

import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

# Compiled catalogues. The application looks in share/locale first (see
# i18n.locale_dirs), so they ship there rather than in build/mo.
datas = []
mo_root = os.path.join(project_root, "build", "mo")
if os.path.isdir(mo_root):
    for language in sorted(os.listdir(mo_root)):
        catalogue = os.path.join(mo_root, language, "LC_MESSAGES", "pdfarranger.mo")
        if os.path.isfile(catalogue):
            datas.append((catalogue, os.path.join("share", "locale", language,
                                                  "LC_MESSAGES")))
else:
    print("WARNING: build/mo is missing - run tools/build_mo.py for translations")

icon_ico = os.path.join(project_root, "data", "pdfarranger.ico")
if os.path.isfile(icon_ico):
    datas.append((icon_ico, "."))

a = Analysis(
    [os.path.join(project_root, "pdfarranger_qt", "__main__.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    # QtPdf is loaded through PySide6 rather than imported by name, and img2pdf
    # pulls its image backends in lazily.
    hiddenimports=["PySide6.QtPdf", "PySide6.QtPrintSupport", "img2pdf"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here uses these, and they are large.
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtMultimedia",
              "gi", "cairo", "matplotlib", "numpy.f2py"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdfarranger-qt",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI application: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_ico if os.path.isfile(icon_ico) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="pdfarranger-qt",
)
