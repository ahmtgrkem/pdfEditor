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
# Dinamik XFA formları Qt WebEngine'de çalışır (bkz. app/ui/xfa_view.py).
# Görünüm gecikmeli import edildiği için WebEngine ve bağımlılıkları burada
# açıkça sayılır; aksi hâlde paketten düşer ve etkileşimli form açılmaz.
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
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPositioning",
]
try:
    hiddenimports += collect_submodules("app")
except Exception:
    pass

# WebEngine yalnız DLL değil; kendi alt süreci (QtWebEngineProcess.exe),
# .pak kaynakları ve yerelleştirmeleri olmadan çalışmaz.
try:
    from PyInstaller.utils.hooks import collect_data_files
    datas += collect_data_files("PySide6", includes=[
        "**/QtWebEngineProcess*",
        "**/resources/*.pak",
        "**/resources/*.dat",
        "**/translations/qtwebengine_locales/*",
        # Standart Qt diyaloglarının Türkçesi (bkz. app.main.install_translations)
        "**/translations/qtbase_tr.qm",
    ])
except Exception:
    pass

# --- Gereksiz Qt modüllerini hariç tut ---------------------------------
excludes = [
    "tkinter",
    "unittest",
    "pydoc_data",
    "PySide6.QtWebSockets",
    "PySide6.QtQuick3D",
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

# Gereksiz Qt DLL'lerini paketten temizle.
# DİKKAT: Qt6WebEngine*/Qt6WebChannel/Qt6Quick/Qt6Qml burada **olamaz** —
# etkileşimli XFA görünümü bunlara dayanır (Qt6Concurrent'a da WebEngine
# ihtiyaç duyar).
_UNWANTED_DLL = (
    "Qt6Pdf", "Qt63D", "Qt6Charts", "Qt6DataVisualization",
    "Qt6Multimedia", "Qt6WebSockets",
    "Qt6Designer", "Qt6Test", "Qt6Sql", "Qt6Help",
)

a.binaries = [
    entry for entry in a.binaries
    if not os.path.basename(entry[0]).startswith(_UNWANTED_DLL)
]

# Pakete girmemesi gereken veri dosyaları.
#
# ``qml/`` ağacı en önemlisi: QtWebEngine'in QML sürümüne ait 2510 dosyalık
# (24 MB) tema varlığı. Uygulama yalnızca **widget** sürümünü kullanıyor ve
# klasör olmadan da sorunsuz çalışıyor (paketlenmiş exe ile doğrulandı).
# Kaldırılması dosya sayısını 2971'den ~460'a düşürüyor: kurulum belirgin
# biçimde hızlanıyor, virüs taramasının işi azalıyor ve derin kurulum
# dizinlerinde MAX_PATH sınırını aşan yollar (``qml\QtQuick\Controls\
# FluentWinUI3\...``) ortadan kalkıyor — bu yollar kurulumda
# "MoveFile tamamlanamadı; kod 3" hatası veriyordu.
#
# DevTools kaynakları (83 MB) ve ``.debug`` çeşitleri de kullanılmıyor.
def _gereksiz(entry) -> bool:
    hedef = entry[0].replace("\\", "/")
    ad = os.path.basename(hedef)
    return (
        "/PySide6/qml/" in f"/{hedef}"
        or "qtwebengine_devtools_resources" in ad
        or ".debug.pak" in ad
        or ".debug.bin" in ad
    )


a.datas = [entry for entry in a.datas if not _gereksiz(entry)]
a.binaries = [entry for entry in a.binaries if not _gereksiz(entry)]

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
