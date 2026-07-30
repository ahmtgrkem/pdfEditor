"""2. Metin işleme, seçim deneyimi ve tuval (canvas) testleri."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from app.core.annotations import TextStyle
from app.ui.tools import Tool
from conftest import click_page, drag_on_page, page_view_pos, pump

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

    def test_secim_tutamaklari_gorunur(self, opened_image, qapp):
        """Görsel seçilince 8 boyutlandırma tutamağı çıkmalı."""
        view = opened_image.view
        assert view.selection_handles() == [], "Seçim yokken tutamak olmamalı"

        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        assert view.selected_image is not None, "Görsele tıklayınca seçilmeli"
        assert len(view.selection_handles()) == 8

    def test_eklenen_nesne_tasinabilir(self, opened_image, qapp):
        """Seçili görsel klavye/koddan kaydırılabilmeli ve belgeye yazılmalı."""
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)

        assert view.move_selected_object(40.0, 25.0) is True
        gorseller = opened_image.controller.page_images(0)
        assert len(gorseller) == 1
        x0, y0, _x1, _y1 = gorseller[0]["rect"]
        assert abs(x0 - (IMAGE_RECT[0] + 40.0)) < 1.5, x0
        assert abs(y0 - (IMAGE_RECT[1] + 25.0)) < 1.5, y0


# ======================================================================
# 2.3 Metin motoru (font, boyut, hizalama)
# ======================================================================
class TestSayfaGorselleri:
    """Sayfadaki görselin seçilmesi, taşınması, boyutlandırılması, silinmesi."""

    def test_bos_alana_tiklayinca_secim_kalkar(self, opened_image, qapp):
        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        assert view.selected_image is not None

        click_page(view, 0, 500.0, 120.0)
        pump(qapp)
        assert view.selected_image is None

    def test_surukleyerek_tasinir(self, opened_image, qapp):
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        drag_on_page(view, 0, (260.0, 340.0), (330.0, 400.0))
        pump(qapp)

        gorseller = opened_image.controller.page_images(0)
        assert len(gorseller) == 1
        x0, y0 = gorseller[0]["rect"][:2]
        assert abs(x0 - (IMAGE_RECT[0] + 70.0)) < 2.0, x0
        assert abs(y0 - (IMAGE_RECT[1] + 60.0)) < 2.0, y0

    @pytest.mark.parametrize("bitis,beklenen_dx,beklenen_dy", [
        ((350.0, 355.0), 90.0, 0.0),     # baskın yön yatay -> dikey sabit
        ((275.0, 440.0), 0.0, 100.0),    # baskın yön dikey -> yatay sabit
    ])
    def test_shift_ile_hizada_kalir(self, opened_image, qapp, bitis,
                                    beklenen_dx, beklenen_dy):
        """Shift basılıyken taşıma baskın eksende kilitlenmeli."""
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        drag_on_page(view, 0, (260.0, 340.0), bitis, modifiers=Qt.ShiftModifier)
        pump(qapp)

        x0, y0 = opened_image.controller.page_images(0)[0]["rect"][:2]
        assert abs(x0 - (IMAGE_RECT[0] + beklenen_dx)) < 2.0, x0
        assert abs(y0 - (IMAGE_RECT[1] + beklenen_dy)) < 2.0, y0

    def test_shift_yokken_iki_eksende_de_tasinir(self, opened_image, qapp):
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        drag_on_page(view, 0, (260.0, 340.0), (350.0, 395.0))
        pump(qapp)

        x0, y0 = opened_image.controller.page_images(0)[0]["rect"][:2]
        assert abs(x0 - (IMAGE_RECT[0] + 90.0)) < 2.0, x0
        assert abs(y0 - (IMAGE_RECT[1] + 55.0)) < 2.0, y0

    def test_kose_tutamagi_orani_korur(self, opened_image, qapp):
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        oran = (IMAGE_RECT[3] - IMAGE_RECT[1]) / (IMAGE_RECT[2] - IMAGE_RECT[0])

        # Sağ-alt köşe tutamağını dışa sürükle (yalnız yatayda).
        drag_on_page(view, 0, (IMAGE_RECT[2], IMAGE_RECT[3]),
                     (IMAGE_RECT[2] + 60.0, IMAGE_RECT[3]))
        pump(qapp)

        x0, y0, x1, y1 = opened_image.controller.page_images(0)[0]["rect"]
        assert x1 - x0 > (IMAGE_RECT[2] - IMAGE_RECT[0]) + 40, "Genişlemeliydi"
        yeni_oran = (y1 - y0) / (x1 - x0)
        assert abs(yeni_oran - oran) < 0.05, f"Oran bozuldu: {yeni_oran} != {oran}"

    def test_delete_tusu_gorseli_siler(self, opened_image, qapp):
        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        pump(qapp)

        assert opened_image.controller.page_images(0) == []
        assert view.selected_image is None

    def test_tasima_metni_ve_cizimi_bozmaz(self, opened_image, qapp):
        view = opened_image.view
        belge = opened_image.controller.document
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        assert view.move_selected_object(30.0, 0.0) is True

        assert "Bu metin kalmali" in belge.page_text(0)
        with belge.lock:
            assert belge.raw.load_page(0).get_drawings(), "Çizgi silinmemeli"

    def test_arkaya_gonderilen_gorsel_metnin_altinda_kalir(self, opened_image, qapp):
        """Z sırası: aynı yere çizilen görsel öndeyken metni örtmeli."""
        import fitz

        view = opened_image.view
        belge = opened_image.controller.document
        ustu = fitz.Rect(60, 688, 260, 712)      # metnin bulunduğu şerit

        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        # Görseli metnin üzerine getir
        assert view.move_selected_object(-160.0, 350.0) is True
        with belge.lock:
            onde = belge.raw.load_page(0).get_pixmap(clip=ustu).tobytes("png")

        assert view.bring_selected_image(False) is True
        with belge.lock:
            arkada = belge.raw.load_page(0).get_pixmap(clip=ustu).tobytes("png")

        assert onde != arkada, "Öne/arkaya alma çıktıyı değiştirmeli"

    def test_geri_al_tasimayi_iptal_eder(self, opened_image, qapp):
        from conftest import IMAGE_RECT

        view = opened_image.view
        click_page(view, 0, 260.0, 340.0)
        pump(qapp)
        assert view.move_selected_object(50.0, 50.0) is True

        opened_image.controller.undo()
        pump(qapp)
        x0, y0 = opened_image.controller.page_images(0)[0]["rect"][:2]
        assert abs(x0 - IMAGE_RECT[0]) < 1.5, x0
        assert abs(y0 - IMAGE_RECT[1]) < 1.5, y0


class TestYaziTipiCozumleme:
    """Düzenlenen metnin yazı tipi değişmemeli."""

    def test_sistemdeki_aileler_listelenir(self):
        from app.core import fonts

        aileler = fonts.available_families()
        # Sabit dokuz aileden fazlası olmalı: Word'deki gibi tüm sistem fontları.
        assert len(aileler) > 20, f"Yalnızca {len(aileler)} aile bulundu"
        assert aileler == sorted(aileler, key=str.lower)

    @pytest.mark.parametrize("kalin,yatik", [(False, False), (True, False),
                                             (False, True), (True, True)])
    def test_stil_dogru_dosyaya_gider(self, kalin, yatik):
        """Kalın istendiğinde düz dosya dönerse metin inceleşiyordu."""
        import fitz

        from app.core import fonts

        _ad, yol = fonts.resolve("Arial", kalin, yatik)
        if yol is None:
            pytest.skip("Arial kurulu değil")
        bayraklar = fitz.Font(fontfile=yol).flags
        assert bool(bayraklar["bold"]) is kalin, yol
        assert bool(bayraklar["italic"]) is yatik, yol

    @pytest.mark.parametrize("pdf_adi,beklenen", [
        ("ABCDEF+TimesNewRomanPSMT", "Times New Roman"),
        ("ArialMT", "Arial"),
        ("Arial-BoldMT", "Arial"),
        ("CourierNewPS-BoldMT", "Courier New"),
        ("ArialNarrow-Bold", "Arial Narrow"),
        ("Helvetica", "Arial"),
    ])
    def test_pdf_font_adi_dogru_aileye_eslenir(self, pdf_adi, beklenen):
        from app.core import fonts

        if not fonts.has_family(beklenen):
            pytest.skip(f"{beklenen} kurulu değil")
        assert fonts.match(pdf_adi) == beklenen

    @pytest.mark.parametrize("kaynak,serif_mi", [
        ("Georgia", True), ("Times New Roman", True),
        ("Verdana", False), ("Arial", False),
    ])
    def test_olcuyle_en_yakin_aile_bulunur(self, kaynak, serif_mi):
        """Ada bakmadan, harf genişlikleriyle serif/sans doğru ayrılmalı.

        Belgedeki yazı tipi kurulu değilse ad tahmini işe yaramıyor ve her
        şey Arial'e düşüyordu; serif bir belge düzenlenirken ekran sans oluyordu.
        """
        from app.core import fonts

        if not fonts.has_family(kaynak):
            pytest.skip(f"{kaynak} kurulu değil")
        _ad, yol = fonts.resolve(kaynak)
        bulunan = fonts.closest_by_metrics(yol)
        assert bulunan, "Bir aile bulunmalı"

        SERIFLER = {"Times New Roman", "Georgia", "Cambria", "Garamond",
                    "Book Antiqua", "Palatino Linotype", "Constantia"}
        assert (bulunan in SERIFLER) is serif_mi, (
            f"{kaynak} -> {bulunan} (serif beklenen: {serif_mi})"
        )

    @pytest.mark.parametrize("aile", ["Arial", "Georgia", "Verdana",
                                      "Times New Roman", "Segoe UI"])
    def test_kalinlik_murekkeple_olculur(self, aile):
        """Kalınlık ada değil, çizilen mürekkebe bakılarak bulunmalı.

        ``FormataOTFMd`` gibi ara ağırlıklar ne span bayrağında ne adında
        "bold" taşıyor; ekranda ince görünüyorlardı.
        """
        from app.core import fonts

        if not fonts.has_family(aile):
            pytest.skip(f"{aile} kurulu değil")
        ORNEK = "JASTIN POMPEU SOARES"
        _a, duz = fonts.resolve(aile, bold=False)
        _b, kalin = fonts.resolve(aile, bold=True)
        if duz == kalin:
            pytest.skip(f"{aile} için ayrı kalın yüz yok")

        assert fonts.looks_bold(kalin, ORNEK) is True
        assert fonts.looks_bold(duz, ORNEK) is False, "Düz yüz kalın sayılmamalı"
        assert fonts.stem_width(kalin, ORNEK) > fonts.stem_width(duz, ORNEK)

    def test_hicbir_duz_yuz_kalin_sayilmaz(self):
        """Yanlış pozitif olmamalı: düz metin ekranda kalınlaşmasın.

        Yanlış negatif zararsız (span bayrağı ve font adı zaten yakalıyor),
        yanlış pozitif ise düz metni kalın gösterip yazarken de kalınlaştırır.
        """
        from app.core import fonts

        yanlis = []
        for aile in fonts.available_families():
            _a, duz = fonts.resolve(aile, bold=False)
            _b, kalin = fonts.resolve(aile, bold=True)
            if not duz or duz == kalin:
                continue
            if fonts.looks_bold(duz, "Hamburgefonstiv HAMBURG"):
                yanlis.append(aile)
        assert not yanlis, f"Düz yüzü kalın sayılan aileler: {yanlis}"

    def test_kalinlik_olcumu_bozuk_fontta_patlamaz(self, tmp_path):
        from app.core import fonts

        bos = tmp_path / "bos.ttf"
        bos.write_bytes(b"font degil")
        assert fonts.looks_bold(str(bos), "deneme") is False
        assert fonts.stem_width(str(bos), "deneme") is None

    def test_olcu_esleme_gliflersiz_fontta_none_doner(self, tmp_path):
        from app.core import fonts

        bos = tmp_path / "bos.ttf"
        bos.write_bytes(b"bu bir font degil")
        assert fonts.closest_by_metrics(str(bos)) is None

    def test_gomulu_font_yeniden_kullanilir(self, tmp_path):
        """Belgedeki font sistemde olmasa da metin onunla yazılmalı."""
        import fitz

        from app.core import annotations as ann
        from app.core import fonts
        from app.core.document import PdfDocument

        _ad, yol = fonts.resolve("Georgia")
        if yol is None:
            pytest.skip("Georgia kurulu değil")
        kaynak = tmp_path / "gomulu.pdf"
        doc = fitz.open()
        doc.new_page().insert_text(
            (72, 100), "Merhaba", fontsize=14, fontname="FG", fontfile=yol
        )
        doc.save(str(kaynak))
        doc.close()

        belge = PdfDocument()
        belge.open(str(kaynak))
        bilgi = ann.find_text_at_point(belge, 0, (80.0, 96.0))
        assert bilgi is not None

        adaylar = ann.embedded_font_files(belge, 0, bilgi["raw_font"])
        assert adaylar, "Gömülü font bulunmalı"
        assert ann.embedded_font_path(belge, 0, bilgi["raw_font"]) in adaylar
        assert ann.embedded_fontfile(belge, 0, bilgi["raw_font"], "Merhaba")
        # Fontun taşımadığı bir glif istenirse özgün font kullanılmamalı.
        assert ann.embedded_fontfile(belge, 0, bilgi["raw_font"], "日本語") is None

        stil = TextStyle(family=bilgi["font"], size=bilgi["size"],
                         source_font=bilgi["raw_font"])
        assert ann.replace_text(belge, 0, bilgi["rect"], "Merhaba yeni",
                                stil, origin=bilgi["origin"])
        span = belge.raw.load_page(0).get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
        assert "Georgia" in span["font"], f"Yazı tipi değişmiş: {span['font']}"


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

    def test_degismeyen_metin_belgeye_yazilmaz(self, opened, qapp):
        """Çift tıklayıp hiçbir şey değiştirmeden çıkmak belgeyi bozmamalı.

        Yeniden yazmak metni redaksiyonla silip kuruyor; harf aralıkları ve
        gömülü font bilgisi kaybolduğu için yazı tipi değişiyordu.
        """
        view = opened.view
        bilgi = opened.controller.find_text_at_point(0, (100.0, 116.0))
        assert bilgi is not None
        with opened.controller.document.lock:
            once = opened.controller.document.raw.load_page(0).get_text("rawdict")

        view.start_inline_editing(view._items[0], bilgi)
        pump(qapp)
        assert view.inline_editor is not None
        view.commit_live_text_widget()      # tek harf bile değiştirilmedi
        pump(qapp)

        with opened.controller.document.lock:
            sonra = opened.controller.document.raw.load_page(0).get_text("rawdict")
        assert sonra == once, "Değişmeyen metin belgeye yeniden yazılmamalı"
        assert opened.controller.can_undo() is False, "Geri al yığınına girmemeli"

    def test_metin_duzenleme_ust_satiri_silmez(self, opened, qapp, tmp_path):
        """Sıkı satır aralığında bir satırı düzenlemek komşusunu bozmamalı.

        Span'ın bildirdiği kutu font metriğinden gelir ve üstteki satıra
        taşar; redaksiyon o kutuyla yapılınca üst satır da siliniyordu.
        """
        import pymupdf

        d = pymupdf.open()
        s = d.new_page(width=400, height=200)
        # 20 punto, 26 punto satır aralığı: glifler ayrı ama font metriğinden
        # gelen kutular 1.5 punto üst üste biniyor — hatanın koşulu bu.
        s.insert_text(pymupdf.Point(40, 100), "UST SATIR KALMALI", fontsize=20)
        s.insert_text(pymupdf.Point(40, 126), "alt satir", fontsize=20)
        kaynak = tmp_path / "sikisik.pdf"
        d.save(str(kaynak))
        d.close()

        opened.controller.open(str(kaynak))
        pump(qapp)
        bilgi = opened.controller.find_text_at_point(0, (60.0, 120.0))
        assert bilgi is not None and "alt satir" in bilgi["text"]

        assert opened.controller.replace_text(
            0, bilgi["rect"], "DEGISTIRILDI",
            TextStyle(size=bilgi["size"], family=bilgi["font"]),
            origin=bilgi["origin"],
        ) is True

        metin = opened.controller.document.page_text(0).replace("\xa0", " ")
        assert "UST SATIR KALMALI" in metin, "Üst satır silinmemeli"
        assert "DEGISTIRILDI" in metin
        assert "alt satir" not in metin, "Eski satır kaldırılmalı"

    def test_metin_degistirmek_arka_plani_silmez(self, opened, qapp, tmp_path):
        """Düzenlenen metnin ardındaki zemin korunmalı.

        Eski davranışta silme işlemi alanı beyaz dolguyla boyuyordu; desenli
        ya da renkli bir zemin üzerindeki metni düzenlemeye girer girmez
        metnin ardında beyaz bir kutu beliriyordu.
        """
        import pymupdf

        # Renkli zemin üzerine metin
        d = pymupdf.open()
        s = d.new_page(width=300, height=200)
        s.draw_rect(pymupdf.Rect(0, 0, 300, 200), color=None, fill=(0.2, 0.4, 0.9))
        s.insert_text(pymupdf.Point(40, 100), "Eski metin", fontsize=18)
        kaynak = tmp_path / "zeminli.pdf"
        d.save(str(kaynak))
        d.close()

        opened.controller.open(str(kaynak))
        pump(qapp)
        assert opened.controller.replace_text(
            0, (35.0, 82.0, 200.0, 108.0), "Yeni metin", TextStyle(size=18.0)
        ) is True
        pump(qapp)

        sayfa = opened.controller.document.raw[0]
        metin = sayfa.get_text().replace("\xa0", " ")   # NBSP olarak çizilebilir
        assert "Yeni metin" in metin
        assert "Eski metin" not in metin

        # Metnin bulunduğu bölgede beyaz kalmamalı: zemin görünür olmalı.
        pix = sayfa.get_pixmap(dpi=72, clip=pymupdf.Rect(35, 82, 200, 108))
        beyaz = sum(
            1 for i in range(0, len(pix.samples), pix.n)
            if pix.samples[i] > 250 and pix.samples[i + 1] > 250
            and pix.samples[i + 2] > 250
        )
        oran = beyaz / (pix.width * pix.height)
        assert oran < 0.5, f"zemin beyazla örtülmüş (%{oran:.0%})"

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
