"""Diyaloglarda paylaşılan küçük bileşenler."""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import page_ops
from .. import theme


class ColorButton(QToolButton):
    """Renk seçici düğme; isteğe bağlı 'renk yok' desteği."""

    colorChanged = Signal(object)  # QColor | None

    def __init__(self, color: QColor | None = None, allow_none: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._color = QColor(color) if color is not None else None
        self._allow_none = allow_none
        self.setIconSize(QSize(22, 22))
        self.setAutoRaise(False)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> QColor | None:
        return QColor(self._color) if self._color is not None else None

    def set_color(self, color: QColor | None) -> None:
        self._color = QColor(color) if color is not None else None
        self._refresh()
        self.colorChanged.emit(self.color())

    def _refresh(self) -> None:
        pm = QPixmap(22, 22)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QColor(theme.current().border))
        if self._color is None:
            painter.setBrush(QColor(255, 255, 255, 30))
            painter.drawRoundedRect(1, 1, 20, 20, 4, 4)
            painter.setPen(QColor(theme.current().danger))
            painter.drawLine(4, 18, 18, 4)
        else:
            painter.setBrush(self._color)
            painter.drawRoundedRect(1, 1, 20, 20, 4, 4)
        painter.end()
        self.setIcon(pm)
        self.setToolTip(self._color.name() if self._color else "Renk yok")

    def _pick(self) -> None:
        dlg = QColorDialog(self._color or QColor("#ffffff"), self)
        dlg.setWindowTitle("Renk seç" + (" (İptal = renk yok)" if self._allow_none else ""))
        if dlg.exec() == QDialog.Accepted:
            self.set_color(dlg.currentColor())
        elif self._allow_none:
            self.set_color(None)


class PageRangeEdit(QWidget):
    """Sayfa aralığı girişi + hazır seçenekler."""

    def __init__(self, page_count: int, current_page: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.page_count = page_count
        self.current_page = current_page

        self.combo = QComboBox(self)
        self.combo.addItems(["Tüm sayfalar", "Geçerli sayfa", "Özel aralık"])
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("örn. 1-3, 5, 8-")
        self.edit.setEnabled(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.combo)
        layout.addWidget(self.edit, 1)

        self.combo.currentIndexChanged.connect(self._on_mode)

    def _on_mode(self, index: int) -> None:
        self.edit.setEnabled(index == 2)
        if index == 2 and not self.edit.text():
            self.edit.setText(f"1-{self.page_count}")

    def indices(self) -> list[int]:
        mode = self.combo.currentIndex()
        if mode == 0:
            return list(range(self.page_count))
        if mode == 1:
            return [self.current_page]
        return page_ops.parse_page_ranges(self.edit.text(), self.page_count)

    def set_custom(self, expression: str) -> None:
        self.combo.setCurrentIndex(2)
        self.edit.setText(expression)


class PathPicker(QWidget):
    """Dosya/klasör seçici satırı."""

    pathChanged = Signal(str)

    def __init__(self, mode: str = "dir", filter_: str = "", parent=None) -> None:
        super().__init__(parent)
        self.mode = mode
        self.filter = filter_
        self.edit = QLineEdit(self)
        self.button = QPushButton("Gözat…", self)
        self.button.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.edit.textChanged.connect(self.pathChanged)

    def path(self) -> str:
        return self.edit.text().strip()

    def set_path(self, value: str) -> None:
        self.edit.setText(value)

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.path() or os.path.expanduser("~")
        if self.mode == "dir":
            chosen = QFileDialog.getExistingDirectory(self, "Klasör seç", start)
        elif self.mode == "save":
            chosen, _ = QFileDialog.getSaveFileName(self, "Farklı kaydet", start, self.filter)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Dosya seç", start, self.filter)
        if chosen:
            self.set_path(chosen)


class BaseDialog(QDialog):
    """Ortak düzen ve düğme çubuğu sağlayan temel diyalog."""

    def __init__(self, title: str, parent=None, ok_text: str = "Uygula") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)

        self.content = QVBoxLayout()
        self.content.setSpacing(10)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        self.buttons.button(QDialogButtonBox.Ok).setProperty("accent", "true")
        self.buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 14)
        outer.setSpacing(12)
        outer.addLayout(self.content)
        outer.addStretch(1)
        outer.addWidget(self.buttons)

    def add_hint(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.current().text_muted};")
        self.content.addWidget(label)
        return label
