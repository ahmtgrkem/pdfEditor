"""Dinamik XFA formunun canlı çalışması ve dayanıklı belge açma.

:mod:`app.core.xfa_html` şablonu HTML'e derler, :mod:`app.core.xfa_runtime`
onu tarayıcı motorunda yaşatır. Buradaki testler derleyicinin ürettiği yapıyı
(alanlar, gizli bölümler, betikler, yerleşim) ve motor gerektirmeyen veri
yollarını doğrular; motorlu uçtan uca akış ``TestCanliMotor`` altındadır ve
QtWebEngine yoksa atlanır.
"""
from __future__ import annotations

import json
import re

import pytest

from pathlib import Path

from app.core import xfa, xfa_html


# ======================================================================
# Yardımcılar
# ======================================================================
def _sablon(govde: str, ekstra_kok: str = "") -> bytes:
    """Sayfa tanımı olan asgari ama geçerli bir XFA şablonu."""
    return (
        '<template xmlns="http://www.xfa.org/schema/xfa-template/3.3/">'
        '<subform name="form" layout="tb">'
        '<pageSet><pageArea name="Sayfa1">'
        '<medium short="210mm" long="297mm"/>'
        '<contentArea x="10mm" y="10mm" w="190mm" h="277mm"/>'
        "</pageArea></pageSet>"
        + govde +
        ekstra_kok +
        "</subform></template>"
    ).encode("utf-8")


@pytest.fixture
def dogrulama_sablonu() -> bytes:
    """Alandan çıkışta biçim denetleyip ``app.alert`` gösteren form.

    Gerçek kurumsal formlar doğrulamayı ``<validate>`` yerine ``exit``
    olayındaki betikle yapar (e-posta biçimi böyle denetleniyor).
    """
    return _sablon(
        '<subform name="Iletisim" layout="tb" w="190mm">'
        '  <field name="eposta" w="120mm" h="7mm">'
        '    <ui><textEdit/></ui>'
        '    <caption><value><text>E-posta</text></value></caption>'
        '    <event activity="exit">'
        '      <script contentType="application/x-javascript">'
        'var r = new RegExp("^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+\.[a-zA-Z]+$");'
        'if (!r.test(this.rawValue)) { app.alert("E-posta: Gecersiz bicim");'
        ' this.rawValue = ""; }'
        '      </script>'
        '    </event>'
        '  </field>'
        '</subform>'
    )


@pytest.fixture
def tablo_sablonu() -> bytes:
    """Tekrarlanabilir satırı olan tablo — "+" ile satır eklenir."""
    return _sablon(
        '<subform name="T" layout="table" columnWidths="60mm 60mm 20mm" w="190mm">'
        '  <subform name="baslik" layout="row" w="190mm" h="8mm">'
        '    <draw name="b1" w="60mm" h="8mm">'
        '      <value><text>Ad</text></value></draw>'
        '    <draw name="b2" w="60mm" h="8mm">'
        '      <value><text>Soyad</text></value></draw>'
        '    <draw name="b3" w="20mm" h="8mm">'
        '      <value><text>#</text></value></draw>'
        '  </subform>'
        '  <subform name="satir" layout="row" w="190mm" h="8mm">'
        '    <occur min="1" max="5"/>'
        '    <field name="ad" w="60mm" h="6mm"><ui><textEdit/></ui></field>'
        '    <field name="soyad" w="60mm" h="6mm"><ui><textEdit/></ui></field>'
        '    <field name="ekle" w="20mm" h="6mm">'
        '      <ui><button/></ui>'
        '      <caption><value><text>+</text></value></caption>'
        '      <event activity="click">'
        '        <script contentType="application/x-javascript">'
        'xfa.resolveNode("form.T.satir").instanceManager.addInstance(1);'
        '        </script>'
        '      </event>'
        '    </field>'
        '  </subform>'
        '</subform>'
    )


@pytest.fixture
def kosullu_sablon() -> bytes:
    """Seçime göre bir bölümü açan form — dinamik XFA'nın çekirdek davranışı."""
    return _sablon(
        '<subform name="Bolum" layout="tb" w="190mm">'
        '  <exclGroup name="Tur" w="190mm" h="8mm">'
        '    <field name="Birey" w="60mm" h="6mm">'
        '      <ui><checkButton shape="round"/></ui>'
        '      <caption placement="right" reserve="50mm">'
        "        <value><text>Bireysel</text></value></caption>"
        "      <items><text>B</text></items></field>"
        '    <field name="Kurum" w="60mm" h="6mm" x="65mm">'
        '      <ui><checkButton shape="round"/></ui>'
        '      <caption placement="right" reserve="50mm">'
        "        <value><text>Kurumsal</text></value></caption>"
        "      <items><text>K</text></items></field>"
        '    <event activity="click" name="event__click">'
        '      <script contentType="application/x-javascript">'
        'if (this.rawValue == "K") { form.Bolum.Kurumsal.presence = "visible"; }'
        'else { form.Bolum.Kurumsal.presence = "hidden"; }'
        "</script></event>"
        "  </exclGroup>"
        '  <subform name="Kurumsal" layout="tb" w="190mm" presence="hidden">'
        # İki uzun blok: bölüm açılınca form ikinci sayfaya taşar. Ayrı ayrı
        # duruyorlar ki sayfalama aralarından bölebilsin — yazdırma hizası
        # ancak çok sayfalı durumda anlamlı biçimde sınanır.
        '    <draw name="dolgu1" w="190mm" h="160mm"><value><text>.</text></value>'
        "    </draw>"
        '    <draw name="dolgu2" w="190mm" h="160mm"><value><text>.</text></value>'
        "    </draw>"
        '    <field name="unvan" w="190mm" h="9mm">'
        '      <ui><textEdit/></ui>'
        '      <caption reserve="50mm"><para vAlign="middle"/>'
        "        <value><text>Ünvan</text></value></caption>"
        '      <para vAlign="middle"/></field>'
        "  </subform>"
        "</subform>"
    )


# ======================================================================
# Derleyici
# ======================================================================
class TestDerleyici:
    def test_alanlar_gercek_denetimlere_cevrilir(self, kosullu_sablon):
        html = xfa_html.compile_template(kosullu_sablon).html
        assert '<input type="checkbox"' in html
        assert '<input type="text"' in html
        # Yuvarlak onay kutusu = radyo; kare çizilirse kullanıcı çoklu seçim sanır
        assert "xchk round" in html

    def test_alan_sayisi_ve_betikler_toplanir(self, kosullu_sablon):
        derlenmis = xfa_html.compile_template(kosullu_sablon)
        assert derlenmis.field_count == 3
        assert derlenmis.script_count == 1
        assert derlenmis.root == "form"

    def test_gizli_bolum_gizli_baslar(self, kosullu_sablon):
        html = xfa_html.compile_template(kosullu_sablon).html
        eslesme = re.search(
            r'data-som="form\.Bolum\.Kurumsal"[^>]*style="([^"]*)"', html)
        assert eslesme, "gizli alt form derlenmiş HTML'de bulunamadı"
        assert "display:none" in eslesme.group(1)

    def test_sayfa_olculeri_sablondan_alinir(self, kosullu_sablon):
        derlenmis = xfa_html.compile_template(kosullu_sablon)
        genis, yuksek = derlenmis.page_size
        assert round(genis) == 595 and round(yuksek) == 842

    def test_etiket_ve_alan_ayni_hizaya_gelir(self, kosullu_sablon):
        """Ekran görüntüsündeki hizalama sorununun regresyon testi.

        Etiket ve değer aynı ``vAlign``i paylaşır; flex hizalaması ikisine de
        yazılmazsa etiket alanın üstünde kalır.
        """
        html = xfa_html.compile_template(kosullu_sablon).html
        alan = re.search(r'data-som="form\.Bolum\.Kurumsal\.unvan".*?</div></div></div>',
                         html, re.S)
        assert alan, "alan bulunamadı"
        parca = alan.group(0)
        assert parca.count("align-items:safe center") == 2, (
            "etiket ve widget aynı dikey hizayı almalı")

    def test_metin_tasarsa_ustten_kirpilmaz(self):
        """``safe`` hizalama: ortalı uzun metinde ilk satır kaybolmamalı."""
        html = xfa_html.compile_template(_sablon(
            '<draw name="not" w="50mm" h="4mm"><para vAlign="middle"/>'
            "<value><text>Kutuya sığmayan uzunca bir açıklama metni</text></value>"
            "</draw>"
        )).html
        assert "align-items:safe center" in html

    def test_kenarlik_ayri_katmanda_durur(self):
        """Doğrulama vurgusu betikle açılıp kapanır; ayrı katman şart."""
        html = xfa_html.compile_template(_sablon(
            '<field name="a" w="50mm" h="9mm"><ui><textEdit/></ui>'
            '<border><edge presence="hidden" thickness="0.7mm">'
            '<color value="255,0,0"/></edge></border></field>'
        )).html
        katman = re.search(r'class="xhl"[^>]*style="([^"]*)"', html)
        assert katman, "kenarlık katmanı üretilmedi"
        assert "255,0,0" not in katman.group(1)      # renk #ff0000'a çevrilir
        assert "#ff0000" in katman.group(1)
        # Gizli tanımlı kenar başlangıçta kapalı ama betikle açılabilir olmalı
        assert "display:none" in katman.group(1)

    def test_gorsel_veri_uri_olarak_gomulur(self):
        # 1x1 saydam PNG
        png = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
               "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        html = xfa_html.compile_template(_sablon(
            f'<draw name="logo" w="10mm" h="10mm"><value>'
            f'<image contentType="image/png">{png}</image></value></draw>'
        )).html
        assert "data:image/png;base64,iVBORw0KGgo" in html

    def test_bos_sablon_hata_verir(self):
        with pytest.raises(ValueError):
            xfa_html.compile_template(b"")

    def test_calisma_zamani_gomulur(self, kosullu_sablon):
        html = xfa_html.compile_template(kosullu_sablon).html
        assert "window.XFA" in html and "instanceManager" in html
        assert "XFA_CONFIG" in html


class TestOlcuCevrimi:
    @pytest.mark.parametrize("girdi,punto", [
        ("25.4mm", 72.0), ("1in", 72.0), ("10pt", 10.0), ("2.54cm", 72.0),
        ("", 0.0), (None, 0.0), ("abc", 0.0),
    ])
    def test_birimler_puntoya_cevrilir(self, girdi, punto):
        from app.core.xfa_render import parse_measure
        assert round(parse_measure(girdi), 3) == punto


# ======================================================================
# Tablo sütunları
# ======================================================================
class TestTabloSutunlari:
    """``layout="table"`` + ``columnWidths`` regresyonu.

    Sütunlar yok sayılınca hücreler kendi ``w``leriyle çiziliyor, başlık
    satırıyla veri satırı birbirinden kayıyordu (Foxit'te hizalı görünen
    tablolar bizde bozuktu). Şablonlar hücreye tasarım aracından kalma dar
    bir ``w`` bırakır; gerçek ölçü tablodaki sütundur.
    """

    SABLON = _sablon(
        '<subform name="Tablo" layout="table" columnWidths="120mm 20mm">'
        '<subform name="Baslik" layout="row">'
        '<draw name="b1"><value><text>Sektor</text></value></draw>'
        '<draw name="b2"><value><text/></value></draw>'
        "</subform>"
        '<subform name="Satir" layout="row">'
        '<field name="h1" w="30mm"><ui><textEdit/></ui></field>'
        '<field name="h2" w="8mm"><ui><textEdit/></ui></field>'
        "</subform></subform>"
    )

    def _stil(self, html: str, ad: str) -> str:
        parca = html[html.index(f'data-name="{ad}"'):]
        return parca.split('style="', 1)[1].split('"', 1)[0]

    def test_hucre_kendi_genisligi_yerine_sutunu_alir(self):
        html = xfa_html.compile_template(self.SABLON).html
        # 120mm = 340.16pt; hücrenin kendi 30mm'i yok sayılmalı.
        assert "340.157pt" in self._stil(html, "h1")
        assert "56.693pt" in self._stil(html, "h2")

    def test_baslik_ve_veri_satiri_ayni_genisligi_paylasir(self):
        html = xfa_html.compile_template(self.SABLON).html
        assert self._stil(html, "b1").count("340.157pt") >= 2
        assert self._stil(html, "b1")[:40] == self._stil(html, "h1")[:40]

    def test_colspan_sutunlari_toplar(self):
        sablon = _sablon(
            '<subform name="T" layout="table" columnWidths="10mm 20mm 30mm">'
            '<subform name="S" layout="row">'
            '<field name="genis" colSpan="2"><ui><textEdit/></ui></field>'
            '<field name="dar"><ui><textEdit/></ui></field>'
            "</subform></subform>"
        )
        html = xfa_html.compile_template(sablon).html
        assert "85.039pt" in self._stil(html, "genis")     # 10+20 mm
        assert "85.039pt" in self._stil(html, "dar")       # 30 mm

    def test_ic_ice_tablo_dis_sutunlari_kullanmaz(self):
        """Hücrenin içindeki satır, dıştaki tablonun sütunlarını almamalı."""
        sablon = _sablon(
            '<subform name="Dis" layout="table" columnWidths="150mm">'
            '<subform name="DisSatir" layout="row">'
            '<subform name="Hucre" layout="row">'
            '<field name="ic" w="12mm"><ui><textEdit/></ui></field>'
            "</subform></subform></subform>"
        )
        html = xfa_html.compile_template(sablon).html
        assert "34.016pt" in self._stil(html, "ic")        # kendi 12mm'si
        assert "425.197pt" not in self._stil(html, "ic")


# ======================================================================
# Gömülü yazı tipleri
# ======================================================================
class TestGomuluYaziTipi:
    """PDF'e gömülü yazı tipi kullanılmazsa metin genişlikleri sapıyor.

    Foxit/Adobe formu gömülü Myriad Pro ile çizer; Arial'e düşülünce satırlar
    ~%6 uzuyor, etiketler sarıp taşıyor ve tablo başlıkları kayıyordu.
    """

    def test_postscript_adi_css_ailesine_cevrilir(self):
        assert xfa._css_font_name("MyriadPro-Regular") == ("Myriad Pro", 400, "normal")
        assert xfa._css_font_name("ABCDEF+MyriadPro-Bold") == ("Myriad Pro", 700, "normal")
        assert xfa._css_font_name("TimesNewRomanPSMT") == ("Times New Roman", 400, "normal")
        assert xfa._css_font_name("ArialMT") == ("Arial", 400, "normal")

    def test_sfnt_tablolari_dorde_hizalanir(self):
        """Tarayıcının doğrulayıcısı hizasız tabloyu reddediyor.

        ``OTS parsing error: CFF : misaligned table`` -> ``@font-face``
        sessizce düşüyor ve sayfa sistem yazı tipine geri dönüyordu.
        """
        import struct

        govde_a, govde_b = b"AAA", b"BBBBB"          # 3 ve 5 bayt: hizasız
        ham = (b"OTTO" + struct.pack(">HHHH", 2, 16, 0, 16)
               + struct.pack(">4sIII", b"CFF ", 0, 44, len(govde_a))
               + struct.pack(">4sIII", b"DSIG", 0, 47, len(govde_b))
               + govde_a + govde_b)
        yeni = xfa._repack_sfnt(ham)

        sayi = struct.unpack(">H", yeni[4:6])[0]
        assert sayi == 1, "DSIG yeniden yerleşimden sonra geçersiz; atılmalı"
        etiket, _, konum, boy = struct.unpack(">4sIII", yeni[12:28])
        assert etiket == b"CFF "
        assert konum % 4 == 0
        assert yeni[konum:konum + boy] == govde_a

    def test_bozuk_veri_oldugu_gibi_doner(self):
        assert xfa._repack_sfnt(b"OTTO\x00\x09") == b"OTTO\x00\x09"

    def test_sablonun_kullanmadigi_aile_gomulmez(self):
        assert xfa.template_typefaces(
            b'<font typeface="Myriad Pro"/><font typeface="Courier New"/>'
        ) == {"myriad pro", "courier new"}

    def test_font_kurallari_stile_girer(self):
        kural = "@font-face{font-family:'X';src:url(data:font/opentype;base64,AA)}"
        html = xfa_html.compile_template(_sablon(""), font_css=kural).html
        assert kural in html
        assert html.index(kural) < html.index("<body>")


# ======================================================================
# Veri yolu (datasets)
# ======================================================================
class TestYinelenenSatirVerisi:
    def test_dizinli_yollar_kardes_dugum_uretir(self):
        veri = xfa.build_datasets({
            "form.Tablo.satir[0].ad": "Ali",
            "form.Tablo.satir[1].ad": "Ayşe",
            "form.Tablo.satir[1].soyad": "Yılmaz",
        }).decode("utf-8")
        assert veri.count("<satir>") == 2
        assert "<ad>Ali</ad>" in veri and "<ad>Ayşe</ad>" in veri
        assert "<soyad>Yılmaz</soyad>" in veri

    def test_okuma_yazma_gidis_donus(self):
        degerler = {
            "form.Kisi.ad": "Ali",
            "form.Tablo.satir[0].kod": "A",
            "form.Tablo.satir[1].kod": "B",
        }
        assert xfa.read_values(xfa.build_datasets(degerler)) == degerler

    def test_tek_ornek_dizinsiz_kalir(self):
        """Tek satırlı tablo dizinsiz yazılır; gereksiz dizin yolu bozar."""
        okunan = xfa.read_values(xfa.build_datasets({"form.T.satir.kod": "A"}))
        assert okunan == {"form.T.satir.kod": "A"}


# ======================================================================
# Dayanıklı açma
# ======================================================================
class TestDayanikliAcma:
    def test_saglam_dosya_onarim_gerektirmez(self, sample_pdf):
        from app.core.document import open_tolerant
        belge, onarildi = open_tolerant(str(sample_pdf))
        try:
            assert belge.page_count > 0 and onarildi is False
        finally:
            belge.close()

    def test_basliktan_once_cop_olan_dosya_acilir(self, sample_pdf, tmp_path):
        """İndirme artığı/e-posta üstbilgisi eklenmiş PDF'ler yaygın."""
        from app.core.document import open_tolerant
        bozuk = tmp_path / "onek.pdf"
        bozuk.write_bytes(b"HTTP/1.1 200 OK\r\n\r\n" + Path(sample_pdf).read_bytes())
        belge, _ = open_tolerant(str(bozuk))
        try:
            assert belge.page_count > 0
        finally:
            belge.close()

    def test_kirpik_dosya_onarilarak_acilir(self, sample_pdf, tmp_path):
        from app.core.document import open_tolerant
        kirpik = tmp_path / "kirpik.pdf"
        kirpik.write_bytes(Path(sample_pdf).read_bytes()[:-300])
        belge, onarildi = open_tolerant(str(kirpik))
        try:
            assert belge.page_count > 0
            assert onarildi is True
        finally:
            belge.close()

    def test_yanlis_uzantili_pdf_acilir(self, sample_pdf, tmp_path):
        from app.core.document import open_tolerant
        sahte = tmp_path / "belge.txt"
        sahte.write_bytes(Path(sample_pdf).read_bytes())
        belge, _ = open_tolerant(str(sahte))
        try:
            assert belge.page_count > 0 and belge.is_pdf
        finally:
            belge.close()

    def test_gorsel_pdfe_cevrilir_ve_yol_dusurulur(self, tmp_path):
        """PNG açılabilir olmalı ama "Kaydet" görselin üzerine yazmamalı."""
        import pymupdf
        from app.core.document import PdfDocument

        gorsel = pymupdf.open()
        sayfa = gorsel.new_page(width=120, height=80)
        sayfa.draw_rect(pymupdf.Rect(5, 5, 115, 75), fill=(0, 0, 1))
        yol = tmp_path / "kare.png"
        yol.write_bytes(sayfa.get_pixmap().tobytes("png"))
        gorsel.close()

        belge = PdfDocument()
        belge.open(str(yol))
        try:
            assert belge.page_count == 1
            assert belge.was_repaired is True
            assert belge.path is None, "kaynak görselin üzerine yazılmamalı"
            assert belge.is_dirty is True
        finally:
            belge.close()

    def test_tanimsiz_icerik_anlasilir_hata_verir(self, tmp_path):
        """Rastgele baytlar ayrıştırıcıları çökertmeden reddedilmeli."""
        from app.core.document import PdfError, open_tolerant
        cop = tmp_path / "cop.bin"
        cop.write_bytes(bytes(range(256)) * 20)
        with pytest.raises(PdfError):
            open_tolerant(str(cop))

    def test_bos_dosya_reddedilir(self, tmp_path):
        from app.core.document import PdfError, open_tolerant
        bos = tmp_path / "bos.pdf"
        bos.write_bytes(b"")
        with pytest.raises(PdfError):
            open_tolerant(str(bos))


# ======================================================================
# Uçtan uca (tarayıcı motoruyla)
# ======================================================================
webengine = pytest.importorskip(
    "PySide6.QtWebEngineWidgets", reason="QtWebEngine kurulu değil")


class TestCanliMotor:
    """Formun gerçekten çalıştığını doğrular: betik, gösterme/gizleme, değerler."""

    @staticmethod
    def _yukle(qapp, sablon, degerler=None):
        from app.ui.xfa_view import XfaFormView

        gorunum = XfaFormView()
        hazir = {"ok": False}
        gorunum.formReady.connect(lambda *_: hazir.update(ok=True))
        gorunum.load_template(sablon, degerler or {})
        for _ in range(600):
            qapp.processEvents()
            if hazir["ok"]:
                break
            _bekle(50)
        assert hazir["ok"], "form görünümü hazır olmadı"
        return gorunum

    @staticmethod
    def _js(qapp, gorunum, kod, sure=4000):
        sonuc = {}
        gorunum.web.page().runJavaScript(kod, lambda r: sonuc.setdefault("v", r))
        for _ in range(sure // 50):
            qapp.processEvents()
            if "v" in sonuc:
                return sonuc["v"]
            _bekle(50)
        pytest.fail(f"JavaScript yanıt vermedi: {kod[:60]}")

    def test_secim_bagimli_bolum_acilir(self, qapp, kosullu_sablon):
        gorunum = self._yukle(qapp, kosullu_sablon)
        try:
            gizli = self._js(qapp, gorunum, GIZLI_MI)
            assert gizli == "hidden"
            self._js(qapp, gorunum, TIKLA_KURUM)
            assert self._js(qapp, gorunum, GIZLI_MI) == "visible"
        finally:
            gorunum.deleteLater()

    def test_doldurulan_degerler_okunur(self, qapp, kosullu_sablon):
        gorunum = self._yukle(qapp, kosullu_sablon)
        try:
            self._js(qapp, gorunum, TIKLA_KURUM)
            self._js(qapp, gorunum, YAZ_UNVAN)
            degerler = gorunum.values_blocking()
            assert degerler.get("form.Bolum.Tur") == "K"
            assert degerler.get("form.Bolum.Kurumsal.unvan") == "Genel Müdür"
        finally:
            gorunum.deleteLater()

    def test_kayitli_deger_geri_yuklenir(self, qapp, kosullu_sablon):
        """Dolu form yeniden açıldığında seçime bağlı bölüm de açılmalı."""
        gorunum = self._yukle(qapp, kosullu_sablon, {"form.Bolum.Tur": "K"})
        try:
            assert self._js(qapp, gorunum, GIZLI_MI) == "visible"
        finally:
            gorunum.deleteLater()

    def test_gecersiz_bicimde_uyari_kutusu_cikar(self, qapp, dogrulama_sablonu,
                                                 monkeypatch):
        """``app.alert`` kutuda gösterilmeli, durum çubuğunda kaybolmamalı."""
        from PySide6.QtWidgets import QMessageBox

        kutular: list = []
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: kutular.append(a[2])))

        gorunum = self._yukle(qapp, dogrulama_sablonu)
        try:
            # Köprü kurulmadan ``app.alert`` şeride düşer; önce beklenir.
            for _ in range(60):
                if self._js(qapp, gorunum, "!!window.xfaHost"):
                    break
                _bekle(50)
            else:
                pytest.fail("xfaHost köprüsü kurulmadı")

            # Geçersiz değer yaz ve alandan çık (offscreen'de blur() yetmiyor,
            # focusout açıkça gönderilir).
            self._js(qapp, gorunum, """
                (function () {
                  var g = document.querySelector('[data-som="form.Iletisim.eposta"]');
                  var alan = g.querySelector('input');
                  alan.focus();
                  alan.value = 'ASDASDASD';
                  alan.dispatchEvent(new Event('input', {bubbles: true}));
                  alan.blur();
                  alan.dispatchEvent(new Event('focusout', {bubbles: true}));
                  return 'ok';
                })()
            """)
            for _ in range(40):
                qapp.processEvents()
                if kutular:
                    break
                _bekle(50)
            assert kutular, "Geçersiz biçimde uyarı kutusu gösterilmeli"
            assert "Gecersiz bicim" in kutular[0]

            # Betik alanı boşaltmış olmalı (Foxit de böyle yapıyor)
            kalan = self._js(qapp, gorunum, """
                document.querySelector('[data-som="form.Iletisim.eposta"] input').value
            """)
            assert kalan == "", "Geçersiz değer temizlenmeli"
        finally:
            gorunum.deleteLater()

    def test_eklenen_tablo_satiri_yan_yana_kalir(self, qapp, tablo_sablonu):
        """Satır klonu ``display:flex``ini korumalı.

        Örnek eklenirken ``style.display`` sıfırlanıyordu; ``layout="row"``
        alt formunun satır düzeni de bu bildirimde durduğu için eklenen
        satırın hücreleri alt alta düşüyordu (Foxit'te yan yana duruyor).
        """
        gorunum = self._yukle(qapp, tablo_sablonu)
        try:
            olc = """
            (function () {
              var sec = '[data-som="form.T.satir"]';
              var hepsi = document.querySelectorAll(sec);
              var son = hepsi[hepsi.length - 1];
              var c = son.children;
              var ilk = c[0].getBoundingClientRect();
              var sonr = c[c.length - 1].getBoundingClientRect();
              return JSON.stringify({
                sayi: hepsi.length,
                display: getComputedStyle(son).display,
                ayni_satir: Math.abs(ilk.top - sonr.top) < 6,
                yan_yana: sonr.left > ilk.right - 2
              });
            })()
            """
            once = json.loads(self._js(qapp, gorunum, olc))
            assert once["sayi"] == 1
            assert once["display"] == "flex"

            # Şablonun kendi "+" düğmesine bas
            self._js(qapp, gorunum, """
                (function () {
                  var d = document.querySelectorAll('button.xbtn');
                  for (var i = 0; i < d.length; i++) {
                    if (d[i].textContent.trim() === '+') { d[i].click(); return 'ok'; }
                  }
                  return 'dugme yok';
                })()
            """)
            for _ in range(20):
                sonra = json.loads(self._js(qapp, gorunum, olc))
                if sonra["sayi"] > 1:
                    break
                _bekle(50)
            assert sonra["sayi"] == 2, "satır eklenmeli"
            assert sonra["display"] == "flex", (
                "eklenen satır flex kalmalı; block olursa hücreler alt alta düşer"
            )
            assert sonra["ayni_satir"], "hücreler aynı satırda olmalı"
            assert sonra["yan_yana"], "hücreler yan yana dizilmeli"
        finally:
            gorunum.deleteLater()

    def test_yazdirma_kipinde_sayfalar_bosluksuz_dizilir(self, qapp,
                                                        kosullu_sablon):
        """Kayma regresyonu: ekrandaki sayfa aralığı çıktıya sızmamalı.

        Sayfa çerçeveleri yalnızca oluşturulurken konumlandırılırsa yazdırma
        kipinde eski aralıkta kalır; kayma sayfa başına birikip altbilgileri
        sonraki sayfanın tepesine taşırdı.
        """
        gorunum = self._yukle(qapp, kosullu_sablon)
        try:
            self._js(qapp, gorunum, TIKLA_KURUM)      # uzun bölüm açılır
            # Ekran yerleşimi (aralıklı) **tamamlanmadan** yazdırma kipine
            # geçilirse çerçeveler zaten sıfırdan kurulur ve kayma hiç
            # oluşmaz; hatayı yakalamak için önce o yerleşim beklenir.
            for _ in range(40):
                if int(self._js(qapp, gorunum, "window.XFA.pageCount()") or 1) >= 2:
                    break
                _bekle(50)
            else:
                pytest.fail("ekran sayfalaması iki sayfaya çıkmadı")

            self._js(qapp, gorunum, "window.XFA.prepareForPrint()")
            ustler = json.loads(self._js(qapp, gorunum, SAYFA_USTLERI) or "[]")
            yukseklik = float(self._js(qapp, gorunum, "window.XFA_CONFIG.page.h"))
            assert len(ustler) >= 2, "çok sayfalı durum sınanmalı"
            for i, ust in enumerate(ustler):
                assert abs(float(ust) - i * yukseklik) < 0.5
        finally:
            self._js(qapp, gorunum, "window.XFA.endPrint()")
            gorunum.deleteLater()


GIZLI_MI = (
    "document.querySelector('[data-som=\"form.Bolum.Kurumsal\"]')"
    ".dataset.presence"
)
TIKLA_KURUM = (
    "document.querySelector('[data-som=\"form.Bolum.Tur.Kurum\"] input')"
    ".click(); 'ok'"
)
#: JSON metni olarak alınır: WebEngine bu köprüde dizi/nesne dönüşümünde
#: boş değer üretebiliyor (bkz. XfaFormView._run_values_js).
SAYFA_USTLERI = (
    "JSON.stringify(Array.from(document.querySelectorAll('#pagebg .page'))"
    ".map(function (p) { return parseFloat(p.style.top); }))"
)
YAZ_UNVAN = (
    "var f = document.querySelector("
    "'[data-som=\"form.Bolum.Kurumsal.unvan\"] input');"
    "f.value = 'Genel Müdür'; 'ok'"
)


def _bekle(ms: int = 20) -> None:
    """Tarayıcı motoruna nefes aldırır (yükleme/JS yanıtı arka planda gelir)."""
    from PySide6.QtCore import QThread
    QThread.msleep(min(ms, 50))
