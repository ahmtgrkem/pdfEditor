"""Ortak test altyapısı: QApplication, örnek belgeler ve diyalog susturma.

Testler başsız (offscreen) çalışır; gerçek pencere görmek için:
    set QT_QPA_PLATFORM=windows && pytest tests -q
"""
from __future__ import annotations

import os
import sys

import pytest

# Qt'yi başsız çalıştır (CI ve arka planda test için)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pymupdf as fitz  # noqa: E402
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QColorDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)

SAMPLE_PAGES = 6
SAMPLE_LINE = "Sayfa {n} - Türkçe içerik şığĞÜÖİı test"
SAMPLE_BODY = "Lorem ipsum dolor sit amet consectetur adipiscing elit"


# ======================================================================
# Uygulama
# ======================================================================
@pytest.fixture(scope="session", autouse=True)
def settings_dir(tmp_path_factory):
    """Kullanıcının gerçek ayarlarını bozmamak için izole QSettings dizini.

    ``autouse``: izolasyonun yalnızca ``qapp`` isteyen testlerde geçerli
    olması yetmez — ayar nesnesi üreten her test korunmalı. Bu fikstür bir
    kez atlandığında testler kullanıcının kayıt defterine yazar.

    Ayrıca ``AppSettings`` biçimi açıkça vermek zorundadır; ``QSettings(org,
    app)`` kurucusu buradaki ``setDefaultFormat`` çağrısını yok sayar.
    """
    path = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(path))
    return path


@pytest.fixture(scope="session")
def qapp(settings_dir):
    from app.ui import theme

    app = QApplication.instance() or QApplication([])
    theme.apply(app, "dark")
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def silence_dialogs(monkeypatch):
    """Modal diyaloglar testi kilitlemesin; çağrılar kayda alınır."""
    calls: dict[str, list] = {"message": [], "file": [], "input": []}

    def record_message(kind):
        def _inner(parent=None, title="", text="", *args, **kwargs):
            calls["message"].append((kind, title, text))
            if kind == "question":
                return QMessageBox.Yes
            return QMessageBox.Ok
        return staticmethod(_inner)

    for name in ("information", "warning", "critical", "about"):
        monkeypatch.setattr(QMessageBox, name, record_message(name))
    monkeypatch.setattr(QMessageBox, "question", record_message("question"))

    # Örnek olarak kurulan kutular (özel düğmeli QMessageBox) statik metotları
    # kullanmaz; ``exec`` susturulmazsa test modal pencerede süresiz bekler.
    def blocked_exec(self):
        calls["message"].append(("exec", self.windowTitle(), self.text()))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "exec", blocked_exec)

    def blocked_file(*args, **kwargs):
        calls["file"].append(args)
        return ("", "")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(blocked_file))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(blocked_file))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], ""))
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "")
    )
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (1, False)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QColorDialog, "exec", lambda self: 0)
    return calls


@pytest.fixture
def window(qapp, silence_dialogs):
    """Her test için taze ana pencere."""
    from app.services.settings import AppSettings
    from app.ui.main_window import MainWindow

    win = MainWindow(AppSettings())
    win.resize(1200, 850)
    win.show()
    qapp.processEvents()
    yield win
    try:
        win.controller.document.mark_clean()
        win.controller.shutdown()
    finally:
        win.close()
        qapp.processEvents()


@pytest.fixture
def opened(window, sample_pdf, qapp):
    """Örnek belge açılmış pencere."""
    assert window.open_path(str(sample_pdf)) is True
    for _ in range(8):
        qapp.processEvents()
    return window


# ======================================================================
# Örnek dosyalar
# ======================================================================
def _build_sample(path: str, pages: int = SAMPLE_PAGES) -> str:
    from app.core import fonts

    # Türkçe karakterler için gerçek bir TTF gömülür (base-14 fontlar yetmez).
    alias, fontfile = fonts.resolve("Arial")
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 120), SAMPLE_LINE.format(n=i + 1), fontsize=18,
                         fontname=alias, fontfile=fontfile)
        page.insert_text((72, 160), SAMPLE_BODY, fontsize=12,
                         fontname=alias, fontfile=fontfile)
    doc.set_toc([[1, "Giriş", 1], [2, "Alt başlık", 2], [1, "Sonuç", max(1, pages - 1)]])
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory):
    return _build_sample(str(tmp_path_factory.mktemp("pdf") / "ornek.pdf"))


@pytest.fixture(scope="session")
def second_pdf(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("pdf2") / "ikinci.pdf")
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"Ek belge sayfa {i + 1}", fontsize=16)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture(scope="session")
def encrypted_pdf(tmp_path_factory, sample_pdf):
    path = str(tmp_path_factory.mktemp("enc") / "sifreli.pdf")
    doc = fitz.open(sample_pdf)
    doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="sahip", user_pw="gizli")
    doc.close()
    return path


@pytest.fixture(scope="session")
def corrupt_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("bozuk") / "bozuk.pdf"
    path.write_bytes(b"%PDF-1.7\nbu dosya kasten bozuldu\n%%EOF")
    return str(path)


@pytest.fixture
def readonly_pdf(tmp_path, sample_pdf):
    import shutil
    import stat

    path = tmp_path / "salt_okunur.pdf"
    shutil.copy(sample_pdf, path)
    os.chmod(path, stat.S_IREAD)
    yield str(path)
    os.chmod(path, stat.S_IWRITE)


@pytest.fixture(scope="session")
def sample_png(tmp_path_factory):
    from PIL import Image

    path = str(tmp_path_factory.mktemp("img") / "damga.png")
    img = Image.new("RGBA", (240, 120), (255, 0, 0, 180))
    img.save(path)
    return path


#: ``image_pdf``teki görselin yerleştirildiği alan (punto)
IMAGE_RECT = (200.0, 300.0, 320.0, 380.0)


@pytest.fixture
def image_pdf(tmp_path):
    """Metin, çizgi ve tek bir görsel içeren sayfa.

    Görsel düzenleme testleri için: taşıma/silme metni ve çizimi bozmamalı.
    """
    import io

    from PIL import Image

    tampon = io.BytesIO()
    Image.new("RGB", (120, 80), (200, 30, 30)).save(tampon, "PNG")

    path = tmp_path / "gorselli.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 700), "Bu metin kalmali", fontsize=12)
    page.insert_image(fitz.Rect(*IMAGE_RECT), stream=tampon.getvalue())
    page.draw_line(fitz.Point(50, 600), fitz.Point(300, 600),
                   color=(0, 0, 1), width=2)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def opened_image(window, image_pdf, qapp):
    """``image_pdf`` açılmış, seçim aracı etkin pencere."""
    from app.ui.tools import Tool

    assert window.open_path(image_pdf) is True
    for _ in range(8):
        qapp.processEvents()
    window.tools.set_tool(Tool.SELECT)
    return window


# ======================================================================
# Yardımcılar
# ======================================================================
def pump(app, times: int = 6) -> None:
    """Kuyruktaki Qt olaylarını işler."""
    for _ in range(times):
        app.processEvents()


def page_annots(document, index: int) -> list:
    with document.lock:
        return list(document.raw.load_page(index).annots())


def page_view_pos(view, page_index: int, x_pt: float, y_pt: float):
    """Sayfa üzerindeki punto koordinatını görünüm (viewport) koordinatına çevirir."""
    from PySide6.QtCore import QPointF

    item = view._items[page_index]
    scene = QPointF(
        item.pos().x() + x_pt * view.zoom,
        item.pos().y() + y_pt * view.zoom,
    )
    return QPointF(view.mapFromScene(scene))


def mouse_drag(view, start, end, steps: int = 6, release: bool = True,
               button=None, modifiers=None):
    """Görünüm üzerinde gerçek QMouseEvent'lerle fare sürüklemesi simüle eder."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    button = button or Qt.LeftButton
    modifiers = Qt.NoModifier if modifiers is None else modifiers

    def send(kind, pos, buttons):
        event = QMouseEvent(kind, QPointF(pos), button, buttons, modifiers)
        if kind == QEvent.MouseButtonPress:
            view.mousePressEvent(event)
        elif kind == QEvent.MouseMove:
            view.mouseMoveEvent(event)
        else:
            view.mouseReleaseEvent(event)

    send(QEvent.MouseButtonPress, start, button)
    for i in range(1, steps + 1):
        t = i / steps
        mid = QPointF(
            start.x() + (end.x() - start.x()) * t,
            start.y() + (end.y() - start.y()) * t,
        )
        send(QEvent.MouseMove, mid, button)
    if release:
        send(QEvent.MouseButtonRelease, end, Qt.NoButton)


def drag_on_page(view, page_index: int, p1: tuple, p2: tuple, **kwargs) -> None:
    """Punto koordinatlarıyla sayfa üzerinde sürükleme yapar."""
    start = page_view_pos(view, page_index, *p1)
    end = page_view_pos(view, page_index, *p2)
    mouse_drag(view, start, end, **kwargs)


def click_page(view, page_index: int, x_pt: float, y_pt: float) -> None:
    """Sayfadaki punto koordinatına tek tıklama."""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    pos = page_view_pos(view, page_index, x_pt, y_pt)
    view.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(pos), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier))
    view.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(pos), Qt.LeftButton,
        Qt.NoButton, Qt.NoModifier))
