"""Güncelleme bildirim ve indirme ilerlemesi diyalogları."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from ... import __app_name__, __version__
from ...services.updater import UpdateInfo, human_size, human_speed
from .. import theme


class UpdateAvailableDialog(QDialog):
    """Yeni sürüm bildirimi: sürüm notları, "Şimdi Güncelle" / "Daha Sonra"."""

    def __init__(self, info: UpdateInfo, parent=None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("Güncelleme mevcut")
        self.setModal(True)
        self.setMinimumWidth(520)

        palette = theme.current()

        baslik = QLabel(f"<h3 style='margin:0'>{__app_name__} {info.version} yayınlandı</h3>", self)
        baslik.setTextFormat(Qt.RichText)

        alt_baslik_parcalari = [f"Yüklü sürüm: <b>{__version__}</b>"]
        if info.release_date:
            alt_baslik_parcalari.append(f"Yayın tarihi: {info.release_date}")
        if info.size:
            alt_baslik_parcalari.append(f"Boyut: {human_size(info.size)}")
        alt_baslik = QLabel(" &nbsp;•&nbsp; ".join(alt_baslik_parcalari), self)
        alt_baslik.setTextFormat(Qt.RichText)
        alt_baslik.setStyleSheet(f"color: {palette.text_muted};")

        self.notes = QTextBrowser(self)
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(150)
        self.notes.setPlainText(info.release_notes or "Bu sürüm için not paylaşılmadı.")

        self.skip_box = QCheckBox("Bu sürümü atla", self)
        self.skip_box.setToolTip("Bu sürüm için bir daha hatırlatılmaz.")

        self.buttons = QDialogButtonBox(self)
        self.btn_update = QPushButton("Şimdi Güncelle", self)
        self.btn_update.setProperty("accent", "true")
        self.btn_update.setDefault(True)
        self.buttons.addButton(self.btn_update, QDialogButtonBox.AcceptRole)
        self.btn_later = QPushButton("Daha Sonra", self)
        self.buttons.addButton(self.btn_later, QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        uyari: QLabel | None = None
        if info.mandatory:
            # Zorunlu güncellemede erteleme ve atlama kapatılır.
            self.btn_later.setEnabled(False)
            self.skip_box.setVisible(False)
            uyari = QLabel(
                "Bu <b>zorunlu</b> bir güncellemedir; uygulamayı kullanmaya devam "
                "etmek için kurmanız gerekir.", self,
            )
            uyari.setWordWrap(True)
            uyari.setStyleSheet(f"color: {palette.danger};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(baslik)
        layout.addWidget(alt_baslik)
        if uyari is not None:
            layout.addWidget(uyari)
        layout.addWidget(QLabel("Sürüm notları:", self))
        layout.addWidget(self.notes, 1)

        alt_satir = QHBoxLayout()
        alt_satir.addWidget(self.skip_box)
        alt_satir.addStretch(1)
        alt_satir.addWidget(self.buttons)
        layout.addLayout(alt_satir)

    @property
    def skip_requested(self) -> bool:
        return self.skip_box.isVisible() and self.skip_box.isChecked()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.info.mandatory:
            event.ignore()      # zorunlu güncelleme kapatılamaz
            return
        super().closeEvent(event)


class UpdateProgressDialog(QDialog):
    """Canlı indirme ilerlemesi: yüzde, boyut ve hız."""

    cancelled = Signal()

    def __init__(self, info: UpdateInfo, parent=None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("Güncelleme indiriliyor")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        self.label = QLabel(f"{__app_name__} {info.version} indiriliyor…", self)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)

        self.detail = QLabel("Bağlantı kuruluyor…", self)
        self.detail.setStyleSheet(f"color: {theme.current().text_muted};")

        self.buttons = QDialogButtonBox(self)
        self.btn_cancel = QPushButton("İptal", self)
        self.buttons.addButton(self.btn_cancel, QDialogButtonBox.RejectRole)
        self.btn_cancel.clicked.connect(self._on_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addWidget(self.buttons)

    def _on_cancel(self) -> None:
        self.btn_cancel.setEnabled(False)
        self.detail.setText("İptal ediliyor…")
        self.cancelled.emit()

    def update_progress(self, received: int, total: int, speed: float) -> None:
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(received * 100 / total))
            self.detail.setText(
                f"{human_size(received)} / {human_size(total)}  •  {human_speed(speed)}"
            )
        else:
            # Sunucu boyut bildirmedi: belirsiz ilerleme çubuğu
            self.bar.setRange(0, 0)
            self.detail.setText(f"{human_size(received)} indirildi  •  {human_speed(speed)}")

    def set_installing(self) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.label.setText("Kurulum başlatılıyor…")
        self.detail.setText("Uygulama kapanacak ve güncelleme kurulacak.")
        self.btn_cancel.setEnabled(False)

    def reject(self) -> None:  # noqa: D102 - Esc ile kapatmayı iptale bağla
        self._on_cancel()
