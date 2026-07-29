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
