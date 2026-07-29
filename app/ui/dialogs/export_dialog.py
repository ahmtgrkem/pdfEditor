"""Görsele dönüştürme ve sıkıştırma diyalogları."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSlider,
    QSpinBox,
    QWidget,
    QHBoxLayout,
)

from ...core.exporter import CompressOptions, IMAGE_FORMATS, ImageExportOptions
from .common import BaseDialog, PageRangeEdit, PathPicker

DPI_PRESETS = [72, 96, 150, 200, 300, 600]


class ExportImagesDialog(BaseDialog):
    """PDF sayfalarını PNG/JPG/TIFF olarak dışa aktarma ayarları."""

    def __init__(self, page_count: int, current_page: int, source_path: str | None, parent=None) -> None:
        super().__init__("Görsele dönüştür", parent, ok_text="Dışa aktar")
        self.setMinimumWidth(540)

        self.fmt = QComboBox(self)
        self.fmt.addItems(list(IMAGE_FORMATS))

        self.dpi = QComboBox(self)
        self.dpi.setObjectName("dpiCombo")
        self.dpi.setEditable(True)
        # Yalnızca sayı girilebilsin (24-1200 DPI aralığı)
        self.dpi.setValidator(QIntValidator(24, 1200, self))
        self.dpi.setInsertPolicy(QComboBox.NoInsert)
        self.dpi.addItems([str(d) for d in DPI_PRESETS])
        self.dpi.setCurrentText("150")

        self.quality = QSlider(Qt.Horizontal, self)
        self.quality.setRange(20, 100)
        self.quality.setValue(90)
        self.quality_label = QLabel("90", self)
        self.quality.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))
        q_row = QWidget(self)
        qrow = QHBoxLayout(q_row)
        qrow.setContentsMargins(0, 0, 0, 0)
        qrow.addWidget(self.quality, 1)
        qrow.addWidget(self.quality_label)

        self.grayscale = QCheckBox("Gri tonlama", self)
        self.transparent = QCheckBox("Saydam arka plan (PNG/TIFF)", self)
        self.multipage = QCheckBox("Tek çok sayfalı TIFF dosyası", self)

        self.pages = PageRangeEdit(page_count, current_page, self)

        default_dir = os.path.dirname(source_path) if source_path else os.path.expanduser("~")
        base = os.path.splitext(os.path.basename(source_path))[0] if source_path else "sayfa"
        self.out_dir = PathPicker("dir", parent=self)
        self.out_dir.set_path(os.path.join(default_dir, f"{base}_gorseller"))
        self.prefix = QLineEdit(base, self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow("Biçim", self.fmt)
        form.addRow("Çözünürlük (DPI)", self.dpi)
        form.addRow("Kalite", q_row)
        form.addRow("Sayfalar", self.pages)
        form.addRow("Hedef klasör", self.out_dir)
        form.addRow("Dosya ön eki", self.prefix)
        form.addRow("", self.grayscale)
        form.addRow("", self.transparent)
        form.addRow("", self.multipage)

        self.content.addLayout(form)
        self.hint = self.add_hint("")

        self.fmt.currentTextChanged.connect(self._sync)
        self.dpi.currentTextChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        fmt = self.fmt.currentText()
        self.quality.setEnabled(fmt in ("JPG", "WEBP"))
        self.transparent.setEnabled(fmt in ("PNG", "TIFF", "WEBP"))
        self.multipage.setEnabled(fmt == "TIFF")
        dpi = self._dpi_value()
        px = int(595 / 72 * dpi), int(842 / 72 * dpi)
        self.hint.setText(f"A4 sayfa yaklaşık {px[0]}×{px[1]} piksel olarak dışa aktarılacak.")

    def _dpi_value(self) -> int:
        try:
            return max(24, min(1200, int(float(self.dpi.currentText()))))
        except ValueError:
            return 150

    def options(self) -> ImageExportOptions:
        return ImageExportOptions(
            out_dir=self.out_dir.path(),
            fmt=self.fmt.currentText(),
            dpi=self._dpi_value(),
            pages=self.pages.indices(),
            prefix=self.prefix.text().strip() or "sayfa",
            jpeg_quality=self.quality.value(),
            grayscale=self.grayscale.isChecked(),
            transparent=self.transparent.isChecked() and self.transparent.isEnabled(),
            multipage_tiff=self.multipage.isChecked() and self.multipage.isEnabled(),
        )

    def accept(self) -> None:  # noqa: D102
        if not self.out_dir.path():
            QMessageBox.information(self, "Dışa aktar", "Hedef klasör seçin.")
            return
        try:
            self.pages.indices()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Dışa aktar", str(exc))
            return
        super().accept()


class CompressDialog(BaseDialog):
    """PDF sıkıştırma / optimizasyon ayarları."""

    PRESETS = {
        "Yüksek kalite (hafif sıkıştırma)": (300, 88),
        "Dengeli (önerilen)": (150, 72),
        "Küçük dosya (e-posta)": (110, 58),
        "En küçük (ekran)": (72, 45),
    }

    def __init__(self, source_path: str | None, current_size: int = 0, parent=None) -> None:
        super().__init__("PDF sıkıştır", parent, ok_text="Sıkıştır")
        self.setMinimumWidth(540)

        self.preset = QComboBox(self)
        self.preset.addItems(list(self.PRESETS))
        self.preset.setCurrentIndex(1)

        self.dpi = QSpinBox(self)
        self.dpi.setRange(36, 600)
        self.dpi.setValue(150)
        self.dpi.setSuffix(" DPI")

        self.quality = QSpinBox(self)
        self.quality.setRange(20, 95)
        self.quality.setValue(72)
        self.quality.setSuffix(" %")

        self.downsample = QCheckBox("Görselleri yeniden örnekle ve yeniden sıkıştır", self)
        self.downsample.setChecked(True)
        self.subset = QCheckBox("Yazı tiplerini alt kümele", self)
        self.subset.setChecked(True)
        self.strip_meta = QCheckBox("Belge bilgilerini (metadata) temizle", self)

        default = source_path or os.path.expanduser("~/belge.pdf")
        base, ext = os.path.splitext(default)
        self.output = PathPicker("save", "PDF (*.pdf)", parent=self)
        self.output.set_path(f"{base}_sikistirilmis{ext or '.pdf'}")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow("Hazır ayar", self.preset)
        form.addRow("Görsel çözünürlüğü", self.dpi)
        form.addRow("Görsel kalitesi", self.quality)
        form.addRow("", self.downsample)
        form.addRow("", self.subset)
        form.addRow("", self.strip_meta)
        form.addRow("Çıktı dosyası", self.output)

        self.content.addLayout(form)
        size_text = f"Mevcut boyut: {current_size / 1024 / 1024:.2f} MB" if current_size else ""
        self.add_hint(
            f"{size_text}\nSıkıştırma yeni bir dosyaya yazılır; özgün belge değişmez."
        )

        self.preset.currentTextChanged.connect(self._apply_preset)
        self.downsample.toggled.connect(self._sync)
        self._apply_preset(self.preset.currentText())

    def _apply_preset(self, name: str) -> None:
        dpi, quality = self.PRESETS.get(name, (150, 72))
        self.dpi.setValue(dpi)
        self.quality.setValue(quality)
        self._sync()

    def _sync(self) -> None:
        enabled = self.downsample.isChecked()
        self.dpi.setEnabled(enabled)
        self.quality.setEnabled(enabled)

    def options(self) -> CompressOptions:
        return CompressOptions(
            image_dpi=self.dpi.value() if self.downsample.isChecked() else 0,
            jpeg_quality=self.quality.value(),
            downsample_images=self.downsample.isChecked(),
            subset_fonts=self.subset.isChecked(),
            remove_metadata=self.strip_meta.isChecked(),
        )

    def output_path(self) -> str:
        return self.output.path()

    def accept(self) -> None:  # noqa: D102
        if not self.output_path():
            QMessageBox.information(self, "Sıkıştır", "Çıktı dosyası seçin.")
            return
        super().accept()
