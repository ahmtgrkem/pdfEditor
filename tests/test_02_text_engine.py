"""2. Metin işleme, seçim deneyimi ve tuval (canvas) testleri."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.core.annotations import TextStyle
from app.ui.tools import Tool
from conftest import drag_on_page, page_view_pos, pump

# Örnek belgede 1. satır ~ (72,120), 18 punto
TEXT_BOX = ((60.0, 100.0), (430.0, 136.0))


# ======================================================================
# 2.1 Metin seçimi ve kopyalama
# ======================================================================
class TestMetinSecimi:
    def test_surukleyerek_metin_secilir(self, opened, qapp):
        opened.tools.set_tool(Tool.SELECT)
        drag_on_page(opened.view, 0, *TEXT_BOX)
        pump(qapp)
        secilen = opened.view.selected_text()
        assert secilen, "Sürükleme sonrası metin seçilmiş olmalı"
        assert "Sayfa 1" in secilen
        assert "Türkçe" in secilen, "Türkçe karakterler seçimde bozulmamalı"

    def test_secim_dikdortgeni_dogru_sayfada_saklanir(self, opened, qapp):
        opened.tools.set_tool(Tool.SELECT)
        opened.view.go_to_page(2)
        pump(qapp)
        drag_on_page(opened.view, 2, *TEXT_BOX)
        assert opened.view._selection_page == 2
        assert opened.view._selection_rect is not None
        assert "Sayfa 3" in opened.view.selected_text()

    def test_ctrl_c_panoya_kopyalar(self, opened, qapp):
        QApplication.clipboard().clear()
        opened.tools.set_tool(Tool.SELECT)
        drag_on_page(opened.view, 0, *TEXT_BOX)
        assert opened.view.copy_selection() is True
        pump(qapp)
        pano = QApplication.clipboard().text()
        assert "Sayfa 1" in pano

    def test_bos_alanda_secim_metin_dondurmez(self, opened, qapp):
        opened.tools.set_tool(Tool.SELECT)
        drag_on_page(opened.view, 0, (60.0, 600.0), (300.0, 700.0))
        assert opened.view.selected_text() == ""
        assert opened.view.copy_selection() is False

    def test_escape_secimi_iptal_eder(self, opened, qapp):
        opened.tools.set_tool(Tool.SELECT)
        drag_on_page(opened.view, 0, *TEXT_BOX)
        assert opened.view._selection_rect is not None
        event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
        opened.view.keyPressEvent(event)
        assert opened.view._selection_rect is None


# ======================================================================
# 2.2 Canlı seçim kutusu (interactive bounding box)
# ======================================================================
class TestCanliSecimKutusu:
    def test_surukleme_sirasinda_kutu_cizilir(self, opened, qapp):
        """Fare basılıyken kesikli seçim kutusu ekrana çizilmeli."""
        opened.tools.set_tool(Tool.SELECT)
        view = opened.view
        pump(qapp)
        view.viewport().repaint()
        once = view.viewport().grab().toImage()

        # bırakmadan sürükle
        drag_on_page(view, 0, *TEXT_BOX, release=False)
        assert view._dragging is True
        view.viewport().repaint()
        pump(qapp)
        sirasinda = view.viewport().grab().toImage()

        assert sirasinda != once, "Sürükleme sırasında canlı seçim kutusu çizilmeli"
        rect = view._drag_rect_pt()
        assert rect.width() > 10 and rect.height() > 5

        # temizlik: bırak
        pos = page_view_pos(view, 0, *TEXT_BOX[1])
        view.mouseReleaseEvent(
            QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos), Qt.LeftButton,
                        Qt.NoButton, Qt.NoModifier)
        )

    def test_arac_degisince_canli_cizim_iptal_olur(self, opened, qapp):
        view = opened.view
        opened.tools.set_tool(Tool.PENCIL)
        drag_on_page(view, 0, (100.0, 400.0), (200.0, 450.0), release=False)
        assert view._dragging is True
        opened.tools.set_tool(Tool.SELECT)          # araç değişimi
        assert view._dragging is False, "Araç değişince yarım çizim iptal edilmeli"
        assert view._strokes == []

    @pytest.mark.xfail(reason="Seçime boyutlandırma tutamağı (resize handle) eklenmedi",
                       strict=True)
    def test_secim_tutamaklari_gorunur(self, opened):
        # Beklenen: seçim sonrası 8 tutamak ve taşıma/boyutlandırma önizlemesi.
        assert hasattr(opened.view, "selection_handles")

    @pytest.mark.xfail(reason="Yerleştirilmiş nesneyi taşıma/boyutlandırma yok",
                       strict=True)
    def test_eklenen_nesne_tasinabilir(self, opened):
        assert hasattr(opened.view, "move_selected_object")


# ======================================================================
# 2.3 Metin motoru (font, boyut, hizalama)
# ======================================================================
class TestMetinMotoru:
    def test_eklenen_metin_belgede_bulunur(self, opened, qapp):
        ok = opened.controller.add_text(
            0, (80.0, 300.0, 420.0, 360.0), "Türkçe metin şığĞÜÖİı",
            TextStyle(family="Arial", size=14.0),
        )
        assert ok is True
        metin = opened.controller.document.page_text(0)
        assert "Türkçe metin şığĞÜÖİı" in metin

    def test_font_ve_punto_korunur(self, opened):
        opened.controller.add_text(
            0, (80.0, 400.0, 430.0, 450.0), "Punto testi",
            TextStyle(family="Arial", size=20.0),
        )
        with opened.controller.document.lock:
            sozluk = opened.controller.document.raw.load_page(0).get_text("dict")
        from app.core.document import normalize_text

        puntolar = [
            span["size"]
            for blok in sozluk["blocks"] if blok.get("type") == 0
            for satir in blok["lines"] for span in satir["spans"]
            if "Punto testi" in normalize_text(span["text"])
        ]
        assert puntolar, "Eklenen metin span olarak bulunmalı"
        assert abs(puntolar[0] - 20.0) < 0.6, f"Punto korunmalı, bulunan: {puntolar[0]}"

    def test_kutuya_sigmayan_metin_kucultulur(self, opened):
        uzun = "Çok uzun bir metin. " * 40
        ok = opened.controller.add_text(
            0, (80.0, 500.0, 300.0, 560.0), uzun, TextStyle(size=18.0)
        )
        assert ok is True, "Metin otomatik küçültülerek sığdırılmalı"

    def test_kaydet_ac_dongusunde_metin_kalir(self, opened, tmp_path):
        opened.controller.add_text(
            0, (80.0, 600.0, 430.0, 650.0), "Kalıcılık testi", TextStyle()
        )
        hedef = tmp_path / "metinli.pdf"
        opened.controller.save(str(hedef))
        assert opened.open_path(str(hedef)) is True
        assert "Kalıcılık testi" in opened.controller.document.page_text(0)

    def test_cift_tik_ile_mevcut_metin_duzenlenir(self, opened, qapp):
        # Beklenen: metin bloğuna çift tıklayınca düzenlenebilir kutu açılması.
        view = opened.view
        pos = page_view_pos(view, 0, 100.0, 118.0)
        view.mouseDoubleClickEvent(
            QMouseEvent(QEvent.MouseButtonDblClick, QPointF(pos), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
        )
        pump(qapp)
        assert getattr(view, "inline_editor", None) is not None

    def test_zoom_degisimi_metin_duzenlemesini_bozmaz(self, opened, qapp):
        # 1. Metni düzenle (%147 zoom simülasyonu)
        opened.view.set_zoom(1.47)
        pump(qapp)
        ok = opened.controller.replace_text(
            0, (60.0, 100.0, 430.0, 136.0), "Yapay Zeka Yeni Metin", TextStyle(size=18.0)
        )
        assert ok is True, "Metin değiştirme başarılı olmalı"
        pump(qapp)
        assert "Yapay Zeka Yeni Metin" in opened.controller.document.page_text(0)

        # 2. Zoom seviyesini değiştir (%1.31)
        opened.view.set_zoom(1.31)
        pump(qapp)

        # 3. Güncellenen metnin PyMuPDF sayfasında ve render'da kalıcı olduğunu doğrula
        page_text = opened.controller.document.page_text(0)
        assert "Yapay Zeka Yeni Metin" in page_text, "Zoom değişince yeni metin kaybolmamalı"
