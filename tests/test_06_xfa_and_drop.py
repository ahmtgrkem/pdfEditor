"""6. XFA form desteği ve dosya sürükle-bırak."""
from __future__ import annotations

import os

import pymupdf
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from app.core import xfa, xfa_render
from app.ui.file_drop import dropped_files

# Sürükleme olayları MIME verisinin ömrünü uzatmaz; referans tutulmazsa
# olay işlenmeden nesne toplanabilir.
_MIME_KEEPALIVE: list[QMimeData] = []


def _mime(paths: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _MIME_KEEPALIVE.append(mime)
    return mime


# ======================================================================
# 6.1 Sürükle-bırak yönlendirmesi
# ======================================================================
class TestDosyaBirakma:
    """Olayı **gerçek widget'a** göndererek sınar.

    Eski test ``window.dragEnterEvent(...)``i doğrudan çağırıyordu; bu,
    olay yönlendirmesini tamamen atladığı için belge alanına bırakmanın
    hiç çalışmadığını göremiyordu (``QGraphicsView`` olayı viewport'unda
    tüketiyor).
    """

    def _birak(self, app, widget, path: str) -> bool:
        gir = QDragEnterEvent(
            QPoint(10, 10), Qt.CopyAction, _mime([path]), Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(widget, gir)
        birak = QDropEvent(
            QPointF(10, 10), Qt.CopyAction, _mime([path]), Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(widget, birak)
        app.processEvents()
        return gir.isAccepted()

    @pytest.mark.parametrize("hedef", ["belge", "kucuk_resim", "pencere"])
    def test_her_alana_birakilan_dosya_acilir(self, qapp, window, sample_pdf, hedef):
        acilan: list = []
        window.open_dropped_files = acilan.append

        widget = {
            "belge": window.view.viewport(),
            "kucuk_resim": window.thumbnails.list.viewport(),
            "pencere": window,
        }[hedef]

        assert self._birak(qapp, widget, str(sample_pdf)), "dragEnter kabul edilmeli"
        assert acilan, f"{hedef} alanina birakilan dosya acilmali"
        assert acilan[0][0] == os.path.normpath(str(sample_pdf))

    def test_pdf_disi_dosya_kabul_edilmez(self, qapp, window, tmp_path):
        baska = tmp_path / "not.txt"
        baska.write_text("merhaba", encoding="utf-8")
        acilan: list = []
        window.open_dropped_files = acilan.append

        self._birak(qapp, window.view.viewport(), str(baska))
        assert not acilan

    def test_sayfa_siralama_surukleme_bozulmaz(self, qapp, window, sample_pdf):
        """Dosya içermeyen (iç) sürükleme küçük resim listesine kalmalı."""
        window.open_path(str(sample_pdf))
        qapp.processEvents()
        liste = window.thumbnails.list
        assert liste.count() > 1

        bos = QMimeData()          # iç sürüklemede URL yoktur
        _MIME_KEEPALIVE.append(bos)
        assert dropped_files(bos) == []

        gir = QDragEnterEvent(
            QPoint(10, 10), Qt.CopyAction, bos, Qt.LeftButton, Qt.NoModifier
        )
        QApplication.sendEvent(liste.viewport(), gir)
        # Karışım devraldıysa dosya olmadan da kabul ederdi; etmemeli.
        assert not gir.isAccepted()

    def test_dropped_files_yalnizca_pdf_dondurur(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        txt = tmp_path / "b.txt"
        txt.write_bytes(b"x")
        mime = _mime([str(txt), str(pdf)])
        assert dropped_files(mime) == [os.path.normpath(str(pdf))]

    def test_yollar_isletim_sistemi_bicimine_cevrilir(self, tmp_path):
        """toLocalFile Windows'ta eğik çizgi döndürür; normalleştirilmeli."""
        pdf = tmp_path / "n.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        (yol,) = dropped_files(_mime([str(pdf)]))
        assert yol == os.path.normpath(yol)
        if os.sep == "\\":
            assert "/" not in yol

    def test_bos_mime_cokertmez(self):
        assert dropped_files(None) == []
        assert dropped_files(QMimeData()) == []


# ======================================================================
# 6.2 XFA formları
# ======================================================================
def _yaz_xfa(path, template: bytes, datasets: bytes | None = None) -> None:
    """Verilen şablonu taşıyan asgari bir XFA PDF'i yazar."""
    if datasets is None:
        datasets = (
            '<xfa:datasets xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/">'
            '<xfa:data xfa:dataNode="dataGroup"/></xfa:datasets>'
        ).encode("utf-8")

    doc = pymupdf.open()
    doc.new_page()
    t_xref = doc.get_new_xref()
    doc.update_object(t_xref, "<<>>")
    doc.update_stream(t_xref, template)
    d_xref = doc.get_new_xref()
    doc.update_object(d_xref, "<<>>")
    doc.update_stream(d_xref, datasets)

    acro = doc.get_new_xref()
    doc.update_object(
        acro, f"<</Fields[]/XFA[(template){t_xref} 0 R(datasets){d_xref} 0 R]>>"
    )
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{acro} 0 R")
    doc.xref_set_key(doc.pdf_catalog(), "NeedsRendering", "true")
    doc.save(str(path))
    doc.close()


@pytest.fixture
def xfa_pdf(tmp_path):
    """İçinde küçük bir XFA paketi olan PDF üretir.

    Gerçek kurumsal form 1 MB'lık şablon taşıyor; test için asgari ama
    yapısal olarak aynı bir belge yeterli.
    """
    sablon = (
        '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
        '<subform name="form">'
        '<subform name="Kisi">'
        '<field name="ad">'
        '<caption><value><text>Ad Soyad</text></value></caption>'
        "<ui><textEdit/></ui>"
        "</field>"
        '<field name="ulke">'
        '<caption><value><text>Ülke</text></value></caption>'
        "<ui><choiceList/></ui>"
        "<items><text>Türkiye</text><text>Almanya</text></items>"
        '<items save="1"><text>TR</text><text>DE</text></items>'
        "</field>"
        '<field name="onay">'
        '<caption><value><text>Kabul ediyorum</text></value></caption>'
        "<ui><checkButton/></ui>"
        "<items><text>1</text></items>"
        "</field>"
        '<field name="gonder">'
        '<caption><value><text>Gönder</text></value></caption>'
        "<ui><button/></ui>"
        "</field>"
        "</subform></subform></template>"
    ).encode("utf-8")
    yol = tmp_path / "xfa.pdf"
    _yaz_xfa(yol, sablon)
    return yol


class TestXfaOkuma:
    def test_xfa_tespit_edilir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        assert xfa.is_xfa(d) is True
        assert xfa.is_dynamic(d) is True
        assert set(xfa.read_packets(d)) == {"template", "datasets"}
        d.close()

    def test_duz_pdf_xfa_sayilmaz(self, sample_pdf):
        d = pymupdf.open(str(sample_pdf))
        assert xfa.is_xfa(d) is False
        assert xfa.load(d) is None
        d.close()

    def test_alanlar_etiket_ve_turleriyle_okunur(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        form = xfa.load(d)
        assert form.root == "form"
        turler = {a.name: a.type for a in form.fields}
        assert turler == {
            "ad": "text", "ulke": "choice", "onay": "check", "gonder": "button"
        }
        etiketler = {a.name: a.caption for a in form.fields}
        assert etiketler["ad"] == "Ad Soyad"
        assert etiketler["ulke"] == "Ülke"
        d.close()

    def test_veri_yolu_altform_hiyerarsisini_izler(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        yollar = {a.path for a in xfa.load(d).fields}
        assert "form.Kisi.ad" in yollar
        d.close()

    def test_dugme_doldurulabilir_sayilmaz(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        form = xfa.load(d)
        assert len(form.fields) == 4
        assert {a.name for a in form.editable_fields} == {"ad", "ulke", "onay"}
        d.close()

    def test_secenekler_gosterilen_ve_kaydedilen_olarak_eslesir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        ulke = next(a for a in xfa.load(d).fields if a.name == "ulke")
        assert ulke.options == [("Türkiye", "TR"), ("Almanya", "DE")]
        d.close()

    def test_onay_kutusu_sablon_degeriyle_isaretlenmez(self):
        """Onay kutusunda ``<value>`` mevcut durum değil, "açık" değeridir.

        Durum sayılırsa boş bir form bütün kutuları işaretli açar.
        """
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            '<subform name="form"><field name="onay">'
            "<ui><checkButton/></ui>"
            "<value><text>C</text></value>"
            "<items><text>C</text></items>"
            "</field></subform></template>"
        ).encode()
        alan = xfa.extract_fields(sablon)[0]
        assert alan.type == "check"
        assert alan.value == "", "şablon değeri kutuyu işaretlememeli"
        assert alan.options == [("C", "C")], "açık değeri korunmalı"

    def test_metin_alani_sablon_degerini_korur(self):
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            '<subform name="form"><field name="ad">'
            "<ui><textEdit/></ui><value><text>Varsayılan</text></value>"
            "</field></subform></template>"
        ).encode()
        assert xfa.extract_fields(sablon)[0].value == "Varsayılan"

    def test_bozuk_sablon_cokertmez(self):
        assert xfa.extract_fields(b"<template bozuk") == []
        assert xfa.extract_fields(b"") == []
        assert xfa.read_values(b"gecersiz") == {}


class TestXfaYazma:
    def test_degerler_yazilip_geri_okunur(self, xfa_pdf, tmp_path):
        d = pymupdf.open(str(xfa_pdf))
        form = xfa.load(d)
        degerler = {"form.Kisi.ad": "Görkem", "form.Kisi.ulke": "TR"}
        assert xfa.write_values(d, degerler, form.root) is True

        cikti = tmp_path / "dolu.pdf"
        d.save(str(cikti))
        d.close()

        d2 = pymupdf.open(str(cikti))
        form2 = xfa.load(d2)
        okunan = {a.path: a.value for a in form2.fields if a.value}
        assert okunan == degerler
        d2.close()

    def test_turkce_karakterler_korunur(self, xfa_pdf, tmp_path):
        d = pymupdf.open(str(xfa_pdf))
        xfa.write_values(d, {"form.Kisi.ad": "Şığğüöİı Çınar"}, "form")
        cikti = tmp_path / "tr.pdf"
        d.save(str(cikti))
        d.close()

        d2 = pymupdf.open(str(cikti))
        deger = next(a.value for a in xfa.load(d2).fields if a.name == "ad")
        assert deger == "Şığğüöİı Çınar"
        d2.close()

    def test_bos_degerler_yazilmaz(self):
        veri = xfa.build_datasets({"form.Kisi.ad": "", "form.Kisi.ulke": "  "})
        assert b"<ad" not in veri and b"<ulke" not in veri

    def test_ic_ice_yol_agac_olarak_yazilir(self):
        veri = xfa.build_datasets({"form.A.B.c": "x"}).decode("utf-8")
        assert "<A><B><c>x</c></B></A>" in veri

    def test_xfa_olmayan_belgeye_yazilmaz(self, sample_pdf):
        d = pymupdf.open(str(sample_pdf))
        assert xfa.write_values(d, {"a.b": "c"}) is False
        d.close()


class TestXfaCizim:
    """Şablonun görüntülenebilir PDF'e dönüştürülmesi."""

    def test_olcu_birimleri_puntoya_cevrilir(self):
        assert xfa_render.parse_measure("10mm") == pytest.approx(28.346, abs=0.01)
        assert xfa_render.parse_measure("1in") == 72.0
        assert xfa_render.parse_measure("12pt") == 12.0
        assert xfa_render.parse_measure("1cm") == pytest.approx(28.346, abs=0.01)
        assert xfa_render.parse_measure("") == 0.0
        assert xfa_render.parse_measure(None, 5.0) == 5.0
        assert xfa_render.parse_measure("abc", 3.0) == 3.0

    def test_yerlesim_sayfa_ve_kutu_uretir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        yerlesim = xfa_render.layout_template(sablon)
        assert yerlesim.box_count == 4        # 3 doldurulabilir + 1 düğme
        assert all(k.w > 0 and k.h > 0 for s in yerlesim.pages for k in s)
        d.close()

    def test_cizilen_pdf_widget_icerir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        cikti = xfa_render.render(sablon)
        try:
            assert cikti.page_count >= 1
            adlar = {w.field_name for s in cikti for w in s.widgets()}
            # Düğme doldurulabilir olmadığı için widget üretilmez.
            assert any(a.endswith("ad") for a in adlar)
            assert any(a.endswith("ulke") for a in adlar)
            assert any(a.endswith("onay") for a in adlar)
            assert not any(a.endswith("gonder") for a in adlar)
        finally:
            cikti.close()
        d.close()

    def test_etiketler_sayfaya_cizilir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        cikti = xfa_render.render(sablon)
        try:
            metin = "".join(s.get_text() for s in cikti)
            # Boşluklar NBSP olarak çizilebildiği için normalleştirilir.
            duz = metin.replace("\xa0", " ")
            assert "Ad Soyad" in duz
            assert "Ülke" in duz
        finally:
            cikti.close()
        d.close()

    def test_cizilen_belgede_xfa_kalmaz(self, xfa_pdf):
        """Çıktı sıradan bir AcroForm PDF'i olmalı; XFA kalırsa Adobe
        AcroForm alanlarını yok sayar ve form yine boş görünür."""
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        veri = xfa_render.render_bytes(sablon)
        d.close()

        yeni = pymupdf.open(stream=veri, filetype="pdf")
        try:
            assert xfa.is_xfa(yeni) is False
            assert yeni.is_form_pdf
        finally:
            yeni.close()

    def test_degerler_widgetlara_islenir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        cikti = xfa_render.render(sablon, {"form.Kisi.ad": "Görkem"})
        try:
            degerler = {w.field_name: w.field_value
                        for s in cikti for w in s.widgets()}
            assert degerler.get("form.Kisi.ad") == "Görkem"
        finally:
            cikti.close()
        d.close()

    def test_gizli_bolumler_varsayilan_olarak_cizilmez(self):
        """Özgün görünüm esas alınır: Adobe/Foxit gizli bölümleri göstermez.

        ``show_hidden=True`` bunları da çizer — özgününe sadık değildir ama
        formun tamamını tek seferde doldurulabilir kılar.
        """
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            '<subform name="form" layout="tb">'
            '<subform name="Gizli" presence="hidden" w="100mm" h="20mm">'
            '<field name="a" w="80mm" h="9mm">'
            '<caption><value><text>Gizli alan</text></value></caption>'
            "<ui><textEdit/></ui></field>"
            "</subform></subform></template>"
        ).encode()
        assert xfa_render.layout_template(sablon).box_count == 0
        assert xfa_render.layout_template(sablon, show_hidden=True).box_count == 1

    def test_veri_tasiyici_alanlar_cizilmez(self):
        """``presence="invisible"`` alanlar görünür widget'larla üst üste
        binen iç veri taşıyıcılarıdır."""
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            '<subform name="form" layout="tb">'
            '<field name="gorunur" w="80mm" h="9mm"><ui><textEdit/></ui></field>'
            '<field name="tasiyici" presence="invisible" w="80mm" h="9mm">'
            "<ui><textEdit/></ui></field>"
            "</subform></template>"
        ).encode()
        yollar = [k.path for s in xfa_render.layout_template(sablon).pages for k in s]
        assert any(y.endswith("gorunur") for y in yollar)
        assert not any(y.endswith("tasiyici") for y in yollar)

    def test_dokunulmamis_onay_kutulari_kapali_cizilir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        cikti = xfa_render.render(sablon)          # değer verilmedi
        try:
            onay = next(w for s in cikti for w in s.widgets()
                        if w.field_name.endswith("onay"))
            assert onay.field_value in (False, "Off"), "boş form işaretli açılmamalı"
        finally:
            cikti.close()
        d.close()

    def test_veriyle_gelen_onay_kutusu_isaretlenir(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        cikti = xfa_render.render(sablon, {"form.Kisi.onay": "1"})
        try:
            onay = next(w for s in cikti for w in s.widgets()
                        if w.field_name.endswith("onay"))
            assert onay.field_value not in (False, "Off")
        finally:
            cikti.close()
        d.close()

    def test_kutular_sayfa_disina_tasmaz(self, xfa_pdf):
        d = pymupdf.open(str(xfa_pdf))
        sablon = xfa.packet_data(d, xfa.read_packets(d)["template"])
        yerlesim = xfa_render.layout_template(sablon)
        genislik = yerlesim.page_size[0]
        for sayfa in yerlesim.pages:
            for kutu in sayfa:
                assert kutu.x + kutu.w <= genislik + 0.5, f"{kutu.path} taşıyor"
        d.close()

    def test_sayfa_susleri_pagearea_dan_cizilir(self):
        """Arka plan görseli ve altbilgi kök alt formun dışında, ``pageArea``
        içindedir; yalnızca alt form gezilirse tamamen kaybolur."""
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            "<subform name='form' layout='tb'><pageSet><pageArea name='P1'>"
            "<medium stock='a4' short='210mm' long='297mm'/>"
            "<contentArea x='10mm' y='10mm' w='190mm' h='270mm'/>"
            "<draw name='Altbilgi' x='20mm' y='280mm' w='60mm' h='6mm'>"
            "<value><text>Alt bilgi</text></value></draw>"
            "</pageArea></pageSet>"
            "<field name='a' w='80mm' h='9mm'><ui><textEdit/></ui></field>"
            "</subform></template>"
        ).encode()
        yerlesim = xfa_render.layout_template(sablon)
        assert len(yerlesim.background) == 1
        assert yerlesim.background[0].path == "Altbilgi"

        cikti = xfa_render.render(sablon)
        try:
            assert "Alt bilgi" in cikti[0].get_text().replace("\xa0", " ")
        finally:
            cikti.close()

    def test_cok_sayfali_form_cizilir(self):
        """Etiketli alanlar ikinci sayfaya taştığında da çizim sürmeli.

        Etiket yerleşimi değişkeni bir kez ``Layout`` nesnesini gölgeleyip
        ikinci sayfada çökertmişti.
        """
        alanlar = "".join(
            f"<field name='a{i}' w='150mm' h='20mm'>"
            f"<caption reserve='40mm'><value><text>Etiket {i}</text></value></caption>"
            "<ui><textEdit/></ui></field>"
            for i in range(30)
        )
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            "<subform name='form' layout='tb'><pageSet><pageArea name='P1'>"
            "<medium stock='a4' short='210mm' long='297mm'/>"
            "<contentArea x='10mm' y='10mm' w='190mm' h='250mm'/>"
            "</pageArea></pageSet>" + alanlar + "</subform></template>"
        ).encode()

        yerlesim = xfa_render.layout_template(sablon)
        assert len(yerlesim.pages) > 1, "içerik birden çok sayfaya yayılmalı"

        cikti = xfa_render.render(sablon)
        try:
            assert cikti.page_count == len(yerlesim.pages)
            toplam = sum(len(list(s.widgets())) for s in cikti)
            assert toplam == 30
        finally:
            cikti.close()

    def test_sayfa_numaralari_altbilgide_yerine_konur(self):
        """Altbilgi ``Page <embed> of <embed>`` biçimindedir; referanslar
        çözülmezse sayfada "Page of" yazar."""
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/"'
            ' xmlns:xfa="http://www.xfa.org/schema/xfa-data/1.0/">'
            "<subform name='form' layout='tb'><pageSet><pageArea name='P1'>"
            "<medium stock='a4' short='210mm' long='297mm'/>"
            "<contentArea x='10mm' y='10mm' w='190mm' h='250mm'/>"
            "<field name='CurrentPage' id='fldCur' presence='hidden'"
            " x='20mm' y='280mm' w='20mm' h='6mm'><ui><numericEdit/></ui></field>"
            "<field name='PageCount' id='fldTot' presence='hidden'"
            " x='40mm' y='280mm' w='20mm' h='6mm'><ui><numericEdit/></ui></field>"
            "<draw name='Alt' x='60mm' y='280mm' w='60mm' h='6mm'><value>"
            "<exData contentType='text/html'><body><p>Page "
            "<span xfa:embed='#fldCur'/> of <span xfa:embed='#fldTot'/>"
            "</p></body></exData></value></draw>"
            "</pageArea></pageSet>"
            "<field name='a' w='80mm' h='9mm'><ui><textEdit/></ui></field>"
            "</subform></template>"
        ).encode()

        yerlesim = xfa_render.layout_template(sablon)
        assert yerlesim.page_field_ids == {"fldCur": "current", "fldTot": "total"}

        cikti = xfa_render.render(sablon)
        try:
            metin = cikti[0].get_text().replace("\xa0", " ")
            assert "Page 1 of 1" in metin
        finally:
            cikti.close()

    def test_yuvarlak_onay_kutusu_radyo_olur(self):
        """``shape="round"`` birbirini dışlayan seçim demektir."""
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            "<subform name='form'>"
            "<field name='r' w='40mm' h='6mm'>"
            "<ui><checkButton shape='round'/></ui></field>"
            "<field name='k' w='40mm' h='6mm' y='10mm'>"
            "<ui><checkButton/></ui></field>"
            "</subform></template>"
        ).encode()
        cikti = xfa_render.render(sablon)
        try:
            turler = {w.field_name: w.field_type for s in cikti for w in s.widgets()}
            assert turler["form.r"] == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON
            assert turler["form.k"] == pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        finally:
            cikti.close()

    def test_bozuk_sablon_cokertmez(self):
        assert xfa_render.layout_template(b"<bozuk").box_count == 0
        assert xfa_render.layout_template(b"").box_count == 0
        belge = xfa_render.render(b"<bozuk")
        try:
            assert belge.page_count >= 1      # boş da olsa geçerli PDF
        finally:
            belge.close()


class TestXfaArayuz:
    def test_xfa_acilinca_menu_etkinlesir(self, qapp, window, xfa_pdf, monkeypatch):
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information",
            staticmethod(lambda *a, **k: None),
        )
        assert window._actions["xfa_form"].isEnabled() is False
        window.open_path(str(xfa_pdf))
        qapp.processEvents()
        assert window._actions["xfa_form"].isEnabled() is True
        assert window._xfa_form is not None
        assert len(window._xfa_form.editable_fields) == 3

    def test_duz_pdf_acilinca_menu_kapali_kalir(self, qapp, window, sample_pdf):
        window.open_path(str(sample_pdf))
        qapp.processEvents()
        assert window._actions["xfa_form"].isEnabled() is False

    def test_diyalog_degerleri_toplar(self, qapp, xfa_pdf):
        from app.ui.dialogs import XfaFormDialog

        d = pymupdf.open(str(xfa_pdf))
        form = xfa.load(d)
        diyalog = XfaFormDialog(form)

        diyalog._editors["form.Kisi.ad"].setText("Ahmet")
        diyalog._editors["form.Kisi.onay"].setChecked(True)
        acilir = diyalog._editors["form.Kisi.ulke"]
        acilir.setCurrentIndex(acilir.findData("DE"))

        assert diyalog.values() == {
            "form.Kisi.ad": "Ahmet",
            "form.Kisi.onay": "1",
            "form.Kisi.ulke": "DE",
        }
        diyalog.close()
        d.close()

    def test_bos_birakilan_alanlar_gonderilmez(self, qapp, xfa_pdf):
        from app.ui.dialogs import XfaFormDialog

        d = pymupdf.open(str(xfa_pdf))
        diyalog = XfaFormDialog(xfa.load(d))
        assert diyalog.values() == {}
        diyalog.close()
        d.close()

    def test_formu_goruntule_belgeyi_degistirir(self, qapp, window, xfa_pdf):
        window.open_path(str(xfa_pdf))
        qapp.processEvents()
        assert window.controller.page_count == 1

        window.render_xfa_form()
        qapp.processEvents()

        ham = window.controller.document.raw
        assert xfa.is_xfa(ham) is False, "çizilen belgede XFA kalmamalı"
        assert ham.is_form_pdf, "alanlar AcroForm widget'ı olmalı"
        adlar = {w.field_name for s in ham for w in s.widgets()}
        assert any(a.endswith("ad") for a in adlar)

    def test_tum_bolumler_secenegi_gizlileri_de_cizer(self, qapp, window, tmp_path):
        gizli = tmp_path / "gizli.pdf"
        sablon = (
            '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
            '<subform name="form" layout="tb">'
            '<field name="acik" w="80mm" h="9mm">'
            "<caption><value><text>Açık</text></value></caption>"
            "<ui><textEdit/></ui></field>"
            '<subform name="Gizli" presence="hidden" w="100mm" h="20mm">'
            '<field name="kapali" w="80mm" h="9mm">'
            "<caption><value><text>Kapalı</text></value></caption>"
            "<ui><textEdit/></ui></field></subform>"
            "</subform></template>"
        ).encode()
        _yaz_xfa(gizli, sablon)

        window.open_path(str(gizli))
        qapp.processEvents()
        window.render_xfa_form()                   # özgün görünüm
        qapp.processEvents()
        adlar = {w.field_name for s in window.controller.document.raw
                 for w in s.widgets()}
        assert any(a.endswith("acik") for a in adlar)
        assert not any(a.endswith("kapali") for a in adlar)

        # Çizilen belge "kirli" sayılır; kaydetme sorusu açmayı iptal eder.
        window.controller.document.mark_clean()
        assert window.open_path(str(gizli)) is True
        qapp.processEvents()
        window.render_xfa_form(show_hidden=True)   # tüm bölümler
        qapp.processEvents()
        adlar = {w.field_name for s in window.controller.document.raw
                 for w in s.widgets()}
        assert any(a.endswith("kapali") for a in adlar)

    def test_goruntulenen_form_adsiz_acilir(self, qapp, window, xfa_pdf):
        """Çizilen belge diskteki dosyanın karşılığı değildir; yol atanırsa
        "Kaydet" özgün XFA dosyasının üzerine yazar."""
        window.open_path(str(xfa_pdf))
        qapp.processEvents()
        window.render_xfa_form()
        qapp.processEvents()
        assert window.controller.document.path is None
        assert window.controller.document.is_dirty is True
