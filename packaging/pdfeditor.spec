# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller yapılandırması (PyInstaller 6.x).

Kullanım (proje kökünden):
    pyinstaller packaging/pdfeditor.spec --noconfirm --clean

Çıktı:  dist/PDFEditor/PDFEditor.exe   (konsolsuz)
"""
import os

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "assets")

# --- kaynak dosyalar ---------------------------------------------------
datas = []
for name in ("app.ico", "app.png"):
    path = os.path.join(ASSETS, name)
    if os.path.exists(path):
        datas.append((path, "assets"))

# --- ikili bağımlılıklar (MuPDF DLL'leri) ------------------------------
binaries = []
for package in ("pymupdf", "fitz"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass

# --- gizli importlar ---------------------------------------------------
hiddenimports = [
    "pymupdf",
    "pymupdf.mupdf",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PySide6.QtSvg",
    "PySide6.QtPrintSupport",
]
try:
    hiddenimports += collect_submodules("app")
except Exception:
    pass

# --- gereksiz modüller (paket boyutunu küçültür) -----------------------
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
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtHttpServer",
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

# --- kullanılmayan Qt kitaplıklarını at --------------------------------
# PySide6 kancası tüm Qt DLL'lerini kopyalar; yalnızca Widgets tabanlı
# arayüz için gerekmeyenler paketten çıkarılır (~15 MB kazanç).
_UNWANTED_DLL = (
    "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt63D", "Qt6Charts", "Qt6DataVisualization",
    "Qt6Graphs", "Qt6Multimedia", "Qt6WebEngine", "Qt6WebSockets", "Qt6WebChannel",
    "Qt6WebView", "Qt6Designer", "Qt6Test", "Qt6SpatialAudio", "Qt6TextToSpeech",
    "Qt6Bluetooth", "Qt6Nfc", "Qt6Positioning", "Qt6Location", "Qt6Sensors",
    "Qt6SerialPort", "Qt6SerialBus", "Qt6Scxml", "Qt6StateMachine",
    "Qt6RemoteObjects", "Qt6Sql", "Qt6Help", "Qt6NetworkAuth", "Qt6HttpServer",
    "Qt6Concurrent",
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
    name="PDFEditor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                      # --noconsole
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ASSETS, "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDFEditor",
)
