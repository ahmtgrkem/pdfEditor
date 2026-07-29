# -*- mode: python ; coding: utf-8 -*-
"""AGY PDF Editor - PyInstaller Yapılandırma Betiği.

Kullanım:
    pyinstaller agy_pdf_editor.spec --noconfirm --clean

Çıktı:
    dist/AGY_PDF_Editor/AGY_PDF_Editor.exe
"""
import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(SPECPATH)
ASSETS = os.path.join(ROOT, "assets")

# --- Kaynak dosyalar (Görseller ve İkonlar) ----------------------------
datas = []
for name in ("app_icon.ico", "app.ico", "app.png"):
    path = os.path.join(ASSETS, name)
    if os.path.exists(path):
        datas.append((path, "assets"))

# --- İkili kütüphane bağımlılıkları (PyMuPDF / fitz DLL'leri) ----------
binaries = []
for package in ("pymupdf", "fitz"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

# --- Gizli importlar ---------------------------------------------------
hiddenimports = [
    "pymupdf",
    "pymupdf.mupdf",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",
    "PySide6.QtWidgets",
    "PySide6.QtGui",
    "PySide6.QtCore",
]
try:
    hiddenimports += collect_submodules("app")
except Exception:
    pass

# --- Gereksiz Qt modüllerini hariç tut ---------------------------------
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Gereksiz Qt DLL'lerini paketten temizle
_UNWANTED_DLL = (
    "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt63D", "Qt6Charts", "Qt6DataVisualization",
    "Qt6Multimedia", "Qt6WebEngine", "Qt6WebSockets", "Qt6WebChannel",
    "Qt6Designer", "Qt6Test", "Qt6Sql", "Qt6Help", "Qt6Concurrent",
)

a.binaries = [
    entry for entry in a.binaries
    if not os.path.basename(entry[0]).startswith(_UNWANTED_DLL)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AGY_PDF_Editor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # --noconsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ASSETS, "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AGY_PDF_Editor",
)
