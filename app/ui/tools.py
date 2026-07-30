"""Etkileşimli araç tanımları ve ortak araç durumu."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor

from ..core.annotations import MarkupKind, PenStyle, ShapeKind, TextStyle


class Tool(str, Enum):
    SELECT = "select"
    HAND = "hand"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    PENCIL = "pencil"
    ERASER = "eraser"
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"
    TEXT = "text"
    IMAGE = "image"
    SIGNATURE = "signature"


#: İki nokta arası çizen araçlar
LINE_TOOLS = {Tool.LINE, Tool.ARROW}

MARKUP_MAP = {
    Tool.HIGHLIGHT: MarkupKind.HIGHLIGHT,
    Tool.UNDERLINE: MarkupKind.UNDERLINE,
    Tool.STRIKEOUT: MarkupKind.STRIKEOUT,
}

SHAPE_MAP = {
    Tool.RECT: ShapeKind.RECT,
    Tool.ELLIPSE: ShapeKind.ELLIPSE,
    Tool.LINE: ShapeKind.LINE,
    Tool.ARROW: ShapeKind.ARROW,
}

CURSORS = {
    Tool.SELECT: Qt.ArrowCursor,
    Tool.HAND: Qt.OpenHandCursor,
    Tool.HIGHLIGHT: Qt.IBeamCursor,
    Tool.UNDERLINE: Qt.IBeamCursor,
    Tool.STRIKEOUT: Qt.IBeamCursor,
    Tool.PENCIL: Qt.CrossCursor,
    Tool.ERASER: Qt.CrossCursor,
    Tool.RECT: Qt.CrossCursor,
    Tool.ELLIPSE: Qt.CrossCursor,
    Tool.LINE: Qt.CrossCursor,
    Tool.ARROW: Qt.CrossCursor,
    Tool.TEXT: Qt.IBeamCursor,
    Tool.IMAGE: Qt.CrossCursor,
    Tool.SIGNATURE: Qt.CrossCursor,
}

LABELS = {
    Tool.SELECT: "Seç",
    Tool.HAND: "Kaydır",
    Tool.HIGHLIGHT: "Vurgula",
    Tool.UNDERLINE: "Altını çiz",
    Tool.STRIKEOUT: "Üstünü çiz",
    Tool.PENCIL: "Kalem",
    Tool.ERASER: "Silgi",
    Tool.RECT: "Dikdörtgen",
    Tool.ELLIPSE: "Daire",
    Tool.LINE: "Çizgi",
    Tool.ARROW: "Ok",
    Tool.TEXT: "Metin",
    Tool.IMAGE: "Görsel",
    Tool.SIGNATURE: "İmza",
}


def qcolor_to_rgb(color: QColor) -> tuple[float, float, float]:
    return color.redF(), color.greenF(), color.blueF()


@dataclass
class ToolDefaults:
    """Kullanıcının araç çubuğundan ayarladığı ortak stil değerleri."""

    stroke: QColor = field(default_factory=lambda: QColor("#e53935"))
    fill: QColor | None = None
    highlight: QColor = field(default_factory=lambda: QColor("#ffeb3b"))
    width: float = 2.0
    opacity: float = 1.0
    text: TextStyle = field(default_factory=TextStyle)


class ToolState(QObject):
    """Etkin aracı ve stil ayarlarını tutar."""

    toolChanged = Signal(object)     # Tool
    styleChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tool = Tool.SELECT
        self.defaults = ToolDefaults()

    @property
    def tool(self) -> Tool:
        return self._tool

    def set_tool(self, tool: Tool) -> None:
        if tool != self._tool:
            self._tool = tool
            self.toolChanged.emit(tool)

    # -- stil ----------------------------------------------------------
    def set_stroke(self, color: QColor) -> None:
        self.defaults.stroke = QColor(color)
        self.styleChanged.emit()

    def set_fill(self, color: QColor | None) -> None:
        self.defaults.fill = QColor(color) if color is not None else None
        self.styleChanged.emit()

    def set_highlight(self, color: QColor) -> None:
        self.defaults.highlight = QColor(color)
        self.styleChanged.emit()

    def set_width(self, width: float) -> None:
        self.defaults.width = max(0.5, float(width))
        self.styleChanged.emit()

    def set_opacity(self, opacity: float) -> None:
        self.defaults.opacity = max(0.05, min(1.0, float(opacity)))
        self.styleChanged.emit()

    # -- çekirdek katman stilleri --------------------------------------
    def pen_style(self, for_markup: bool = False) -> PenStyle:
        d = self.defaults
        if for_markup:
            return PenStyle(
                color=qcolor_to_rgb(d.highlight),
                fill=None,
                width=d.width,
                opacity=d.opacity,
            )
        return PenStyle(
            color=qcolor_to_rgb(d.stroke),
            fill=qcolor_to_rgb(d.fill) if d.fill is not None else None,
            width=d.width,
            opacity=d.opacity,
        )

    def preview_color(self) -> QColor:
        if self._tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            return self.defaults.highlight
        return self.defaults.stroke
