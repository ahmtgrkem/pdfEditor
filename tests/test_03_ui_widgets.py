"""3. Arayüz (UI/UX) ve widget kontrolleri."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from app.core.annotations import TextStyle
from app.ui import theme
from app.ui.page_view import ViewMode, ZoomMode
from conftest import pump

#: Kasıtlı olarak serbest yazıma açık kutular — sayısal doğrulayıcı zorunlu
DUZENLENEBILIR_IZIN = {"zoomCombo", "dpiCombo"}


def combolari_topla(widget) -> list[QComboBox]:
    return widget.findChildren(QComboBox)


# ======================================================================
# 3.1 Açılır menü (ComboBox) kontrolleri
# ======================================================================
class TestComboBoxlar:
    def test_ana_pencere_combolari(self, opened):
        for combo in combolari_topla(opened):
            ad = combo.objectName()
            if combo.isEditable():
                assert ad in DUZENLENEBILIR_IZIN, (
                    f"'{ad or combo.currentText()}' kutusu serbest yazıma açık olmamalı"
                )
                assert combo.validator() is not None, (
                    f"'{ad}' düzenlenebilir ama girdi doğrulayıcısı yok"
                )

    @pytest.mark.parametrize("diyalog", ["watermark", "export", "compress",
                                         "split", "security"])
    def test_diyalog_combolari_salt_secim(self, opened, diyalog):
        from app.ui.dialogs import (CompressDialog, ExportImagesDialog, SecurityDialog,
                                    SplitDialog, WatermarkDialog)

        ctrl = opened.controller
        uretici = {
            "watermark": lambda: WatermarkDialog(ctrl.page_count, 0, opened),
            "export": lambda: ExportImagesDialog(ctrl.page_count, 0, ctrl.path, opened),
            "compress": lambda: CompressDialog(ctrl.path, 1024, opened),
            "split": lambda: SplitDialog(ctrl.page_count, ctrl.path, opened),
            "security": lambda: SecurityDialog(ctrl.path, opened),
        }[diyalog]
        dlg = uretici()
        try:
            for combo in combolari_topla(dlg):
                if combo.isEditable():
                    assert combo.objectName() in DUZENLENEBILIR_IZIN, (
                        f"{diyalog}: '{combo.objectName()}' serbest yazıma açık"
                    )
                    assert combo.validator() is not None
        finally:
            dlg.deleteLater()

    def test_zoom_kutusuna_harf_yazilamaz(self, opened):
        combo = opened.zoom_combo
        onceki = combo.currentText()
        combo.lineEdit().clear()
        QTest.keyClicks(combo.lineEdit(), "abc")
        assert combo.lineEdit().text() == "", "Harf girişi doğrulayıcı tarafından engellenmeli"
        combo.setCurrentText(onceki)

    def test_zoom_kutusuna_gecerli_deger_yazilabilir(self, opened, qapp):
        combo = opened.zoom_combo
        combo.lineEdit().clear()
        QTest.keyClicks(combo.lineEdit(), "137")
        QTest.keyClick(combo.lineEdit(), Qt.Key_Return)
        pump(qapp)
        assert abs(opened.view.zoom - 1.37) < 0.01
        assert opened.view.zoom_mode is ZoomMode.CUSTOM

    def test_gecersiz_deger_durumu_bozmaz(self, opened, qapp):
        opened.view.set_zoom(1.0)
        pump(qapp)
        opened._on_zoom_text("%%%")            # doğrudan bozuk girdi
        pump(qapp)
        assert abs(opened.view.zoom - 1.0) < 0.001
        assert opened.zoom_combo.currentText() == "%100"

    def test_dpi_kutusu_sadece_sayi_alir(self, opened):
        from app.ui.dialogs import ExportImagesDialog

        dlg = ExportImagesDialog(opened.controller.page_count, 0,
                                 opened.controller.path, opened)
        try:
            dlg.dpi.lineEdit().clear()
            QTest.keyClicks(dlg.dpi.lineEdit(), "abc")
            assert dlg.dpi.lineEdit().text() == ""
            QTest.keyClicks(dlg.dpi.lineEdit(), "300")
            assert dlg.dpi.lineEdit().text() == "300"
            assert dlg._dpi_value() == 300
        finally:
            dlg.deleteLater()


# ======================================================================
# 3.2 Araç çubukları, paneller, tema
# ======================================================================
class TestPanellerVeTema:
    def test_kenar_cubugu_gizlenip_acilir(self, opened, qapp):
        opened.toggle_sidebar(False)
        pump(qapp)
        assert not opened.dock.isVisible()
        assert opened._actions["sidebar"].isChecked() is False
        opened.toggle_sidebar(True)
        pump(qapp)
        assert opened.dock.isVisible()
        assert opened._actions["sidebar"].isChecked() is True

    def test_sekmeler_arasi_gecis(self, opened, qapp):
        for i, panel in enumerate((opened.thumbnails, opened.outline, opened.search)):
            opened.sidebar_tabs.setCurrentIndex(i)
            pump(qapp)
            assert opened.sidebar_tabs.currentWidget() is panel

    def test_tam_ekran_modu(self, opened, qapp):
        opened.toggle_fullscreen(True)
        pump(qapp, 10)
        assert opened.isFullScreen()
        opened.toggle_fullscreen(False)
        pump(qapp, 10)
        assert not opened.isFullScreen()

    def test_tema_degisiminde_renkler_tutarli(self, opened, qapp):
        onceki = theme.current().name
        onceki_ikon = opened._actions["save"].icon().pixmap(22, 22).toImage()

        opened.toggle_theme()
        pump(qapp)
        yeni = theme.current()
        assert yeni.name != onceki, "Tema gerçekten değişmeli"

        # tuval arka planı yeni paletle uyumlu mu
        assert opened.view.backgroundBrush().color().name().lower() == yeni.canvas.lower()
        # simgeler yeni tema rengiyle yeniden üretildi mi
        yeni_ikon = opened._actions["save"].icon().pixmap(22, 22).toImage()
        assert yeni_ikon != onceki_ikon, "Simgeler tema rengine göre yenilenmeli"
        # küçük resim paneli stil sayfası güncellendi mi
        assert yeni.accent.lower() in opened.thumbnails.list.styleSheet().lower()

        opened.toggle_theme()
        pump(qapp)
        assert theme.current().name == onceki

    def test_tema_degisimi_belgeyi_bozmaz(self, opened, qapp):
        sayfa = opened.controller.page_count
        opened.controller.add_text(0, (80.0, 300.0, 400.0, 340.0), "tema", TextStyle())
        opened.toggle_theme()
        pump(qapp, 10)
        assert opened.controller.page_count == sayfa
        assert "tema" in opened.controller.document.page_text(0)
        opened.toggle_theme()

    @pytest.mark.parametrize("tema", ["dark", "light"])
    def test_stil_sayfasi_bastan_sona_uygulanir(self, qapp, tema):
        """Gösterge görselleri dosyadan gelmeli ve kurallar düşmemeli.

        Qt'nin stil sayfasında ``url()`` yalnızca dosya yolu kabul eder;
        ``data:`` URI verildiğinde ayrıştırıcı o satırda bozulur ve
        **sonraki tüm kurallar sessizce düşer** — düğmeler, kaydırma
        çubukları, onay kutuları temasız kalır. Bu test hem göstergelerin
        dosyada olduğunu hem de sayfanın sonundaki kuralların hâlâ
        uygulandığını doğrular.
        """
        import os
        import re

        from PySide6.QtWidgets import QPushButton

        palet = theme.THEMES[tema]
        sayfa = theme.stylesheet(palet)

        assert "data:image" not in sayfa, "QSS 'data:' URI desteklemiyor"
        yollar = re.findall(r'url\("([^"]+)"\)', sayfa)
        assert yollar, "Gösterge görselleri tanımlanmalı"
        for yol in yollar:
            assert os.path.exists(yol), f"Gösterge dosyası yok: {yol}"

        # Kural sırasının sonundaki bir bildirim: sayfa baştan sona ayrıştıysa
        # vurgu düğmesi vurgu rengine boyanır.
        onceki = qapp.styleSheet()
        try:
            qapp.setStyleSheet(sayfa)
            dugme = QPushButton("Uygula")
            dugme.setProperty("accent", "true")
            dugme.resize(140, 34)
            dugme.show()
            pump(qapp)
            renk = dugme.grab().toImage().pixelColor(6, 17)
            dugme.close()
        finally:
            qapp.setStyleSheet(onceki)
        assert renk.name().lower() == palet.accent.lower(), (
            f"Vurgu düğmesi {palet.accent} olmalı, {renk.name()} çizildi — "
            "stil sayfasının son kuralları düşmüş olabilir"
        )

    def test_diyalogun_onay_dugmesi_vurgulu_cizilir(self, qapp):
        """Birincil eylem gerçekten vurgu renginde boyanmalı.

        ``accent`` özelliği yalnızca cilalama sırasında okunuyor; standart
        ``QDialogButtonBox`` düğmeleri kutunun kurucusunda cilalandığı için
        özellik hiç işlemiyordu (mavi görünüm ``:default``dan geliyordu, o da
        odağa göre yanlış düğmeye kayabiliyor).
        """
        from PySide6.QtWidgets import QDialogButtonBox

        from app.ui.dialogs.common import BaseDialog

        dialog = BaseDialog("Deneme", ok_text="Uygula")
        dialog.resize(320, 120)
        dialog.show()
        pump(qapp)
        onay = dialog.buttons.button(QDialogButtonBox.Ok)
        iptal = dialog.buttons.button(QDialogButtonBox.Cancel)
        assert onay.isDefault(), "Enter onay düğmesine gitmeli"
        assert not iptal.isDefault(), "İptal varsayılan düğme olmamalı"

        goruntu = onay.grab().toImage()
        renk = goruntu.pixelColor(6, goruntu.height() // 2)
        dialog.close()
        assert renk.name().lower() == theme.current().accent.lower(), (
            f"Onay düğmesi vurgu renginde olmalı, {renk.name()} çizildi"
        )

    def test_gorunum_modlari(self, opened, qapp):
        for mod, key in ((ViewMode.SINGLE, "view_single"),
                         (ViewMode.DOUBLE, "view_double"),
                         (ViewMode.CONTINUOUS, "view_continuous")):
            opened.set_view_mode(mod)
            pump(qapp)
            assert opened.view.view_mode is mod
            assert opened._actions[key].isChecked()


# ======================================================================
# 3.3 Klavye kısayolları
# ======================================================================
class TestKisayollar:
    def test_kisayollar_pencere_kapsamli(self, opened):
        """Odak nerede olursa olsun çalışması için kapsam WindowShortcut olmalı."""
        for key, action in opened._actions.items():
            if not action.shortcut().isEmpty():
                assert action.shortcutContext() == Qt.WindowShortcut, key

    @pytest.mark.parametrize("key,mod,beklenen", [
        (Qt.Key_Z, Qt.ControlModifier, "undo"),
        (Qt.Key_Y, Qt.ControlModifier, "redo"),
        (Qt.Key_S, Qt.ControlModifier, "save"),
        (Qt.Key_F, Qt.ControlModifier, "find"),
        (Qt.Key_B, Qt.ControlModifier, "sidebar"),
        (Qt.Key_T, Qt.ControlModifier, "theme"),
    ])
    def test_kisayol_odaktan_bagimsiz_tetiklenir(self, opened, qapp, monkeypatch,
                                                 key, mod, beklenen):
        tetiklenen = []
        action = opened._actions[beklenen]
        action.setEnabled(True)
        action.triggered.connect(lambda *_: tetiklenen.append(beklenen))

        # odak kenar çubuğundaki listede olsun
        opened.thumbnails.list.setFocus()
        pump(qapp)
        QTest.keyClick(opened.thumbnails.list, key, mod)
        pump(qapp)
        assert tetiklenen, f"{beklenen} kısayolu odak listedeyken de çalışmalı"

    def test_zoom_kisayollari(self, opened, qapp):
        opened.view.set_zoom(1.0)
        pump(qapp)
        opened._actions["zoom_in"].trigger()
        pump(qapp)
        assert opened.view.zoom > 1.0
        opened._actions["zoom_out"].trigger()
        opened._actions["zoom_out"].trigger()
        pump(qapp)
        assert opened.view.zoom < 1.0
        opened._actions["zoom_actual"].trigger()
        pump(qapp)
        assert abs(opened.view.zoom - 1.0) < 0.001

    def test_geri_al_yinele_zinciri(self, opened, qapp):
        ctrl = opened.controller
        onceki = ctrl.page_count
        ctrl.insert_blank(1)
        assert ctrl.page_count == onceki + 1
        opened._actions["undo"].trigger()
        pump(qapp)
        assert ctrl.page_count == onceki
        opened._actions["redo"].trigger()
        pump(qapp)
        assert ctrl.page_count == onceki + 1

    def test_ctrl_delete_sayfa_siler(self, opened, qapp, silence_dialogs):
        onceki = opened.controller.page_count
        opened.view.go_to_page(2)
        pump(qapp)
        opened._actions["page_delete"].trigger()
        pump(qapp)
        assert opened.controller.page_count == onceki - 1

    def test_son_sayfa_silinemez(self, window, qapp, silence_dialogs):
        window.controller.create_empty()
        pump(qapp)
        assert window.controller.page_count == 1
        assert not window._actions["page_delete"].isEnabled(), (
            "Tek sayfalı belgede sayfa silme pasif olmalı"
        )

    @pytest.mark.xfail(reason="Seçili açıklamayı Delete ile silme kısayolu yok",
                       strict=True)
    def test_delete_secili_nesneyi_siler(self, opened):
        assert "delete_selection" in opened._actions
