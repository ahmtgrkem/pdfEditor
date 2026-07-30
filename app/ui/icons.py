"""Vektörel ikon kütüphanesi.

İkonlar SVG olarak gömülüdür; harici dosya bağımlılığı yoktur ve tema
rengine göre yeniden renklendirilir. Bu sayede PyInstaller paketi de
ek kaynak dosyası gerektirmez.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_S = 'fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"'
_F = 'fill="{c}" stroke="none"'

# 24x24 viewBox içinde çizilen ikon gövdeleri
_PATHS: dict[str, str] = {
    # --- dosya ---
    "new": f'<path {_S} d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path {_S} d="M14 3v5h5"/>',
    "open": f'<path {_S} d="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v1"/><path {_S} d="M3 8h17.5l-2.2 9a2 2 0 0 1-2 1.5H5a2 2 0 0 1-2-2z"/>',
    "save": f'<path {_S} d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path {_S} d="M17 21v-8H7v8M7 3v5h7"/>',
    "save_as": f'<path {_S} d="M19 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7"/><path {_S} d="M17 3l4 4-7 7h-4v-4z"/>',
    "print": f'<path {_S} d="M6 9V3h12v6"/><path {_S} d="M6 18H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect {_S} x="6" y="14" width="12" height="7" rx="1"/>',
    "close": f'<path {_S} d="M18 6L6 18M6 6l12 12"/>',
    "exit": f'<path {_S} d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path {_S} d="M16 17l5-5-5-5M21 12H9"/>',
    "properties": f'<circle {_S} cx="12" cy="12" r="9"/><path {_S} d="M12 16v-5M12 8h.01"/>',

    # --- düzenleme ---
    "undo": f'<path {_S} d="M3 7v6h6"/><path {_S} d="M3.5 13a9 9 0 1 1 2.1 6"/>',
    "redo": f'<path {_S} d="M21 7v6h-6"/><path {_S} d="M20.5 13a9 9 0 1 0-2.1 6"/>',
    "copy": f'<rect {_S} x="9" y="9" width="12" height="12" rx="2"/><path {_S} d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "search": f'<circle {_S} cx="11" cy="11" r="7"/><path {_S} d="M20 20l-3.6-3.6"/>',

    # --- görünüm / zoom ---
    "zoom_in": f'<circle {_S} cx="11" cy="11" r="7"/><path {_S} d="M20 20l-3.6-3.6M11 8v6M8 11h6"/>',
    "zoom_out": f'<circle {_S} cx="11" cy="11" r="7"/><path {_S} d="M20 20l-3.6-3.6M8 11h6"/>',
    "fit_page": f'<rect {_S} x="4" y="3" width="16" height="18" rx="2"/><path {_S} d="M8 8h8M8 12h8M8 16h5"/>',
    "fit_width": f'<rect {_S} x="3" y="5" width="18" height="14" rx="2"/><path {_S} d="M7 12h10M7 12l2-2M7 12l2 2M17 12l-2-2M17 12l-2 2"/>',
    "zoom_actual": f'<rect {_S} x="3" y="4" width="18" height="16" rx="2"/><path {_S} d="M8 15V9l-2 1.5M13 9h3v3h-3v3h3"/>',

    # --- sayfa gezinme ---
    "first": f'<path {_S} d="M17 18l-6-6 6-6M7 6v12"/>',
    "prev": f'<path {_S} d="M15 18l-6-6 6-6"/>',
    "next": f'<path {_S} d="M9 18l6-6-6-6"/>',
    "last": f'<path {_S} d="M7 6l6 6-6 6M17 6v12"/>',

    # --- döndürme ---
    "rotate_cw": f'<path {_S} d="M21 12a9 9 0 1 1-2.6-6.4"/><path {_S} d="M21 3v6h-6"/>',
    "rotate_ccw": f'<path {_S} d="M3 12a9 9 0 1 0 2.6-6.4"/><path {_S} d="M3 3v6h6"/>',

    # --- görünüm modları ---
    "view_single": f'<rect {_S} x="6" y="3" width="12" height="18" rx="2"/>',
    "view_continuous": f'<rect {_S} x="6" y="2" width="12" height="9" rx="1.5"/><rect {_S} x="6" y="13" width="12" height="9" rx="1.5"/>',
    "view_double": f'<rect {_S} x="2" y="4" width="9" height="16" rx="1.5"/><rect {_S} x="13" y="4" width="9" height="16" rx="1.5"/>',
    "sidebar": f'<rect {_S} x="3" y="4" width="18" height="16" rx="2"/><path {_S} d="M9 4v16"/>',

    # --- araçlar ---
    "select": f'<path {_S} d="M4 3l7.5 17.5 2.4-6.6 6.6-2.4z"/>',
    "hand": f'<path {_S} d="M8 12V5.5a1.5 1.5 0 1 1 3 0V11m0-.5V4.5a1.5 1.5 0 1 1 3 0V11m0-.5V6a1.5 1.5 0 1 1 3 0v7.5"/><path {_S} d="M8 12v-1a1.5 1.5 0 0 0-3 0v3.5a7 7 0 0 0 7 7h1a7 7 0 0 0 7-7V11"/>',
    "highlight": f'<path {_S} d="M14 3l7 7-8.5 8.5H6l-2-2z"/><path {_S} d="M3 21h18"/>',
    "underline": f'<path {_S} d="M7 4v6a5 5 0 0 0 10 0V4"/><path {_S} d="M5 20h14"/>',
    "strikethrough": f'<path {_S} d="M7 5.5A4 4 0 0 1 11 4h2a4 4 0 0 1 3.7 2.3"/><path {_S} d="M8 15a4 4 0 0 0 4 4h1.5a4 4 0 0 0 2.5-6.5"/><path {_S} d="M3 12h18"/>',
    "pencil": f'<path {_S} d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/><path {_S} d="M14.5 5.5l3 3"/>',
    "eraser": f'<path {_S} d="M19 20H8.5L3.4 14.9a2 2 0 0 1 0-2.8l8.1-8.1a2 2 0 0 1 2.8 0l6.3 6.3a2 2 0 0 1 0 2.8L14 20"/><path {_S} d="M8 20l6.5-6.5"/>',
    "shape_rect": f'<rect {_S} x="3.5" y="5.5" width="17" height="13" rx="1.5"/>',
    "shape_circle": f'<circle {_S} cx="12" cy="12" r="8.5"/>',
    "shape_line": f'<path {_S} d="M4 20L20 4"/>',
    "shape_arrow": f'<path {_S} d="M4 20L20 4M20 4h-7M20 4v7"/>',
    "text": f'<path {_S} d="M4 6V4h16v2"/><path {_S} d="M12 4v16M9 20h6"/>',
    "image": f'<rect {_S} x="3" y="4" width="18" height="16" rx="2"/><circle {_S} cx="8.5" cy="9.5" r="1.8"/><path {_S} d="M21 16l-5-5-6.5 6.5L7 15l-4 4"/>',
    "signature": f'<path {_S} d="M3 17c3.5 0 3.5-10 6.5-10S12 17 15 17s3-4 6-4"/><path {_S} d="M3 21h18"/>',
    "watermark": f'<path {_S} d="M12 3l5.5 7.2a7 7 0 1 1-11 0z"/><path {_S} d="M8.5 14.5h7"/>',

    # --- sayfa yönetimi ---
    "page_add": f'<rect {_S} x="4" y="3" width="16" height="18" rx="2"/><path {_S} d="M12 8v8M8 12h8"/>',
    "page_delete": f'<path {_S} d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path {_S} d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13"/><path {_S} d="M10 11v7M14 11v7"/>',
    "page_extract": f'<rect {_S} x="3" y="3" width="12" height="15" rx="2"/><path {_S} d="M21 9v10a2 2 0 0 1-2 2H9"/><path {_S} d="M9 10.5l3-3 3 3M12 7.5V15"/>',
    "page_duplicate": f'<rect {_S} x="8" y="3" width="13" height="15" rx="2"/><path {_S} d="M16 21H5a2 2 0 0 1-2-2V8"/>',
    "merge": f'<path {_S} d="M8 3v6a4 4 0 0 0 4 4h8"/><path {_S} d="M8 21v-6a4 4 0 0 1 4-4h8"/><path {_S} d="M17 9l3 4-3 4"/>',
    "split": f'<path {_S} d="M20 3v6a4 4 0 0 1-4 4H4"/><path {_S} d="M20 21v-6a4 4 0 0 0-4-4H4"/><path {_S} d="M7 9l-3 4 3 4"/>',

    # --- araçlar / dönüştürme ---
    "export_image": f'<rect {_S} x="3" y="3" width="18" height="14" rx="2"/><path {_S} d="M3 13l4-4 5 5"/><circle {_F} cx="15.5" cy="8" r="1.5"/><path {_S} d="M12 21h9M17 17l4 4-4 4" transform="translate(0,-4) scale(1,0.6)" opacity="0"/>',
    "compress": f'<path {_S} d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"/><path {_S} d="M8 12h8"/>',
    "lock": f'<rect {_S} x="4" y="10" width="16" height="11" rx="2"/><path {_S} d="M8 10V7a4 4 0 0 1 8 0v3"/><path {_S} d="M12 15v2"/>',
    "unlock": f'<rect {_S} x="4" y="10" width="16" height="11" rx="2"/><path {_S} d="M8 10V7a4 4 0 0 1 7.5-2"/><path {_S} d="M12 15v2"/>',

    # --- diğer ---
    "theme_dark": f'<path {_S} d="M21 13.5A9 9 0 1 1 10.5 3a7 7 0 0 0 10.5 10.5z"/>',
    "theme_light": f'<circle {_S} cx="12" cy="12" r="4.5"/><path {_S} d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "bookmark": f'<path {_S} d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "thumbnails": f'<rect {_S} x="3" y="3" width="7" height="7" rx="1.5"/><rect {_S} x="14" y="3" width="7" height="7" rx="1.5"/><rect {_S} x="3" y="14" width="7" height="7" rx="1.5"/><rect {_S} x="14" y="14" width="7" height="7" rx="1.5"/>',
    "help": f'<circle {_S} cx="12" cy="12" r="9"/><path {_S} d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.8-2.8 2.8M12 17h.01"/>',
}

_cache: dict[tuple[str, str, int], QIcon] = {}


def _render(body: str, color: str, size: int) -> QPixmap:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}">{body.format(c=color)}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(size, size)
    pm.setDevicePixelRatio(1.0)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pm


def icon(name: str, color: str | None = None, size: int = 22) -> QIcon:
    """İkonu tema rengiyle üretir.

    "Açık" (checked) durum **vurgu rengiyle** çizilir; vurgu metni rengiyle
    değil. Aynı ``QAction``ın simgesi hem araç çubuğunda hem menüde görünür:
    menü satırının zemini seçili olsa bile nötr kaldığı için beyaz simge
    kayboluyordu (açık temada onay işaretsiz boş satır olarak görünüyordu).
    Araç çubuğundaki basılı düğme de bu yüzden dolu vurgu zemini yerine
    vurgu çerçevesi kullanır (bkz. ``theme.stylesheet``).
    """
    palette = theme.current()
    color = color or palette.text
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    body = _PATHS.get(name)
    if body is None:
        result = QIcon()
    else:
        result = QIcon()
        for scale in (1, 2):
            result.addPixmap(_render(body, color, size * scale), QIcon.Normal, QIcon.Off)
            result.addPixmap(
                _render(body, palette.accent, size * scale), QIcon.Normal, QIcon.On
            )
            result.addPixmap(
                _render(body, palette.accent, size * scale), QIcon.Active, QIcon.On
            )
            result.addPixmap(
                _render(body, palette.text_muted, size * scale), QIcon.Disabled, QIcon.Off
            )
            # Liste/ağaç öğeleri seçildiğinde Qt ``Selected`` kipini kullanır;
            # satır vurgu rengiyle dolduğu için simge de vurgu metni rengine
            # geçmelidir (aksi hâlde koyu simge mavi zeminde kayboluyor).
            result.addPixmap(
                _render(body, palette.accent_text, size * scale), QIcon.Selected, QIcon.Off
            )
            result.addPixmap(
                _render(body, palette.accent_text, size * scale), QIcon.Selected, QIcon.On
            )
    _cache[key] = result
    return result



def clear_cache() -> None:
    """Tema değiştiğinde ikonların yeniden renklendirilmesi için."""
    _cache.clear()

