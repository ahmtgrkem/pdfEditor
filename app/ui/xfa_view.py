"""Dinamik XFA formlarının canlı görünümü.

Dinamik XFA'da form, sayfa akışında değil gömülü bir XML şablonunda durur ve
davranışı JavaScript'le tanımlanır: seçime göre açılan bölümler, tabloya satır
ekleme, ülkeye göre dolan listeler, alan doğrulamaları. Bunları çizmek değil
**çalıştırmak** gerekir; bu yüzden şablon HTML'e derlenip (:mod:`app.core.
xfa_html`) gerçek bir tarayıcı motorunda gösterilir.

Görünümün sorumluluğu: motoru kurmak, betiklerin ``app.alert`` çağrılarını
uygulamanın kendi kutularına bağlamak, doldurulan değerleri geri okumak ve
görünenin birebir aynısını PDF'e basmak.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMarginsF, QObject, QSizeF, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPageLayout, QPageSize
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

from ..core import xfa_html
from . import theme

#: Yakınlaştırma sınırları
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0


def _birlestir(parcalar: list[bytes], path: str) -> bool:
    """Sayfa sayfa basılmış PDF'leri tek dosyada birleştirir."""
    if not parcalar:
        return False
    try:
        import pymupdf

        hedef = pymupdf.open()
        try:
            for veri in parcalar:
                with pymupdf.open(stream=veri, filetype="pdf") as tek:
                    # Her parça tek sayfalık olmalı; fazlası boş taşma sayfasıdır.
                    hedef.insert_pdf(tek, from_page=0, to_page=0)
            hedef.save(path, deflate=True, garbage=3)
        finally:
            hedef.close()
    except Exception:  # noqa: BLE001 - yazma/birleştirme hatası
        return False
    return True


class _Host(QObject):
    """Sayfadaki betiklerin uygulamaya ulaştığı köprü."""

    alerted = Signal(str)
    printRequested = Signal()
    edited = Signal()
    pagesChanged = Signal(int)

    @Slot(str)
    def alert(self, message: str) -> None:
        self.alerted.emit(message)

    @Slot(str)
    def openUrl(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    @Slot()
    def printDoc(self) -> None:
        self.printRequested.emit()

    @Slot()
    def dirty(self) -> None:
        self.edited.emit()

    @Slot(int)
    def pages(self, count: int) -> None:
        self.pagesChanged.emit(count)


class _Page(QWebEnginePage):
    """Konsol iletilerini yutmayan, dış bağlantıları tarayıcıya veren sayfa."""

    consoleMessage = Signal(str)

    def javaScriptConsoleMessage(self, level, message, line, source) -> None:
        # Şablon betikleri hatalıysa sessizce kaybolmasın; tanı için taşınır.
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.consoleMessage.emit(message)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame) -> bool:
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class XfaFormView(QWidget):
    """XFA formunu etkileşimli gösteren görünüm."""

    #: Form yüklendi: (alan sayısı, sayfa sayısı)
    formReady = Signal(int, int)
    #: Kullanıcı bir alanı değiştirdi
    contentChanged = Signal()
    #: Durum çubuğu iletisi
    status = Signal(str)
    #: Sayfa sayısı değişti (bölüm açılıp kapandıkça değişir)
    pageCountChanged = Signal(int)
    #: Kullanıcı formu statik (çizilebilir) sayfaya dönüştürmek istedi
    staticRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._zoom = 1.0
        self._field_count = 0
        self._page_count = 1
        self._loaded = False
        #: Şablonun bildirdiği sayfa ölçüsü (punto) — PDF çıktısı buna basılır
        self._page_size = (595.28, 841.89)

        self.web = QWebEngineView(self)
        self._page = _Page(self.web)
        self.web.setPage(self._page)

        ayarlar = self._page.settings()
        ayarlar.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        ayarlar.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        ayarlar.setAttribute(
            QWebEngineSettings.WebAttribute.ShowScrollBars, True)
        ayarlar.setAttribute(
            QWebEngineSettings.WebAttribute.PrintElementBackgrounds, True)

        # Son bilinen değerler. Kaydetme yolu, motordan eşzamanlı okuma
        # başarısız olursa buna düşer; her düzenlemeden sonra tazelenir.
        self._values: dict[str, str] = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._refresh_values)

        self.host = _Host(self)
        self.host.alerted.connect(self._on_alert)
        self.host.edited.connect(self._on_edited)
        self.host.pagesChanged.connect(self._on_pages_changed)
        self._channel = QWebChannel(self)
        self._channel.registerObject("xfaHost", self.host)
        self._page.setWebChannel(self._channel)
        self._inject_channel_bootstrap()

        self._page.loadFinished.connect(self._on_load_finished)
        self._page.consoleMessage.connect(
            lambda m: self.status.emit(f"Form betiği uyarısı: {m}")
        )

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(0, 0, 0, 0)
        yerlesim.setSpacing(0)
        yerlesim.addWidget(self._bilgi_seridi(), 0)
        yerlesim.addWidget(self.web, 1)

    # ------------------------------------------------------------------
    def _bilgi_seridi(self) -> QWidget:
        """Araçların neden çalışmadığını anlatan ve çıkış yolu sunan şerit.

        Etkileşimli formda açıklama/çizim araçları kapalıdır: belge akışı
        yalnızca "Adobe gerekli" uyarı sayfasıdır, çizim onu değiştirir,
        formu değil. Kullanıcı bunu araç çubuğundaki solgun düğmelerden
        anlayamıyordu; şerit hem nedeni hem çözümü söylüyor.
        """
        p = theme.current()
        self.notice = QWidget(self)
        self.notice.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.notice.setStyleSheet(
            f"background: {p.surface_alt}; border-bottom: 1px solid {p.border};"
        )
        etiket = QLabel(
            "Etkileşimli form görünümü — alanları doldurabilirsiniz; "
            "çizim ve açıklama araçları bu görünümde çalışmaz.",
            self.notice,
        )
        etiket.setWordWrap(True)
        etiket.setStyleSheet(f"color: {p.text}; border: none;")
        dugme = QPushButton("Çizilebilir sayfaya dönüştür", self.notice)
        dugme.setToolTip(
            "Formu, üzerine metin/çizim ekleyebileceğiniz statik bir PDF'e "
            "dönüştürür (Araçlar ▸ Formu görüntüle ile aynı)."
        )
        dugme.clicked.connect(self.staticRequested)

        satir = QHBoxLayout(self.notice)
        satir.setContentsMargins(12, 7, 12, 7)
        satir.setSpacing(12)
        satir.addWidget(etiket, 1)
        satir.addWidget(dugme)
        return self.notice

    def refresh_theme(self) -> None:
        """Tema değişince şeridin renklerini tazeler."""
        p = theme.current()
        self.notice.setStyleSheet(
            f"background: {p.surface_alt}; border-bottom: 1px solid {p.border};"
        )
        for etiket in self.notice.findChildren(QLabel):
            etiket.setStyleSheet(f"color: {p.text}; border: none;")

    # ------------------------------------------------------------------
    # Kurulum
    # ------------------------------------------------------------------
    def _inject_channel_bootstrap(self) -> None:
        """``qwebchannel.js``i sayfaya enjekte edip köprüyü kurar.

        Köprü kurulana kadar çalışma zamanı ``app.alert``i kendi bildirim
        şeridine düşürür; yani gecikme bir şeyi bozmaz.
        """
        try:
            from PySide6.QtCore import QFile, QIODevice
            dosya = QFile(":/qtwebchannel/qwebchannel.js")
            if not dosya.open(QIODevice.ReadOnly):
                return
            kaynak = bytes(dosya.readAll()).decode("utf-8")
            dosya.close()
        except Exception:  # noqa: BLE001 - kaynak yoksa köprüsüz çalışır
            return

        betik = QWebEngineScript()
        betik.setName("xfa-channel")
        betik.setSourceCode(
            kaynak
            + "\nnew QWebChannel(qt.webChannelTransport, function (channel) {"
              "  window.xfaHost = channel.objects.xfaHost;"
              "  window.__xfaDirty = function () { window.xfaHost.dirty(); };"
              "  window.__xfaOnPages = function (n) { window.xfaHost.pages(n); };"
              "});"
        )
        betik.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        betik.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        betik.setRunsOnSubFrames(False)
        self._page.scripts().insert(betik)

    # ------------------------------------------------------------------
    # Yükleme
    # ------------------------------------------------------------------
    def load_template(self, template: bytes,
                      values: dict[str, str] | None = None,
                      font_css: str = "") -> int:
        """Şablonu derleyip gösterir; doldurulabilir alan sayısını döndürür."""
        derlenmis = xfa_html.compile_template(template, values or {},
                                              font_css=font_css)
        self._field_count = derlenmis.field_count
        self._page_size = derlenmis.page_size
        self._loaded = False
        self.web.setHtml(derlenmis.html, QUrl("xfa:///form"))
        return derlenmis.field_count

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self.status.emit("Form görünümü yüklenemedi.")
            return
        self._loaded = True
        self.web.page().runJavaScript(
            "window.XFA ? window.XFA.pageCount() : 0", self._on_pages_ready
        )

    def _on_pages_ready(self, count) -> None:
        self._page_count = int(count or 1)
        self.formReady.emit(self._field_count, self._page_count)
        self.pageCountChanged.emit(self._page_count)

    def _on_edited(self) -> None:
        self.contentChanged.emit()
        self._refresh_timer.start()

    def _refresh_values(self) -> None:
        """Değer önbelleğini arka planda tazeler (``preSave`` çalıştırmadan)."""
        if not self._loaded:
            return
        self._run_values_js(self._values.update, run_presave=False)

    def _on_pages_changed(self, count: int) -> None:
        """Bölümler açılıp kapandıkça form uzar/kısalır; sayfa sayısı değişir."""
        if count and count != self._page_count:
            self._page_count = count
            self.pageCountChanged.emit(count)

    # ------------------------------------------------------------------
    # Veri
    # ------------------------------------------------------------------
    def _run_values_js(self, callback, run_presave: bool) -> None:
        """Değerleri JSON metni olarak okur.

        Metin kullanılır: WebEngine'in JS nesnesi -> Python dönüşümü bu
        köprüde boş sözlük üretebiliyor.
        """
        def cozumle(ham) -> None:
            try:
                veri = json.loads(ham) if ham else {}
            except (TypeError, ValueError):
                veri = {}
            callback({str(k): str(v) for k, v in veri.items()})

        on_hazirlik = "try { window.XFA.preSave(); } catch(e) {}" if run_presave else ""
        self.web.page().runJavaScript(
            f"(function(){{ {on_hazirlik} "
            "return JSON.stringify(window.XFA.values()); })()",
            cozumle,
        )

    def collect_values(self, callback) -> None:
        """Doldurulan değerleri ``{SOM yolu: değer}`` olarak okur (eşzamansız)."""
        if not self._loaded:
            callback(dict(self._values))
            return

        def kaydet(degerler: dict) -> None:
            if degerler:
                self._values = degerler
            callback(dict(self._values))

        self._run_values_js(kaydet, run_presave=True)

    def values_blocking(self, timeout_ms: int = 4000) -> dict[str, str]:
        """Değerleri bekleyerek okur.

        Kaydetme akışı eşzamanlı (``Ctrl+S`` -> yaz -> başlığı tazele) olduğu
        için burada kısa bir yerel olay döngüsüyle beklenir; motor yanıt
        vermezse boş sözlükle geri dönülür ve kaydetme yine de sürer.

        Döngü **bütün** olayları işler: WebEngine'in JavaScript geri çağrıları
        kullanıcı girdisi dışlandığında teslim edilmiyor ve değerler boş
        dönüyordu.
        """
        from PySide6.QtCore import QEventLoop, QTimer

        sonuc: dict[str, str] = {}
        bitti = {"ok": False}
        dongu = QEventLoop(self)

        def geldi(degerler: dict) -> None:
            sonuc.update(degerler)
            bitti["ok"] = True
            dongu.quit()

        self.collect_values(geldi)
        if bitti["ok"]:
            return sonuc
        QTimer.singleShot(timeout_ms, dongu.quit)
        dongu.exec()
        # Motor iç içe döngüde yanıt vermediyse son bilinen değerlerle devam
        # edilir; kaydetme sessizce boş veri yazmamalı.
        return sonuc or dict(self._values)

    def export_pdf_blocking(self, path: str, timeout_ms: int = 60000) -> bool:
        """:meth:`export_pdf`'i bekleyerek çalıştırır.

        Word'e aktarma eşzamanlı bir akış (yol seç -> yaz -> mesaj) olduğu
        için burada :meth:`values_blocking` ile aynı iç içe döngü kullanılır.
        """
        from PySide6.QtCore import QEventLoop, QTimer

        sonuc = {"ok": False}
        dongu = QEventLoop(self)

        def bitti(basarili: bool) -> None:
            sonuc["ok"] = bool(basarili)
            dongu.quit()

        self.export_pdf(path, bitti)
        QTimer.singleShot(timeout_ms, dongu.quit)
        dongu.exec()
        return sonuc["ok"]

    def export_pdf(self, path: str, callback) -> None:
        """Görünenin birebir aynısını PDF'e basar.

        Sayfa bölmesi tarayıcıya bırakılmaz: kendi sayfalamamızla Chromium'un
        sayfa kutuları birkaç punto kayıyor ve kayma sayfa başına birikerek
        altbilgileri sonraki sayfaya taşıyordu. Bunun yerine belge tek sayfa
        yüksekliğine kırpılır, her sayfa ayrı basılır ve sonuçlar birleştirilir.
        """
        if not self._loaded:
            callback(False)
            return

        genislik, yukseklik = self._page_size
        duzen = QPageLayout(
            QPageSize(QSizeF(genislik, yukseklik), QPageSize.Unit.Point),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
        )
        eski_zoom = self.web.zoomFactor()
        parcalar: list[bytes] = []

        def bitir(basarili: bool) -> None:
            self.web.setZoomFactor(eski_zoom)
            self.web.page().runJavaScript("window.XFA.endPrint()")
            callback(basarili)

        def sayfa_bas(indeks: int, toplam: int) -> None:
            if indeks >= toplam:
                bitir(_birlestir(parcalar, path))
                return

            def basildi(veri) -> None:
                bayt = bytes(veri)
                if not bayt:
                    bitir(False)
                    return
                parcalar.append(bayt)
                sayfa_bas(indeks + 1, toplam)

            self.web.page().runJavaScript(
                f"window.XFA.showPrintPage({indeks})",
                lambda _r: self.web.page().printToPdf(basildi, duzen),
            )

        def hazir(sayi) -> None:
            toplam = max(int(sayi or 1), 1)
            sayfa_bas(0, toplam)

        # Yakınlaştırma çıktı ölçeğini de değiştirir; basmadan önce sıfırlanır.
        self.web.setZoomFactor(1.0)
        self.web.page().runJavaScript("window.XFA.prepareForPrint()", hazir)

    # ------------------------------------------------------------------
    # Görünüm
    # ------------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float) -> None:
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, value))
        self.web.setZoomFactor(self._zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.25)

    def zoom_actual(self) -> None:
        self.set_zoom(1.0)

    def go_to_page(self, index: int) -> None:
        self.web.page().runJavaScript(f"window.XFA.gotoPage({int(index) + 1})")

    @property
    def page_count(self) -> int:
        return self._page_count

    def _on_alert(self, message: str) -> None:
        """Şablonun ``app.alert`` çağrıları uyarı kutusunda gösterilir.

        XFA'da ``app.alert`` kalıcı bir uyarı kutusudur; alan doğrulama
        iletileri (ör. "e-posta: geçersiz biçim") buradan gelir ve Adobe/Foxit
        bunları kutuda gösterir. Kısa iletiler durum çubuğuna yazıldığında
        kullanıcı uyarıyı hiç görmüyordu — form da alanı sessizce boşaltıyordu.
        """
        message = (message or "").strip()
        if not message:
            return
        self.status.emit(message)      # durum çubuğunda iz kalsın
        QMessageBox.warning(self, "Form", message)
