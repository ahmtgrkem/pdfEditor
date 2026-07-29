"""Serbest imza çizme / kaydetme diyaloğu.

Fare veya grafik tablet ile çizilen imza, saydam arka planlı PNG olarak
üretilir ve belgeye görsel olarak yerleştirilir. Basınç desteği olan
tabletlerde çizgi kalınlığı basınca göre değişir.
"""
from __future__ import annotations

import io
import os

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .. import icons, theme
from .common import BaseDialog, ColorButton

CANVAS_W = 620
CANVAS_H = 220


class SignatureCanvas(QWidget):
    """Üzerine imza çizilen tuval."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(CANVAS_W, CANVAS_H)
        self.setAttribute(Qt.WA_StaticContents)
        self.setCursor(Qt.CrossCursor)
        self.setTabletTracking(True)
        self._strokes: list[list[tuple[QPointF, float]]] = []
        self._active: list[tuple[QPointF, float]] | None = None
        self.pen_color = QColor("#111827")
        self.pen_width = 2.6

    # ------------------------------------------------------------------
    def is_empty(self) -> bool:
        return not any(len(s) >= 2 for s in self._strokes)

    def clear(self) -> None:
        self._strokes.clear()
        self._active = None
        self.update()
        self.changed.emit()

    def undo(self) -> None:
        if self._strokes:
            self._strokes.pop()
            self.update()
            self.changed.emit()

    # ------------------------------------------------------------------
    def _start(self, pos: QPointF, pressure: float) -> None:
        self._active = [(pos, pressure)]
        self._strokes.append(self._active)

    def _extend(self, pos: QPointF, pressure: float) -> None:
        if self._active is None:
            return
        last = self._active[-1][0]
        if (pos - last).manhattanLength() >= 1.0:
            self._active.append((pos, pressure))
            self.update()

    def _finish(self) -> None:
        if self._active is not None and len(self._active) < 2:
            self._strokes.pop()
        self._active = None
        self.changed.emit()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._start(event.position(), 1.0)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton:
            self._extend(event.position(), 1.0)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._finish()

    def tabletEvent(self, event) -> None:  # noqa: N802
        pressure = max(0.25, event.pressure() or 1.0)
        pos = event.position()
        kind = event.type()
        if kind == QEvent.TabletPress:
            self._start(pos, pressure)
        elif kind == QEvent.TabletMove:
            if self._active is not None:
                self._extend(pos, pressure)
        elif kind == QEvent.TabletRelease:
            self._finish()
        event.accept()

    # ------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pal = theme.current()

        painter.fillRect(self.rect(), QColor("#ffffff"))
        painter.setPen(QPen(QColor(pal.border), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        # imza çizgisi
        painter.setPen(QPen(QColor("#c9ced8"), 1, Qt.DashLine))
        y = int(CANVAS_H * 0.78)
        painter.drawLine(28, y, CANVAS_W - 28, y)
        painter.setPen(QColor("#aeb6c2"))
        painter.drawText(QRect(28, y + 4, 240, 20), Qt.AlignLeft, "İmza")

        self._paint_strokes(painter, 1.0)
        painter.end()

    def _paint_strokes(self, painter: QPainter, scale: float) -> None:
        for stroke in self._strokes:
            if len(stroke) < 2:
                continue
            for i in range(1, len(stroke)):
                p0, pr0 = stroke[i - 1]
                p1, pr1 = stroke[i]
                width = self.pen_width * scale * (0.55 + 0.9 * (pr0 + pr1) / 2)
                pen = QPen(self.pen_color, max(0.6, width))
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawLine(p0 * scale, p1 * scale)

    # ------------------------------------------------------------------
    def content_bounds(self) -> QRect | None:
        pts = [p for stroke in self._strokes for p, _ in stroke]
        if not pts:
            return None
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        pad = self.pen_width * 3 + 4
        return QRect(
            int(max(0, min(xs) - pad)),
            int(max(0, min(ys) - pad)),
            int(min(CANVAS_W, max(xs) + pad) - max(0, min(xs) - pad)),
            int(min(CANVAS_H, max(ys) + pad) - max(0, min(ys) - pad)),
        )

    def to_png(self, scale: float = 3.0) -> bytes | None:
        """İmzayı saydam arka planlı, kırpılmış PNG olarak döndürür."""
        bounds = self.content_bounds()
        if bounds is None or bounds.width() < 2:
            return None

        image = QImage(
            int(CANVAS_W * scale), int(CANVAS_H * scale), QImage.Format_ARGB32_Premultiplied
        )
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_strokes(painter, scale)
        painter.end()

        cropped = image.copy(
            QRect(
                int(bounds.x() * scale),
                int(bounds.y() * scale),
                int(bounds.width() * scale),
                int(bounds.height() * scale),
            )
        )
        buffer = QBuffer()
        buffer.open(QBuffer.WriteOnly)
        cropped.save(buffer, "PNG")
        return bytes(buffer.data())


class SignatureDialog(BaseDialog):
    """İmza çizme, dosyadan yükleme ve kaydetme."""

    def __init__(self, parent=None, last_path: str | None = None) -> None:
        super().__init__("İmza", parent, ok_text="Belgeye yerleştir")
        self.setMinimumWidth(CANVAS_W + 60)
        self._image_bytes: bytes | None = None
        self._loaded_path: str | None = None

        self.canvas = SignatureCanvas(self)

        self.color = ColorButton(QColor("#111827"), parent=self)
        self.color.colorChanged.connect(self._on_color)

        self.width_box = QDoubleSpinBox(self)
        self.width_box.setRange(0.5, 12.0)
        self.width_box.setSingleStep(0.4)
        self.width_box.setValue(2.6)
        self.width_box.setSuffix(" px")
        self.width_box.valueChanged.connect(self._on_width)

        btn_undo = QPushButton(icons.icon("undo", size=18), "Geri al", self)
        btn_undo.clicked.connect(self.canvas.undo)
        btn_clear = QPushButton(icons.icon("eraser", size=18), "Temizle", self)
        btn_clear.clicked.connect(self._clear)
        btn_load = QPushButton(icons.icon("image", size=18), "Görselden yükle…", self)
        btn_load.clicked.connect(self._load_file)
        btn_save = QPushButton(icons.icon("save", size=18), "PNG kaydet…", self)
        btn_save.clicked.connect(self._save_file)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(QLabel("Kalem", self))
        tools.addWidget(self.color)
        tools.addWidget(self.width_box)
        tools.addStretch(1)
        tools.addWidget(btn_undo)
        tools.addWidget(btn_clear)

        files = QHBoxLayout()
        files.setSpacing(6)
        files.addWidget(btn_load)
        files.addWidget(btn_save)
        files.addStretch(1)

        self.preview = QLabel(self)
        self.preview.setFixedHeight(64)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            f"background: {theme.current().surface_alt};"
            f"border: 1px solid {theme.current().border}; border-radius: 8px;"
        )
        self.preview.setText("Önizleme")

        self.content.addWidget(QLabel("Fare veya kalem tablet ile imzanızı çizin:", self))
        self.content.addWidget(self.canvas, 0, Qt.AlignHCenter)
        self.content.addLayout(tools)
        self.content.addLayout(files)
        self.content.addWidget(self.preview)

        self.canvas.changed.connect(self._update_preview)
        self._update_preview()

        if last_path and os.path.exists(last_path):
            self._apply_file(last_path)

    # ------------------------------------------------------------------
    def _on_color(self, color: QColor | None) -> None:
        if color is not None:
            self.canvas.pen_color = color
            self.canvas.update()
            self._update_preview()

    def _on_width(self, value: float) -> None:
        self.canvas.pen_width = float(value)
        self.canvas.update()
        self._update_preview()

    def _clear(self) -> None:
        self._image_bytes = None
        self._loaded_path = None
        self.canvas.clear()
        self._update_preview()

    def _update_preview(self) -> None:
        data = self._image_bytes if self._image_bytes else self.canvas.to_png()
        if not data:
            self.preview.setText("Önizleme")
            self.preview.setPixmap(QPixmap())
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        pm = QPixmap()
        pm.loadFromData(QByteArray(data), "PNG")
        self.preview.setPixmap(
            pm.scaled(self.preview.width() - 12, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(True)

    # ------------------------------------------------------------------
    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "İmza görseli seç", os.path.expanduser("~"),
            "Görseller (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if path:
            self._apply_file(path)

    def _apply_file(self, path: str) -> None:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            QMessageBox.warning(self, "İmza", f"Dosya okunamadı:\n{exc}")
            return
        if path.lower().endswith((".jpg", ".jpeg", ".bmp", ".webp")):
            raw = self._to_transparent_png(raw)
        self._image_bytes = raw
        self._loaded_path = path
        self.canvas.clear()
        self._update_preview()

    @staticmethod
    def _to_transparent_png(data: bytes) -> bytes:
        """Beyaz zeminli imza görsellerini saydamlaştırır."""
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data)).convert("RGBA")
            pixels = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    r, g, b, a = pixels[x, y]
                    if r > 235 and g > 235 and b > 235:
                        pixels[x, y] = (r, g, b, 0)
            out = io.BytesIO()
            img.save(out, "PNG")
            return out.getvalue()
        except Exception:  # noqa: BLE001
            return data

    def _save_file(self) -> None:
        data = self.image_bytes()
        if not data:
            QMessageBox.information(self, "İmza", "Önce bir imza çizin.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "İmzayı kaydet", os.path.join(os.path.expanduser("~"), "imza.png"),
            "PNG görsel (*.png)",
        )
        if path:
            with open(path, "wb") as fh:
                fh.write(data)

    # ------------------------------------------------------------------
    def image_bytes(self) -> bytes | None:
        if self._image_bytes:
            return self._image_bytes
        return self.canvas.to_png()

    def source_path(self) -> str | None:
        return self._loaded_path
