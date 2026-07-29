"""Koyu / açık tema tanımları ve stil sayfası üretimi."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Palette:
    name: str
    window: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_text: str
    canvas: str
    page_shadow: str
    selection: str
    danger: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


DARK = Palette(
    name="dark",
    window="#1b1e24",
    surface="#22262e",
    surface_alt="#2a2f39",
    border="#363c48",
    text="#e6e9ef",
    text_muted="#98a1b3",
    accent="#4c8dff",
    accent_hover="#679dff",
    accent_text="#ffffff",
    canvas="#14161b",
    page_shadow="#00000090",
    selection="#4c8dff55",
    danger="#ef5350",
)

LIGHT = Palette(
    name="light",
    window="#f4f6fa",
    surface="#ffffff",
    surface_alt="#eef1f6",
    border="#d5dae3",
    text="#1c2230",
    text_muted="#5c6779",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_text="#ffffff",
    canvas="#dfe3ea",
    page_shadow="#00000035",
    selection="#2563eb33",
    danger="#d32f2f",
)

THEMES = {"dark": DARK, "light": LIGHT}
_current = DARK


def current() -> Palette:
    return _current


def stylesheet(p: Palette) -> str:
    return f"""
QWidget {{
    background: {p.window};
    color: {p.text};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}}
QMainWindow::separator {{
    background: {p.border};
    width: 1px;
    height: 1px;
}}

/* ---- Menü ---- */
QMenuBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 2px 4px;
}}
QMenuBar::item {{ padding: 6px 11px; border-radius: 6px; background: transparent; }}
QMenuBar::item:selected {{ background: {p.surface_alt}; }}
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.accent}; color: {p.accent_text}; }}
QMenu::item:disabled {{ color: {p.text_muted}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 5px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---- Araç çubuğu ---- */
QToolBar {{
    background: {p.surface};
    border: none;
    border-bottom: 1px solid {p.border};
    padding: 4px 6px;
    spacing: 3px;
}}
QToolBar::separator {{
    background: {p.border};
    width: 1px;
    margin: 5px 6px;
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 5px;
    margin: 0px;
}}
QToolButton:hover {{ background: {p.surface_alt}; border-color: {p.border}; }}
QToolButton:pressed {{ background: {p.border}; }}
QToolButton:checked {{ background: {p.accent}; border-color: {p.accent}; }}
QToolButton::menu-indicator {{ image: none; width: 0px; }}
QToolButton[popupMode="1"] {{ padding-right: 5px; }}

/* ---- Dock / paneller ---- */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    color: {p.text};
}}
QDockWidget::title {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 8px 10px;
    font-weight: 600;
}}

/* ---- Listeler / ağaçlar ---- */
QListWidget, QTreeWidget, QTreeView, QListView, QTableWidget {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    outline: none;
    padding: 4px;
}}
QListWidget::item, QTreeWidget::item {{
    border-radius: 6px;
    padding: 4px;
    margin: 2px 1px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {p.accent};
    color: {p.accent_text};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {p.surface_alt}; }}
QHeaderView::section {{
    background: {p.surface_alt};
    border: none;
    border-right: 1px solid {p.border};
    padding: 6px;
}}

/* ---- Sekmeler ---- */
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ color: {p.text}; border-bottom-color: {p.accent}; }}
QTabBar::tab:hover {{ color: {p.text}; }}

/* ---- Girişler ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 8px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {p.accent}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
    padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}

/* ---- Düğmeler ---- */
QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 15px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p.border}; }}
QPushButton:pressed {{ background: {p.surface}; }}
QPushButton:disabled {{ color: {p.text_muted}; background: {p.surface}; }}
QPushButton:default, QPushButton[accent="true"] {{
    background: {p.accent};
    border-color: {p.accent};
    color: {p.accent_text};
}}
QPushButton:default:hover, QPushButton[accent="true"]:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
}}

/* ---- Kaydırma çubukları ---- */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p.border};
    border-radius: 5px;
    min-height: 32px;
    min-width: 32px;
}}
QScrollBar::handle:hover {{ background: {p.text_muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- Durum çubuğu ---- */
QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 0 6px; }}

/* ---- Diğer ---- */
QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {p.accent};
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QProgressBar {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 7px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {p.border};
    border-radius: 4px;
    background: {p.surface_alt};
}}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
}}
QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 8px;
}}
QSplitter::handle {{ background: {p.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
"""


def _qpalette(p: Palette) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p.window))
    pal.setColor(QPalette.WindowText, QColor(p.text))
    pal.setColor(QPalette.Base, QColor(p.surface))
    pal.setColor(QPalette.AlternateBase, QColor(p.surface_alt))
    pal.setColor(QPalette.Text, QColor(p.text))
    pal.setColor(QPalette.Button, QColor(p.surface_alt))
    pal.setColor(QPalette.ButtonText, QColor(p.text))
    pal.setColor(QPalette.Highlight, QColor(p.accent))
    pal.setColor(QPalette.HighlightedText, QColor(p.accent_text))
    pal.setColor(QPalette.ToolTipBase, QColor(p.surface))
    pal.setColor(QPalette.ToolTipText, QColor(p.text))
    pal.setColor(QPalette.PlaceholderText, QColor(p.text_muted))
    pal.setColor(QPalette.Link, QColor(p.accent))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(p.text_muted))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(p.text_muted))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor(p.text_muted))
    return pal


def apply(app: QApplication, name: str) -> Palette:
    """Temayı uygular ve etkin paleti döndürür."""
    global _current
    _current = THEMES.get(name, DARK)
    app.setStyle("Fusion")
    app.setPalette(_qpalette(_current))
    app.setStyleSheet(stylesheet(_current))
    return _current
