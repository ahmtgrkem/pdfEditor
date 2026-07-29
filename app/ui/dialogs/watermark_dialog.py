"""Filigran (watermark) diyaloğu."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from ...core import fonts
from ...core.annotations import WatermarkOptions
from .common import BaseDialog, ColorButton, PageRangeEdit


class WatermarkDialog(BaseDialog):
    """Metin veya görsel filigran ayarları."""

    def __init__(self, page_count: int, current_page: int = 0, parent=None) -> None:
        super().__init__("Filigran ekle", parent, ok_text="Uygula")
        self.setMinimumWidth(520)
        self._image_bytes: bytes | None = None

        self.mode_text = QRadioButton("Metin filigranı", self)
        self.mode_image = QRadioButton("Görsel filigranı", self)
        self.mode_text.setChecked(True)
        modes = QHBoxLayout()
        modes.addWidget(self.mode_text)
        modes.addWidget(self.mode_image)
        modes.addStretch(1)

        self.text = QLineEdit("TASLAK", self)
        self.family = QComboBox(self)
        self.family.addItems(fonts.available_families())
        self.size = QSpinBox(self)
        self.size.setRange(8, 400)
        self.size.setValue(64)
        self.size.setSuffix(" pt")
        self.color = ColorButton(QColor("#9e9e9e"), parent=self)

        text_row = QWidget(self)
        row = QHBoxLayout(text_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.size)
        row.addWidget(QLabel("Renk", self))
        row.addWidget(self.color)
        row.addStretch(1)

        self.image_path = QLineEdit(self)
        self.image_path.setPlaceholderText("PNG / JPG dosyası seçin…")
        self.image_path.setReadOnly(True)
        browse = QPushButton("Gözat…", self)
        browse.clicked.connect(self._browse)
        image_row = QWidget(self)
        irow = QHBoxLayout(image_row)
        irow.setContentsMargins(0, 0, 0, 0)
        irow.addWidget(self.image_path, 1)
        irow.addWidget(browse)

        self.image_scale = QSpinBox(self)
        self.image_scale.setRange(5, 100)
        self.image_scale.setValue(50)
        self.image_scale.setSuffix(" %")

        self.opacity = QSlider(Qt.Horizontal, self)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(25)
        self.opacity_label = QLabel("%25", self)
        self.opacity.valueChanged.connect(lambda v: self.opacity_label.setText(f"%{v}"))
        opacity_row = QWidget(self)
        orow = QHBoxLayout(opacity_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.addWidget(self.opacity, 1)
        orow.addWidget(self.opacity_label)

        self.angle = QDoubleSpinBox(self)
        self.angle.setRange(-180.0, 180.0)
        self.angle.setValue(45.0)
        self.angle.setSuffix(" °")

        self.pages = PageRangeEdit(page_count, current_page, self)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow("Metin", self.text)
        form.addRow("Yazı tipi", self.family)
        form.addRow("Boyut / renk", text_row)
        form.addRow("Görsel", image_row)
        form.addRow("Görsel boyutu", self.image_scale)
        form.addRow("Saydamlık", opacity_row)
        form.addRow("Açı", self.angle)
        form.addRow("Sayfalar", self.pages)

        self.content.addLayout(modes)
        self.content.addLayout(form)
        self.add_hint("Filigran sayfa içeriğinin üzerine yerleştirilir ve geri alınabilir.")

        self.mode_text.toggled.connect(self._sync_mode)
        self._sync_mode()

    # ------------------------------------------------------------------
    def _sync_mode(self) -> None:
        is_text = self.mode_text.isChecked()
        for w in (self.text, self.family, self.size, self.color, self.angle):
            w.setEnabled(is_text)
        self.image_path.setEnabled(not is_text)
        self.image_scale.setEnabled(not is_text)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Filigran görseli", os.path.expanduser("~"),
            "Görseller (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                self._image_bytes = fh.read()
            self.image_path.setText(path)
            self.mode_image.setChecked(True)
        except OSError as exc:
            self.image_path.setText(f"okunamadı: {exc}")

    # ------------------------------------------------------------------
    def options(self) -> WatermarkOptions:
        color = self.color.color() or QColor("#9e9e9e")
        use_image = self.mode_image.isChecked() and self._image_bytes
        return WatermarkOptions(
            text=self.text.text() or "TASLAK",
            family=self.family.currentText(),
            size=float(self.size.value()),
            color=(color.redF(), color.greenF(), color.blueF()),
            opacity=self.opacity.value() / 100.0,
            angle=float(self.angle.value()),
            pages=self.pages.indices(),
            image=self._image_bytes if use_image else None,
            image_scale=self.image_scale.value() / 100.0,
        )
