"""Koyu / açık tema tanımları ve stil sayfası üretimi."""
from __future__ import annotations

import hashlib
import os
import tempfile
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
    window="#1a1d24",
    surface="#222630",
    surface_alt="#2b303d",
    border="#3d4454",
    text="#f0f3f8",
    text_muted="#94a0b8",
    accent="#3b82f6",
    accent_hover="#60a5fa",
    accent_text="#ffffff",
    canvas="#12141a",
    #: Saydam renkler **#AARRGGBB** yazılır (``QColor``ın beklediği sıra).
    #: ``#RRGGBBAA`` yazılırsa alfa yanlış okunur ve renk bambaşka çıkar.
    page_shadow="#80000000",
    selection="#403b82f6",
    danger="#ef4444",
)

LIGHT = Palette(
    name="light",
    window="#f8fafc",
    surface="#ffffff",
    surface_alt="#e2e8f0",
    border="#cbd5e1",
    text="#0f172a",
    text_muted="#475569",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    accent_text="#ffffff",
    canvas="#b6c2d1",
    page_shadow="#380f172a",
    selection="#382563eb",
    danger="#dc2626",
)

THEMES = {"dark": DARK, "light": LIGHT}
_current = DARK


def current() -> Palette:
    return _current


#: Qt stil sayfalarındaki ``url(...)`` yalnızca **dosya yolu** (ya da ``:/``
#: kaynak yolu) kabul eder; ``data:`` URI'leri desteklenmez. Dahası, geçersiz
#: bir ``url()`` bildirimi ayrıştırıcıyı bozar ve o satırdan **sonraki tüm
#: kurallar sessizce düşer**. Bu yüzden göstergeler geçici dizine yazılıp
#: yoldan gösterilir.
_ICON_DIR = os.path.join(tempfile.gettempdir(), "agy_pdf_editor_qss")


def _svg_path(svg_template: str, color: str, name: str) -> str:
    """Göstergeyi geçici dizine yazar ve QSS'in kullanacağı yolu döndürür."""
    svg = svg_template.format(c=color)
    # İçerik özeti ad içinde: şablon/renk değişince eski dosya kullanılmaz.
    digest = hashlib.md5(svg.encode("utf-8")).hexdigest()[:10]
    path = os.path.join(_ICON_DIR, f"{name}-{digest}.svg")
    if not os.path.exists(path):
        try:
            os.makedirs(_ICON_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(svg)
        except OSError:
            # Yazılamazsa yol var olmayan dosyayı gösterir: gösterge çizilmez
            # ama stil sayfasının kalanı sağlam kalır.
            pass
    return path.replace("\\", "/")


_DOWN_ARROW = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>'
_UP_ARROW = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>'
_RIGHT_ARROW = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>'
_CHECK_MARK = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
_RADIO_DOT = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 24 24" fill="{c}"><circle cx="12" cy="12" r="9"/></svg>'


_CLOSE_MARK = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'
_FLOAT_MARK = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>'


def stylesheet(p: Palette) -> str:
    down_arrow = _svg_path(_DOWN_ARROW, p.text, "down")
    down_arrow_muted = _svg_path(_DOWN_ARROW, p.text_muted, "down-muted")
    up_arrow = _svg_path(_UP_ARROW, p.text, "up")
    up_arrow_muted = _svg_path(_UP_ARROW, p.text_muted, "up-muted")
    right_arrow = _svg_path(_RIGHT_ARROW, p.text, "right")
    right_arrow_muted = _svg_path(_RIGHT_ARROW, p.text_muted, "right-muted")
    check = _svg_path(_CHECK_MARK, p.accent_text, "check")
    check_text = _svg_path(_CHECK_MARK, p.accent, "check-accent")
    dot = _svg_path(_RADIO_DOT, p.accent_text, "dot")
    close_mark = _svg_path(_CLOSE_MARK, p.text_muted, "close")
    float_mark = _svg_path(_FLOAT_MARK, p.text_muted, "float")

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
/* Etiketler kendi arka planını boyamasın: genel ``QWidget`` kuralı yüzünden
   araç/durum çubuğu gibi farklı renkli yüzeylerde soluk kutular oluşuyordu. */
QLabel {{
    background: transparent;
}}

/* ---- Menü ---- */
QMenuBar {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 2px 4px;
}}
QMenuBar::item {{
    padding: 6px 11px;
    border-radius: 6px;
    background: transparent;
    color: {p.text};
}}
QMenuBar::item:selected {{
    background: {p.surface_alt};
}}
QMenu {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 28px 7px 10px;
    border-radius: 6px;
    color: {p.text};
}}
/* Seçili satır vurgu rengiyle değil, nötr bir katmanla boyanır: menü
   simgeleri tema metin rengiyle çizildiği için (bkz. ``icons.icon``) vurgu
   mavisinin üstünde okunmuyorlardı. */
QMenu::item:selected {{
    background: {p.border};
    color: {p.text};
}}
QMenu::item:disabled {{
    color: {p.text_muted};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: 5px 8px;
}}
QMenu::icon {{
    padding-left: 6px;
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
    margin-left: 8px;
}}
QMenu::indicator:checked {{
    image: url("{check_text}");
}}
QMenu::right-arrow {{
    image: url("{right_arrow}");
    width: 12px;
    height: 12px;
    margin-right: 8px;
}}
QMenu::right-arrow:disabled {{
    image: url("{right_arrow_muted}");
}}

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
    color: {p.text};
}}
QToolButton:hover {{
    background: {p.surface_alt};
    border-color: {p.border};
}}
QToolButton:pressed {{
    background: {p.border};
}}
/* Basılı düğme: dolu vurgu zemini yerine vurgu çerçevesi + hafif zemin.
   Simge de vurgu rengine geçtiği için (bkz. ``icons.icon``) aynı ``QAction``
   menüde de doğru görünür. */
QToolButton:checked {{
    background: {p.surface_alt};
    border-color: {p.accent};
    color: {p.accent};
}}
QToolButton:checked:hover {{
    background: {p.border};
    border-color: {p.accent_hover};
}}
/* Menülü araç düğmelerinde küçük ok görünür kalsın: aksi hâlde düğmenin
   menüsü olduğu anlaşılmıyor. */
QToolButton::menu-indicator {{
    image: url("{down_arrow_muted}");
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 8px;
    height: 8px;
    right: 1px;
    bottom: 1px;
}}
QToolButton::menu-indicator:disabled {{
    image: none;
}}
QToolButton[popupMode="1"] {{
    padding-right: 9px;
}}
QToolButton:disabled {{
    color: {p.text_muted};
}}

/* ---- Dock / paneller ---- */
QDockWidget {{
    titlebar-close-icon: url("{close_mark}");
    titlebar-normal-icon: url("{float_mark}");
    color: {p.text};
}}
QDockWidget::title {{
    background: {p.surface};
    border-bottom: 1px solid {p.border};
    padding: 8px 10px;
    font-weight: 600;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 0px;
    icon-size: 12px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {p.surface_alt};
    border-color: {p.border};
}}

/* ---- Listeler / ağaçlar ---- */
QListWidget, QTreeWidget, QTreeView, QListView, QTableWidget {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    outline: none;
    padding: 4px;
    color: {p.text};
}}
QListWidget::item, QTreeWidget::item {{
    border-radius: 6px;
    padding: 5px;
    margin: 2px 1px;
}}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {p.accent};
    color: {p.accent_text};
}}
QListWidget::item:hover, QTreeWidget::item:hover {{
    background: {p.surface_alt};
}}
QListWidget::item:selected:hover, QTreeWidget::item:selected:hover {{
    background: {p.accent_hover};
    color: {p.accent_text};
}}
/* Ağaç açma/kapama okları: varsayılan stil koyu temada görünmüyor. */
QTreeView::branch:has-children:!has-siblings:closed,
QTreeView::branch:closed:has-children:has-siblings {{
    image: url("{right_arrow_muted}");
}}
QTreeView::branch:open:has-children:!has-siblings,
QTreeView::branch:open:has-children:has-siblings {{
    image: url("{down_arrow_muted}");
}}
QHeaderView::section {{
    background: {p.surface_alt};
    color: {p.text};
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    padding: 6px 10px;
    font-weight: 600;
}}

/* ---- Sekmeler ---- */
QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 8px;
    background: {p.surface};
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    margin-right: 2px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {p.text};
    background: {p.surface_alt};
}}

/* ---- Girişler & Dropdown Açılır Kutuları ---- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 6px 10px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover {{
    border-color: {p.text_muted};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {{
    background: {p.window};
    color: {p.text_muted};
    border-color: {p.border};
}}
QLineEdit[readOnly="true"] {{
    background: {p.window};
    color: {p.text_muted};
}}

QComboBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 28px 5px 10px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QComboBox:hover {{
    border-color: {p.text_muted};
    background: {p.surface_alt};
}}
QComboBox:focus {{
    border-color: {p.accent};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 26px;
    border-left: none;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: url("{down_arrow}");
    width: 12px;
    height: 12px;
}}
QComboBox::down-arrow:disabled {{
    image: url("{down_arrow_muted}");
}}
QComboBox:disabled {{
    background: {p.window};
    color: {p.text_muted};
    border-color: {p.border};
}}
QComboBox:editable {{
    background: {p.surface};
}}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
    padding: 4px;
    outline: none;
    color: {p.text};
}}
QComboBox QAbstractItemView::item {{
    min-height: 24px;
    padding: 3px 8px;
    border-radius: 5px;
}}

/* ---- Sayısal Girişler (SpinBox) ---- */
QSpinBox, QDoubleSpinBox {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 5px 24px 5px 8px;
    color: {p.text};
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {p.text_muted};
    background: {p.surface_alt};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p.accent};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    background: transparent;
    margin-right: 2px;
    margin-top: 2px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border: none;
    background: transparent;
    margin-right: 2px;
    margin-bottom: 2px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {p.border};
    border-radius: 4px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{up_arrow}");
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{down_arrow}");
    width: 10px;
    height: 10px;
}}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled,
QSpinBox::up-arrow:off, QDoubleSpinBox::up-arrow:off {{
    image: url("{up_arrow_muted}");
}}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled,
QSpinBox::down-arrow:off, QDoubleSpinBox::down-arrow:off {{
    image: url("{down_arrow_muted}");
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background: {p.window};
    color: {p.text_muted};
}}

/* ---- Düğmeler ---- */
QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 7px;
    padding: 7px 16px;
    min-height: 18px;
    font-weight: 600;
    color: {p.text};
}}
QPushButton:hover {{
    background: {p.border};
    border-color: {p.text_muted};
    color: {p.text};
}}
QPushButton:pressed {{
    background: {p.surface};
}}
QPushButton:focus {{
    border-color: {p.accent};
}}
QPushButton:disabled {{
    color: {p.text_muted};
    background: {p.window};
    border-color: {p.border};
}}
/* Birincil eylem yalnızca ``accent`` özelliğiyle işaretlenir. Qt'nin
   "default" düğmesi odağa göre belirlendiği için ``:default`` seçicisi
   vurguyu yanlış düğmeye taşıyabiliyordu (imza diyaloğunda "İptal" mavi
   çıkıyordu). Hazır kutularda (QMessageBox) düğmeyi çağıran seçtiği için
   orada ``:default`` güvenle kullanılır. */
QPushButton[accent="true"], QMessageBox QPushButton:default {{
    background: {p.accent};
    border: 1px solid {p.accent};
    color: {p.accent_text};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover, QMessageBox QPushButton:default:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
    color: {p.accent_text};
}}
QPushButton[accent="true"]:pressed {{
    background: {p.accent};
    border-color: {p.accent};
    color: {p.accent_text};
}}
QPushButton[accent="true"]:disabled {{
    background: {p.surface_alt};
    border-color: {p.border};
    color: {p.text_muted};
}}
/* Diyalog içindeki araç düğmeleri (B/I, renk kutuları) araç çubuğundaki gibi
   saydam değil, tıklanabilir görünmeli. */
QDialog QToolButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 4px 7px;
    color: {p.text};
}}
QDialog QToolButton:hover {{
    background: {p.border};
    border-color: {p.text_muted};
}}
QDialog QToolButton:checked {{
    background: {p.surface_alt};
    border-color: {p.accent};
    color: {p.accent};
}}
QPushButton[danger="true"] {{
    background: {p.danger};
    border: 1px solid {p.danger};
    color: #ffffff;
}}
QDialogButtonBox QPushButton {{
    min-width: 92px;
}}

/* ---- Kaydırma çubukları ---- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p.text_muted};
    border-radius: 4px;
    min-height: 32px;
    min-width: 32px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {p.accent};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    height: 0px;
    width: 0px;
    border: none;
    background: transparent;
}}
QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {{
    image: none;
    width: 0px;
    height: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ---- Durum çubuğu ---- */
QStatusBar {{
    background: {p.surface};
    border-top: 1px solid {p.border};
    color: {p.text_muted};
    padding: 2px 6px;
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    padding: 0 6px;
    color: {p.text_muted};
}}

/* ---- Diğer Kontroller ---- */
QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
    color: {p.text};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    background: {p.window};
    color: {p.text};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {p.accent};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
    border: 2px solid {p.surface};
}}
QSlider::handle:horizontal:hover {{
    background: {p.accent_hover};
}}
QProgressBar {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 7px;
    text-align: center;
    height: 18px;
    color: {p.text};
}}
QProgressBar::chunk {{
    background: {p.accent};
    border-radius: 6px;
}}
QCheckBox, QRadioButton {{
    color: {p.text};
    spacing: 7px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {p.text_muted};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.text_muted};
    border-radius: 4px;
    background: {p.surface};
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.accent};
    background: {p.surface_alt};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: url("{check}");
}}
QRadioButton::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
    image: url("{dot}");
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {p.border};
    background: {p.window};
}}
QCheckBox::indicator:checked:disabled, QRadioButton::indicator:checked:disabled {{
    background: {p.text_muted};
    border-color: {p.text_muted};
}}
QToolTip {{
    background: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QSplitter::handle {{
    background: {p.border};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:hover {{
    background: {p.accent};
}}

/* ---- Belge tuvali ---- */
/* Genel ``QWidget`` kuralı görünüm arka planını da boyadığı için sayfa ile
   çevresi aynı renge düşüyordu; tuval rengi burada geri alınır. */
QGraphicsView {{
    background: {p.canvas};
    border: none;
}}
"""


def repolish(widget) -> None:
    """Özellik değiştikten sonra stil kurallarını yeniden uygular.

    Qt, ``QPushButton[accent="true"]`` gibi **özellik** seçicilerini yalnızca
    widget cilalanırken (polish) değerlendirir. ``QDialogButtonBox`` standart
    düğmelerini kendi kurucusunda cilaladığı için sonradan konan özellik
    dikkate alınmıyor, düğme vurgu rengini almıyordu.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


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
