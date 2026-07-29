"""1. Dosya işlemleri ve sürükle-bırak testleri."""
from __future__ import annotations

import os

import pymupdf as fitz
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from app.core import exporter
from conftest import pump


# ----------------------------------------------------------------------
# Yardımcılar
# ----------------------------------------------------------------------
# QDropEvent, QMimeData'nın sahipliğini almaz; Python tarafında referans
# tutulmazsa nesne silinir ve mimeData() boş bir QObject döner.
_MIME_KEEPALIVE: list[QMimeData] = []


def _mime(paths: list[str]) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _MIME_KEEPALIVE.append(mime)
    return mime


def drag_enter(widget, paths: list[str]) -> QDragEnterEvent:
    event = QDragEnterEvent(
        QPoint(200, 200), Qt.CopyAction, _mime(paths), Qt.LeftButton, Qt.NoModifier
    )
    widget.dragEnterEvent(event)
    return event


def drop(widget, paths: list[str], app) -> QDropEvent:
    event = QDropEvent(
        QPointF(200, 200), Qt.CopyAction, _mime(paths), Qt.LeftButton, Qt.NoModifier
    )
    widget.dropEvent(event)
    pump(app, 12)          # dropEvent açmayı QTimer ile kuyruğa alır
    return event


# ======================================================================
# 1.1 Sürükle-bırak
# ======================================================================
class TestDragDrop:
    def test_pdf_surukleyince_kabul_edilir(self, window, sample_pdf):
        event = drag_enter(window, [str(sample_pdf)])
        assert event.isAccepted(), "PDF sürüklendiğinde imleç kabul göstermeli"

    def test_pdf_disi_dosya_reddedilir(self, window, sample_png):
        event = drag_enter(window, [str(sample_png)])
        assert not event.isAccepted(), "PDF olmayan dosya kabul edilmemeli"

    def test_birakinca_belge_acilir(self, window, sample_pdf, qapp):
        drop(window, [str(sample_pdf)], qapp)
        assert window.controller.is_open
        assert window.controller.page_count == 6
        assert os.path.basename(window.controller.path) == "ornek.pdf"

    def test_acik_belge_uzerine_birakinca_degisir(self, opened, second_pdf, qapp):
        assert opened.controller.page_count == 6
        drop(opened, [str(second_pdf)], qapp)
        assert opened.controller.page_count == 3
        assert os.path.basename(opened.controller.path) == "ikinci.pdf"

    def test_kaydedilmemis_degisiklikte_uyarir(self, opened, second_pdf, qapp,
                                              silence_dialogs):
        opened.controller.rotate([0], 90)          # belgeyi kirlet
        assert opened.controller.is_dirty
        drop(opened, [str(second_pdf)], qapp)
        kinds = [c[0] for c in silence_dialogs["message"]]
        assert "question" in kinds, "Kaydedilmemiş değişiklik uyarısı çıkmalı"

    def test_coklu_surukleme_ilk_pdfi_acar(self, window, sample_pdf, second_pdf, qapp):
        drop(window, [str(sample_pdf), str(second_pdf)], qapp)
        assert os.path.basename(window.controller.path) == "ornek.pdf"


# ======================================================================
# 1.2 Farklı formatlarda kaydetme / dışa aktarma
# ======================================================================
class TestExportFormats:
    def test_pdf_olarak_kaydet(self, opened, tmp_path):
        target = tmp_path / "kopya.pdf"
        opened.controller.save(str(target))
        assert target.exists() and target.stat().st_size > 0
        doc = fitz.open(str(target))
        assert doc.page_count == 6
        doc.close()
        assert not opened.controller.is_dirty, "Kayıttan sonra kirli bayrağı kalkmalı"

    @pytest.mark.parametrize("fmt,uzanti", [("PNG", ".png"), ("JPG", ".jpg"),
                                            ("TIFF", ".tif"), ("BMP", ".bmp")])
    def test_gorsel_olarak_disa_aktar(self, opened, tmp_path, fmt, uzanti):
        out = tmp_path / fmt.lower()
        written = exporter.export_images(
            opened.controller.document,
            exporter.ImageExportOptions(out_dir=str(out), fmt=fmt, dpi=72, pages=[0, 1]),
        )
        assert len(written) == 2
        for path in written:
            assert path.endswith(uzanti) and os.path.getsize(path) > 0

    def test_cok_sayfali_tiff(self, opened, tmp_path):
        written = exporter.export_images(
            opened.controller.document,
            exporter.ImageExportOptions(out_dir=str(tmp_path / "tif"), fmt="TIFF",
                                        dpi=72, multipage_tiff=True),
        )
        assert len(written) == 1, "Çok sayfalı TIFF tek dosya olmalı"
        from PIL import Image
        with Image.open(written[0]) as img:
            assert img.n_frames == 6

    def test_metin_olarak_disa_aktar(self, opened, tmp_path):
        target = tmp_path / "belge.txt"
        exporter.export_text(opened.controller.document, str(target))
        icerik = target.read_text(encoding="utf-8")
        assert "Sayfa 1" in icerik and "Sayfa 6" in icerik
        assert "şığĞÜÖİı" in icerik, "Türkçe karakterler bozulmamalı"

    def test_menu_eylemleri_belge_acikken_etkin(self, opened):
        for key in ("save", "save_as", "export_images", "export_text", "print"):
            assert opened._actions[key].isEnabled(), f"{key} etkin olmalı"

    def test_menu_eylemleri_belge_yokken_pasif(self, window):
        for key in ("save", "save_as", "export_images", "export_text", "print"):
            assert not window._actions[key].isEnabled(), f"{key} pasif olmalı"

    @pytest.mark.xfail(reason="OCR/aranabilir PDF üretimi henüz uygulanmadı", strict=True)
    def test_aranabilir_pdf_olarak_kaydet(self, opened, tmp_path):
        # Beklenen: taranmış (görsel) PDF'e OCR metin katmanı eklenip kaydedilmesi.
        assert hasattr(exporter, "export_searchable_pdf")


# ======================================================================
# 1.3 Bozuk / kilitli / salt okunur dosyalar
# ======================================================================
class TestProblemliDosyalar:
    def test_bozuk_dosya_cokmeden_uyarir(self, window, corrupt_pdf, silence_dialogs):
        assert window.open_path(str(corrupt_pdf)) is False
        assert not window.controller.is_open
        kinds = [c[0] for c in silence_dialogs["message"]]
        assert "critical" in kinds or "warning" in kinds

    def test_olmayan_dosya_uyarir(self, window, tmp_path, silence_dialogs):
        assert window.open_path(str(tmp_path / "yok.pdf")) is False
        assert any(c[0] == "warning" for c in silence_dialogs["message"])

    def test_sifreli_dosya_parola_sorar(self, window, encrypted_pdf, monkeypatch, qapp):
        from PySide6.QtWidgets import QDialog

        from app.ui.dialogs import security_dialog

        sorular = []

        class SahtePrompt(security_dialog.PasswordPrompt):
            def exec(self):
                sorular.append(True)
                return QDialog.Accepted

            def password(self):
                return "gizli"

        monkeypatch.setattr("app.ui.main_window.PasswordPrompt", SahtePrompt)
        assert window.open_path(str(encrypted_pdf)) is True
        assert sorular, "Parola diyaloğu gösterilmeli"
        assert window.controller.page_count == 6

    def test_yanlis_parola_tekrar_sorar_sonra_vazgecer(self, window, encrypted_pdf,
                                                      monkeypatch):
        from PySide6.QtWidgets import QDialog

        from app.ui.dialogs import security_dialog

        denemeler = {"n": 0}

        class SahtePrompt(security_dialog.PasswordPrompt):
            def __init__(self, file_name, retry=False, parent=None):
                super().__init__(file_name, retry, parent)
                denemeler["retry"] = retry

            def exec(self):
                denemeler["n"] += 1
                return QDialog.Accepted if denemeler["n"] == 1 else QDialog.Rejected

            def password(self):
                return "yanlis"

        monkeypatch.setattr("app.ui.main_window.PasswordPrompt", SahtePrompt)
        assert window.open_path(str(encrypted_pdf)) is False
        assert denemeler["n"] == 2, "Yanlış paroladan sonra tekrar sorulmalı"
        assert denemeler["retry"] is True, "İkinci soruda uyarı gösterilmeli"
        assert not window.controller.is_open

    def test_salt_okunur_dosyaya_kayit_cokmez(self, window, readonly_pdf,
                                              silence_dialogs, qapp):
        assert window.open_path(str(readonly_pdf)) is True
        window.controller.rotate([0], 90)
        sonuc = window.save()
        assert sonuc is False, "Salt okunur dosyaya kayıt başarısız dönmeli"
        assert any(c[0] == "critical" for c in silence_dialogs["message"])
        assert window.controller.is_open, "Uygulama açık kalmalı"
        assert window.controller.is_dirty, "Değişiklikler kaybolmamalı"
