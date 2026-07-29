"""4. Canlı metin düzenleyici: konum, punto ve taban çizgisi hizası."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from app.core.annotations import TextStyle
from app.core.document import normalize_text
from app.ui.inline_text_editor import InlineCanvasTextWidget
from app.ui.tools import Tool
from conftest import page_view_pos, pump

#: Ölçüm toleransı — istenen nokta ile PyMuPDF'in yazdığı nokta arası sapma
TOLERANCE_PT = 0.05


def spans_of(controller, page: int = 0) -> list[dict]:
    with controller.document.lock:
        data = controller.document.raw.load_page(page).get_text("dict")
    return [
        span
        for block in data.get("blocks", []) if block.get("type") == 0
        for line in block.get("lines", []) for span in line.get("spans", [])
    ]


def find_span(controller, needle: str, page: int = 0) -> dict | None:
    """Gömülü fontlar boşlukları U+00A0 olarak döndürebildiği için normalize eder."""
    for span in spans_of(controller, page):
        if needle in normalize_text(span.get("text", "")):
            return span
    return None


def make_widget(zoom: float, size: float, x0: float = 100.0, y0: float = 200.0,
                text: str = "Hgxy Türkçe şığ", **style_kw) -> InlineCanvasTextWidget:
    style = TextStyle(family="Arial", size=size, **style_kw)
    widget = InlineCanvasTextWidget(0, (x0, y0, x0 + 300.0, y0 + size * 1.5), zoom, style)
    widget.editor.setPlainText(text)
    return widget


# ======================================================================
# 4.1 Punto ve DPI ölçekleme
# ======================================================================
class TestPuntoOlcekleme:
    @pytest.mark.parametrize("zoom", [0.75, 1.0, 1.47, 2.5])
    @pytest.mark.parametrize("size", [12.0, 18.0, 32.0])
    def test_ekran_piksel_boyutu_punto_carpi_zoom(self, qapp, zoom, size):
        """Ekrandaki font, PDF'in 72 DPI tabanıyla birebir örtüşmeli."""
        widget = make_widget(zoom, size)
        assert widget.font_pixel_size() == round(size * zoom)

    def test_qfont_pointsize_dpi_tuzagina_dusmez(self, qapp):
        """Qt pt->px dönüşümü 96 DPI ile yapar; bu yüzden px kullanılmalı."""
        widget = make_widget(1.0, 24.0)
        font = widget.editor_font()
        assert font.pixelSize() == 24, "Font piksel cinsinden ayarlanmalı"
        assert font.pointSize() == -1, "pointSize kullanılırsa metin %33 büyür"

    def test_karakter_formati_da_piksel_tabanli(self, qapp):
        widget = make_widget(2.0, 16.0)
        pump(qapp)
        cursor = widget.editor.textCursor()
        cursor.setPosition(1)
        assert cursor.charFormat().font().pixelSize() == 32

    def test_punto_degisimi_ani_yansir(self, qapp):
        widget = make_widget(1.0, 12.0)
        widget.toolbar._increase_size()
        assert widget.style.size == 14.0
        assert widget.font_pixel_size() == 14


# ======================================================================
# 4.2 0 piksel hizalama
# ======================================================================
class TestSifirPikselHizalama:
    def test_metin_alani_arac_cubugu_ve_tutamak_kadar_ofsetli(self, qapp):
        widget = make_widget(1.0, 14.0)
        pump(qapp)
        origin = widget.text_origin()
        assert origin.x() == widget.HANDLE_W + widget.BORDER
        assert origin.y() == widget.toolbar_height() + widget.TOOLBAR_GAP + widget.BORDER
        # Editörün widget içindeki konumu tam olarak bu ofsete oturmalı
        assert widget.editor.pos().x() == origin.x()
        assert widget.editor.pos().y() == origin.y()

    def test_editorde_ic_marjin_kalmaz(self, qapp):
        widget = make_widget(1.0, 14.0)
        assert widget.editor.document().documentMargin() == 0
        assert widget.editor.frameWidth() == 0
        assert widget.editor.viewportMargins().left() == 0
        assert widget.editor.viewportMargins().top() == 0

    def test_arac_cubugu_ustte_yer_yoksa_alta_gecer(self, qapp):
        widget = make_widget(1.0, 14.0)
        above = widget.text_origin_y(toolbar_below=False)
        widget.set_toolbar_below(True)
        assert widget.text_origin_y() == widget.BORDER
        assert widget.text_origin_y() < above, "Alt yerleşimde metin ofseti küçülmeli"

    def test_widget_gorunumde_dogru_noktaya_yerlesir(self, opened, qapp):
        """Metin alanının sol-üstü, sayfadaki hedef noktanın ekran karşılığı olmalı."""
        view = opened.view
        view.start_new_inline_text(0, (120.0, 300.0, 400.0, 330.0))
        pump(qapp)
        widget = view._live_text_widget
        assert widget is not None

        beklenen = page_view_pos(view, 0, 120.0, 300.0)
        gercek = widget.pos() + widget.text_origin()
        assert abs(gercek.x() - beklenen.x()) <= 1
        assert abs(gercek.y() - beklenen.y()) <= 1


# ======================================================================
# 4.3 Taban çizgisi (baseline) hizası — uçtan uca
# ======================================================================
class TestTabanCizgisiHizasi:
    @pytest.mark.parametrize("zoom", [0.75, 1.0, 1.47, 2.5])
    @pytest.mark.parametrize("size", [12.0, 18.0, 32.0])
    def test_pdf_taban_cizgisi_istenen_noktaya_oturur(self, opened, qapp, zoom, size):
        """Düzenleyicinin bildirdiği taban çizgisi ile PDF'teki span çakışmalı.

        Bu, "ekranda gördüğün yer = PDF'e yazılan yer" sözleşmesinin uçtan uca
        doğrulamasıdır ve font metriklerinden bağımsızdır (offscreen Qt'de font
        veritabanı taslak metrik döndürdüğü için bbox karşılaştırılamaz).
        """
        x0, y0 = 100.0, 400.0
        widget = make_widget(zoom, size, x0=x0, y0=y0, text="Hgxy")
        pump(qapp)
        result = widget.result()
        assert result is not None

        onceki = len(spans_of(opened.controller))
        assert opened.controller.add_text(
            0, result.rect, result.text, result.style,
            origin=result.origin, line_height=result.line_height,
        ) is True

        spans = spans_of(opened.controller)
        assert len(spans) > onceki
        span = spans[-1]
        assert abs(span["origin"][0] - result.origin[0]) <= TOLERANCE_PT, "Yatay kayma"
        assert abs(span["origin"][1] - result.origin[1]) <= TOLERANCE_PT, "Dikey kayma"
        assert abs(span["bbox"][0] - x0) <= TOLERANCE_PT, "Sol kenar x0'a oturmalı"
        assert abs(span["size"] - size) < 0.01, "Punto birebir korunmalı"

    def test_taban_cizgisi_fontun_ascent_ini_kullanir(self, qapp):
        """``origin_y = y0 + ascent`` — kutu üstü ile taban çizgisi karıştırılmamalı."""
        from app.core import fonts

        widget = make_widget(1.0, 24.0)
        pump(qapp)
        result = widget.result()
        beklenen = widget.pdf_rect[1] + fonts.ascender("Arial") * 24.0
        # Qt ve PyMuPDF ascent değerleri birebir aynı olmak zorunda değil;
        # taban çizgisinin makul aralıkta olduğu doğrulanır.
        assert abs(result.origin[1] - beklenen) < 24.0 * 0.15

    def test_origin_taban_cizgisidir_kutu_ustu_degil(self, qapp):
        widget = make_widget(1.0, 20.0)
        pump(qapp)
        result = widget.result()
        # Taban çizgisi kutu üstünün altında, bir satır yüksekliğinden yukarıda
        assert result.origin[1] > widget.pdf_rect[1]
        assert result.origin[1] < widget.pdf_rect[1] + result.line_height
        assert result.origin[0] == widget.pdf_rect[0]

    def test_cok_satirli_metin_satir_araligini_korur(self, opened, qapp):
        widget = make_widget(1.0, 14.0, x0=90.0, y0=500.0, text="Birinci\nİkinci\nÜçüncü")
        pump(qapp)
        result = widget.result()
        assert opened.controller.add_text(
            0, result.rect, result.text, result.style,
            origin=result.origin, line_height=result.line_height,
        ) is True

        yazilanlar = [s for s in spans_of(opened.controller)
                      if normalize_text(s["text"]).strip()
                      in ("Birinci", "İkinci", "Üçüncü")]
        assert len(yazilanlar) == 3
        tepeler = sorted(s["origin"][1] for s in yazilanlar)
        aralik_1 = tepeler[1] - tepeler[0]
        aralik_2 = tepeler[2] - tepeler[1]
        assert abs(aralik_1 - result.line_height) <= TOLERANCE_PT
        assert abs(aralik_1 - aralik_2) <= TOLERANCE_PT


# ======================================================================
# 4.4 Taşıma ve boyutlandırma tutamakları
# ======================================================================
class TestTutamaklar:
    def test_tutamaklar_metin_alaninin_disinda_durur(self, qapp):
        widget = make_widget(1.0, 14.0)
        pump(qapp)
        editor = widget.editor.geometry()
        assert widget.drag_handle.geometry().right() < editor.left()
        assert widget.resize_handle.geometry().left() > editor.right()

    def test_tasima_pdf_rect_i_anlik_gunceller(self, qapp):
        widget = make_widget(2.0, 14.0)
        pump(qapp)
        onceki = widget.pdf_rect
        widget.move_by_pixels(40, 20, onceki)     # zoom=2 -> 20pt, 10pt
        assert widget.pdf_rect[0] == pytest.approx(onceki[0] + 20.0)
        assert widget.pdf_rect[1] == pytest.approx(onceki[1] + 10.0)
        assert widget.pdf_rect[2] == pytest.approx(onceki[2] + 20.0)

    def test_genislik_ayari_pdf_rect_e_yansir(self, qapp):
        widget = make_widget(2.0, 14.0)
        pump(qapp)
        widget.set_text_width_px(400)
        genislik_pt = widget.pdf_rect[2] - widget.pdf_rect[0]
        assert genislik_pt == pytest.approx(200.0)
        assert widget.editor.width() == 400

    def test_zoom_degisimi_pdf_koordinatini_bozmaz(self, qapp):
        widget = make_widget(1.0, 16.0)
        pump(qapp)
        onceki = widget.pdf_rect[:3]
        widget.set_zoom(2.0)
        pump(qapp)
        assert widget.pdf_rect[0] == pytest.approx(onceki[0])
        assert widget.pdf_rect[1] == pytest.approx(onceki[1])
        assert widget.pdf_rect[2] == pytest.approx(onceki[2], abs=1.0)
        assert widget.font_pixel_size() == 32


# ======================================================================
# 4.5 Araç yönetimi (UX scoping)
# ======================================================================
class TestAracYonetimi:
    def _tikla(self, view, x_pt: float, y_pt: float) -> None:
        pos = page_view_pos(view, 0, x_pt, y_pt)
        view.mousePressEvent(
            QMouseEvent(QEvent.MouseButtonPress, QPointF(pos), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
        )
        view.mouseReleaseEvent(
            QMouseEvent(QEvent.MouseButtonRelease, QPointF(pos), Qt.LeftButton,
                        Qt.NoButton, Qt.NoModifier)
        )

    def test_bos_alana_tiklayinca_metin_islenir_ve_secime_donulur(self, opened, qapp):
        view = opened.view
        view.start_new_inline_text(0, (120.0, 620.0, 380.0, 650.0))
        pump(qapp)
        view._live_text_widget.editor.setPlainText("Onaylanan metin")
        pump(qapp)

        self._tikla(view, 300.0, 760.0)          # kutunun dışında bir nokta
        pump(qapp)

        assert view._live_text_widget is None, "Kutu kapanmalı"
        assert opened.tools.tool is Tool.SELECT, "Araç seçim moduna dönmeli"
        assert "Onaylanan metin" in opened.controller.document.page_text(0)

    def test_onaydan_sonra_tiklamak_yeni_kutu_acmaz(self, opened, qapp):
        view = opened.view
        view.start_new_inline_text(0, (120.0, 660.0, 380.0, 690.0))
        pump(qapp)
        view._live_text_widget.editor.setPlainText("Tek sefer")
        pump(qapp)
        self._tikla(view, 300.0, 770.0)
        pump(qapp)

        self._tikla(view, 200.0, 720.0)          # ikinci tıklama
        pump(qapp)
        assert view._live_text_widget is None, "Metin aracı deaktif olmalı"

    def test_bos_kutu_iptal_edilir(self, opened, qapp):
        view = opened.view
        view.start_new_inline_text(0, (120.0, 700.0, 380.0, 730.0))
        pump(qapp)
        view.commit_live_text_widget()
        pump(qapp)
        assert view._live_text_widget is None
        assert opened.tools.tool is Tool.SELECT

    def test_metin_araci_kutu_acar(self, opened, qapp):
        view = opened.view
        opened.tools.set_tool(Tool.TEXT)
        self._tikla(view, 150.0, 560.0)
        pump(qapp)
        assert view._live_text_widget is not None
        assert view.inline_editor is view._live_text_widget
        view._on_inline_text_cancelled()

    def test_baska_araca_gecince_metin_kaybolmaz(self, opened, qapp):
        view = opened.view
        view.start_new_inline_text(0, (100.0, 580.0, 380.0, 610.0))
        pump(qapp)
        view._live_text_widget.editor.setPlainText("Araç değişimi")
        opened.tools.set_tool(Tool.PENCIL)
        pump(qapp)
        assert view._live_text_widget is None
        assert "Araç değişimi" in opened.controller.document.page_text(0)


# ======================================================================
# 4.6 Mevcut metni düzenleme
# ======================================================================
class TestMevcutMetinDuzenleme:
    def test_cift_tik_canli_duzenleyiciyi_acar(self, opened, qapp):
        view = opened.view
        pos = page_view_pos(view, 0, 100.0, 118.0)
        view.mouseDoubleClickEvent(
            QMouseEvent(QEvent.MouseButtonDblClick, QPointF(pos), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
        )
        pump(qapp)
        widget = view.inline_editor
        assert widget is not None
        assert "Sayfa" in normalize_text(widget.editor.toPlainText())
        # Tespit edilen punto düzenleyiciye taşınmalı (örnek belge 18pt)
        assert widget.style.size == pytest.approx(18.0, abs=0.6)
        view._on_inline_text_cancelled()

    def test_duzenlenen_metin_ayni_satira_yazilir(self, opened, qapp):
        view = opened.view
        pos = page_view_pos(view, 0, 100.0, 118.0)
        view.mouseDoubleClickEvent(
            QMouseEvent(QEvent.MouseButtonDblClick, QPointF(pos), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
        )
        pump(qapp)
        widget = view.inline_editor
        eski = find_span(opened.controller, "Sayfa")
        assert eski is not None

        widget.editor.setPlainText("Değiştirilmiş satır")
        view.commit_live_text_widget()
        pump(qapp)

        yeni = find_span(opened.controller, "Değiştirilmiş")
        assert yeni is not None, "Yeni metin sayfada olmalı"
        assert abs(yeni["origin"][1] - eski["origin"][1]) <= TOLERANCE_PT, "Satır kaymamalı"
        assert abs(yeni["origin"][0] - eski["origin"][0]) <= TOLERANCE_PT, "Sütun kaymamalı"
        assert find_span(opened.controller, "Sayfa") is None, "Eski metin silinmeli"
