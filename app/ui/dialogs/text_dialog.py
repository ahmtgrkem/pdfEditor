"""Sayfaya metin ekleme diyaloğu."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QWidget,
)

from ...core import fonts
from ...core.annotations import TextStyle
from .common import BaseDialog, ColorButton

ALIGNMENTS = [("Sola", 0), ("Ortala", 1), ("Sağa", 2), ("İki yana", 3)]


class TextDialog(BaseDialog):
    """Metin içeriği ve biçimini toplar."""

    def __init__(self, style: TextStyle, parent=None) -> None:
        super().__init__("Metin ekle", parent, ok_text="Ekle")
        self.setMinimumWidth(520)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText("Eklenecek metni yazın…")
        self.editor.setMinimumHeight(110)

        self.family = QComboBox(self)
        self.family.addItems(fonts.available_families())
        idx = self.family.findText(style.family)
        self.family.setCurrentIndex(max(0, idx))

        self.size = QDoubleSpinBox(self)
        self.size.setRange(4.0, 300.0)
        self.size.setDecimals(1)
        self.size.setSingleStep(1.0)
        self.size.setValue(style.size)
        self.size.setSuffix(" pt")

        self.color = ColorButton(QColor.fromRgbF(*style.color), parent=self)
        self.background = ColorButton(
            QColor.fromRgbF(*style.background) if style.background else None,
            allow_none=True,
            parent=self,
        )

        self.bold = QToolButton(self)
        self.bold.setText("B")
        self.bold.setCheckable(True)
        self.bold.setChecked(style.bold)
        bold_font = QFont(self.bold.font())
        bold_font.setBold(True)
        self.bold.setFont(bold_font)

        self.italic = QToolButton(self)
        self.italic.setText("I")
        self.italic.setCheckable(True)
        self.italic.setChecked(style.italic)
        italic_font = QFont(self.italic.font())
        italic_font.setItalic(True)
        self.italic.setFont(italic_font)

        self.align = QComboBox(self)
        for label, _value in ALIGNMENTS:
            self.align.addItem(label)
        self.align.setCurrentIndex(min(style.align, len(ALIGNMENTS) - 1))

        style_row = QWidget(self)
        row = QHBoxLayout(style_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.size)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        row.addWidget(QLabel("Renk", self))
        row.addWidget(self.color)
        row.addWidget(QLabel("Zemin", self))
        row.addWidget(self.background)
        row.addStretch(1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow("Yazı tipi", self.family)
        form.addRow("Biçim", style_row)
        form.addRow("Hizalama", self.align)

        self.content.addWidget(QLabel("Metin", self))
        self.content.addWidget(self.editor)
        self.content.addLayout(form)
        self.add_hint(
            "Metin, Türkçe karakterleri desteklemesi için seçilen yazı tipi belgeye "
            "gömülerek eklenir. Kutuya sığmazsa punto otomatik küçültülür."
        )
        self.editor.setFocus()

    def text(self) -> str:
        return self.editor.toPlainText()

    def style(self) -> TextStyle:
        color = self.color.color() or QColor("#000000")
        bg = self.background.color()
        return TextStyle(
            family=self.family.currentText(),
            size=float(self.size.value()),
            color=(color.redF(), color.greenF(), color.blueF()),
            bold=self.bold.isChecked(),
            italic=self.italic.isChecked(),
            align=ALIGNMENTS[self.align.currentIndex()][1],
            background=(bg.redF(), bg.greenF(), bg.blueF()) if bg is not None else None,
            border=False,
        )
