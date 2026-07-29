"""7. Etkileşimli form alanları: tıklama, yazma, seçme."""
from __future__ import annotations

import pymupdf
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from app.core import form_fields
from app.ui.tools import Tool


@pytest.fixture
def form_pdf(tmp_path):
    """Metin, onay kutusu, radyo grubu ve açılır liste içeren PDF."""
    doc = pymupdf.open()
    sayfa = doc.new_page(width=400, height=300)

    metin = pymupdf.Widget()
    metin.rect = pymupdf.Rect(50, 40, 250, 62)
    metin.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    metin.field_name = "ad"
    metin.field_value = ""
    sayfa.add_widget(metin)

    onay = pymupdf.Widget()
    onay.rect = pymupdf.Rect(50, 80, 66, 96)
    onay.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    onay.field_name = "kabul"
    onay.field_value = False
    sayfa.add_widget(onay)

    for i, (ad, ust) in enumerate((("secim", 120), ("secim", 150))):
        radyo = pymupdf.Widget()
        radyo.rect = pymupdf.Rect(50, ust, 66, ust + 16)
        radyo.field_type = pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON
        radyo.field_name = f"{ad}{i}"
        radyo.field_value = False
        sayfa.add_widget(radyo)

    liste = pymupdf.Widget()
    liste.rect = pymupdf.Rect(50, 190, 250, 212)
    liste.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
    liste.field_name = "ulke"
    liste.choice_values = ["Türkiye", "Almanya", "Fransa"]
    sayfa.add_widget(liste)

    yol = tmp_path / "form.pdf"
    doc.save(str(yol))
    doc.close()
    return yol


# ======================================================================
# 7.1 Alanları okuma
# ======================================================================
class TestAlanOkuma:
    def test_alanlar_tur_ve_konumlariyla_listelenir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        alanlar = form_fields.list_fields(window.controller.document, 0)

        turler = {a.name: a.type for a in alanlar}
        assert turler["ad"] == "text"
        assert turler["kabul"] == "check"
        assert turler["ulke"] == "combo"
        assert turler["secim0"] == "radio"

        ad = next(a for a in alanlar if a.name == "ad")
        assert ad.rect == pytest.approx((50, 40, 250, 62), abs=0.5)
        assert ad.editable is True

    def test_secenekler_okunur(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        ulke = next(a for a in form_fields.list_fields(window.controller.document, 0)
                    if a.name == "ulke")
        assert ulke.options == ["Türkiye", "Almanya", "Fransa"]

    def test_noktadaki_alan_bulunur(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        assert form_fields.field_at(doc, 0, 150, 50).name == "ad"
        assert form_fields.field_at(doc, 0, 58, 88).name == "kabul"
        assert form_fields.field_at(doc, 0, 300, 250) is None

    def test_dondurulmus_sayfada_konum_duzeltilir(self, window, qapp, form_pdf):
        """Widget dikdörtgeni ham PDF uzayındadır ve sayfa döndürmesinden
        etkilenmez; görünüm koordinatına çevrilmezse alanlar yanlış yerde
        aranır."""
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        duz = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")

        with doc.lock:
            doc.raw[0].set_rotation(90)
        donuk = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        assert donuk.rect != duz.rect, "döndürmede konum güncellenmeli"


# ======================================================================
# 7.2 Değer yazma
# ======================================================================
class TestDegerYazma:
    def test_metin_yazilir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        assert form_fields.set_value(doc, 0, "ad", "Görkem") is True
        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        assert yeni.value == "Görkem"

    def test_onay_kutusu_cevrilir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        assert alan.checked is False

        form_fields.toggle(doc, alan)
        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        assert alan.checked is True

        form_fields.toggle(doc, alan)
        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        assert alan.checked is False, "onay kutusu geri kapanabilmeli"

    def test_secili_radyo_tiklayinca_kapanmaz(self, window, qapp, form_pdf):
        """HTML radyo davranışı: seçili düğmeye basmak onu boşa düşürmez."""
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        radyo = next(a for a in form_fields.list_fields(doc, 0) if a.name == "secim0")

        form_fields.toggle(doc, radyo)
        radyo = next(a for a in form_fields.list_fields(doc, 0) if a.name == "secim0")
        assert radyo.checked is True

        form_fields.toggle(doc, radyo)
        radyo = next(a for a in form_fields.list_fields(doc, 0) if a.name == "secim0")
        assert radyo.checked is True

    def test_belge_kirli_isaretlenir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        doc = window.controller.document
        doc.mark_clean()
        form_fields.set_value(doc, 0, "ad", "x")
        assert doc.is_dirty is True


# ======================================================================
# 7.3 Görüntüleyicide etkileşim
# ======================================================================
class TestGoruntuleyiciEtkilesimi:
    def _tikla(self, window, qapp, alan) -> QMouseEvent:
        view = window.view
        item = next(i for i in view._items if i.index == alan.page_index)
        x0, y0, x1, y1 = alan.rect
        sahne = item.pos() + QPointF(
            (x0 + x1) / 2 * view._zoom, (y0 + y1) / 2 * view._zoom
        )
        vp = view.mapFromScene(sahne)
        olay = QMouseEvent(
            QEvent.MouseButtonPress, QPointF(vp), Qt.LeftButton,
            Qt.LeftButton, Qt.NoModifier,
        )
        view.mousePressEvent(olay)
        qapp.processEvents()
        return olay

    def test_onay_kutusuna_tiklamak_cevirir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.SELECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        olay = self._tikla(window, qapp, alan)

        assert olay.isAccepted()
        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        assert yeni.checked is True

    def test_metin_alanina_tiklamak_duzenleyici_acar(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.SELECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        self._tikla(window, qapp, alan)

        editor = window.view._form_editor
        assert editor is not None, "düzenleyici açılmalı"
        editor.setText("Ahmet")
        editor._commit()
        qapp.processEvents()

        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        assert yeni.value == "Ahmet"
        assert window.view._form_editor is None, "onaydan sonra kapanmalı"

    def test_acilir_listeye_tiklamak_secim_kutusu_acar(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.SELECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ulke")
        self._tikla(window, qapp, alan)

        editor = window.view._form_editor
        assert editor is not None
        assert editor.count() == 4          # boş + 3 seçenek
        editor.setCurrentIndex(editor.findText("Almanya"))
        editor._commit()
        qapp.processEvents()

        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ulke")
        assert yeni.value == "Almanya"

    def test_esc_degeri_yazmaz(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.SELECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        self._tikla(window, qapp, alan)
        editor = window.view._form_editor
        editor.setText("yazılmamalı")
        editor.cancelled.emit()
        qapp.processEvents()

        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "ad")
        assert yeni.value == ""
        assert window.view._form_editor is None

    def test_form_degisikligi_geri_alinabilir(self, window, qapp, form_pdf):
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.SELECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        self._tikla(window, qapp, alan)
        assert next(a for a in form_fields.list_fields(doc, 0)
                    if a.name == "kabul").checked is True

        assert window.controller.undo() is True
        qapp.processEvents()
        assert next(a for a in form_fields.list_fields(doc, 0)
                    if a.name == "kabul").checked is False

    def test_ciziim_aracindayken_form_alani_tiklanmaz(self, window, qapp, form_pdf):
        """Alanın üzerine açıklama eklenebilmeli; form yalnızca seçim
        aracındayken etkileşimlidir."""
        window.open_path(str(form_pdf))
        qapp.processEvents()
        window.tools.set_tool(Tool.RECT)
        doc = window.controller.document

        alan = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        self._tikla(window, qapp, alan)

        assert window.view._form_editor is None
        yeni = next(a for a in form_fields.list_fields(doc, 0) if a.name == "kabul")
        assert yeni.checked is False
