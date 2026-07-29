"""PDF görüntüleyici: sayfa düzeni, zoom, arama vurguları ve araç etkileşimi.

Sahne koordinatları *piksel* cinsindendir (zoom uygulanmış). Görünüm
dönüşümü kimlik matrisinde tutulur; böylece her zoom seviyesinde sayfa
MuPDF tarafından yeniden render edilir ve metin daima nettir.
"""
from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QMenu,
    QWidget,
)

from ..core import form_fields
from ..core.form_fields import FormField
from ..services.document_controller import DocumentController
from . import theme
from .file_drop import FileDropMixin
from .form_widgets import FormChoiceEditor, FormTextEditor
from .inline_text_editor import InlineCanvasTextWidget
from .tools import LINE_TOOLS, RECT_TOOLS, Tool, ToolState

PAGE_GAP = 18
PAGE_MARGIN = 26
MIN_ZOOM = 0.08
MAX_ZOOM = 8.0
ZOOM_STEPS = [0.10, 0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]


class ViewMode(str, Enum):
    SINGLE = "single"
    CONTINUOUS = "continuous"
    DOUBLE = "double"


class ZoomMode(str, Enum):
    CUSTOM = "custom"
    FIT_PAGE = "fit_page"
    FIT_WIDTH = "fit_width"


class PageItem(QGraphicsItem):
    """Tek bir PDF sayfasını çizen sahne öğesi."""

    def __init__(self, index: int, width_pt: float, height_pt: float) -> None:
        super().__init__()
        self.index = index
        self.width_pt = width_pt
        self.height_pt = height_pt
        self._zoom = 1.0
        self._image: QImage | None = None
        self._image_zoom = 0.0
        self.search_rects: list[QRectF] = []   # punto cinsinden
        self.active_rect: QRectF | None = None
        self.setAcceptHoverEvents(False)
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, True)

    # -- geometri ------------------------------------------------------
    def set_zoom(self, zoom: float) -> None:
        if abs(zoom - self._zoom) > 1e-6:
            self.prepareGeometryChange()
            self._zoom = zoom

    @property
    def zoom(self) -> float:
        return self._zoom

    def pixel_size(self) -> tuple[float, float]:
        return self.width_pt * self._zoom, self.height_pt * self._zoom

    def boundingRect(self) -> QRectF:  # noqa: N802
        w, h = self.pixel_size()
        return QRectF(0, 0, w, h)

    # -- içerik --------------------------------------------------------
    def set_image(self, image: QImage, zoom: float) -> None:
        self._image = image
        self._image_zoom = zoom
        self.update()

    def clear_image(self) -> None:
        self._image = None
        self._image_zoom = 0.0
        self.update()

    def has_current_image(self) -> bool:
        return self._image is not None and abs(self._image_zoom - self._zoom) < 1e-6

    # -- çizim ---------------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None) -> None:  # noqa: D102, N802
        pal = theme.current()
        rect = self.boundingRect()

        # gölge
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(pal.page_shadow))
        painter.drawRoundedRect(rect.adjusted(3, 4, 3, 5), 2, 2)

        # kağıt
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(rect)

        if self._image is not None:
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawImage(rect, self._image)
        else:
            painter.setPen(QPen(QColor(pal.border), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        # arama vurguları
        if self.search_rects:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 214, 0, 90))
            for r in self.search_rects:
                painter.drawRect(self._to_px(r))
        if self.active_rect is not None:
            painter.setBrush(QColor(255, 145, 0, 130))
            painter.setPen(QPen(QColor(255, 111, 0), 1.5))
            painter.drawRect(self._to_px(self.active_rect))

        # kenarlık
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

    def _to_px(self, r: QRectF) -> QRectF:
        z = self._zoom
        return QRectF(r.x() * z, r.y() * z, r.width() * z, r.height() * z)


class PdfView(FileDropMixin, QGraphicsView):
    """Ana görüntüleyici bileşeni.

    ``FileDropMixin`` şart: ``QGraphicsView`` sürükleme olaylarını kendi
    viewport'unda tükettiği için, karışım olmadan belge alanına bırakılan
    dosya ana pencereye hiç ulaşmaz.
    """

    currentPageChanged = Signal(int)
    zoomChanged = Signal(float)
    status = Signal(str)
    requestText = Signal(int, object)       # page, QRectF (punto)
    requestImage = Signal(int, object)
    requestSignature = Signal(int, object)

    def __init__(self, controller: DocumentController, tools: ToolState, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.tools = tools

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._setup_file_drops()

        self._items: list[PageItem] = []
        self._zoom = 1.0
        self._zoom_mode = ZoomMode.FIT_WIDTH
        self._view_mode = ViewMode.CONTINUOUS
        self._current = 0
        self._suppress_scroll = False

        # etkileşim durumu
        self._drag_page: PageItem | None = None
        self._drag_start = QPointF()
        self._drag_current = QPointF()
        self._dragging = False
        self._strokes: list[list[QPointF]] = []
        self._panning = False
        self._pan_origin = QPoint()
        self._space_pan = False
        self._selection_rect: QRectF | None = None
        self._selection_page = 0
        #: Aktif canlı metin düzenleyici (yeni metin veya mevcut metnin düzenlenmesi)
        self._live_text_widget: InlineCanvasTextWidget | None = None
        #: ``_live_text_widget`` ile aynı nesne — geriye dönük uyumluluk adı
        self.inline_editor: InlineCanvasTextWidget | None = None
        #: Mevcut metin düzenleniyorsa ``find_text_at_point`` sonucu; yeni metinde None
        self._editing_info: dict | None = None
        #: Kutu dışına tıklayarak onaylandı — takip eden release yutulur
        self._just_committed_inline = False
        #: Açık form alanı düzenleyicisi (metin/açılır liste)
        self._form_editor: QWidget | None = None
        #: Düzenlenen alan
        self._form_field: FormField | None = None
        #: İmleç şu an bir form alanının üzerinde mi
        self._form_cursor_on = False
        #: Form alanı üzerinde gezinirken imleç değişsin
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        controller.renderer.pageReady.connect(self._on_page_ready)
        controller.documentReplaced.connect(self.rebuild)
        controller.documentOpened.connect(lambda _: self.rebuild())
        controller.documentClosed.connect(self.rebuild)
        controller.pageContentChanged.connect(self._on_page_content_changed)
        tools.toolChanged.connect(self._on_tool_changed)
        self.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self._update_visible())

        self._apply_background()

    # ==================================================================
    # Kurulum
    # ==================================================================
    def _apply_background(self) -> None:
        self.setBackgroundBrush(QBrush(QColor(theme.current().canvas)))

    def refresh_theme(self) -> None:
        self._apply_background()
        for item in self._items:
            item.update()

    def rebuild(self) -> None:
        """Belge yapısı değiştiğinde sahneyi sıfırdan kurar."""
        self._discard_live_text_widget()
        self._scene.clear()
        self._items.clear()
        if not self.controller.is_open:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            self.viewport().update()
            return

        doc = self.controller.document
        for i in range(doc.page_count):
            try:
                w, h = doc.page_size(i)
            except Exception:  # noqa: BLE001
                w, h = 595.0, 842.0
            item = PageItem(i, w, h)
            self._items.append(item)
            self._scene.addItem(item)

        self._current = min(self._current, len(self._items) - 1)
        self._recompute_zoom()
        self.relayout()
        self.go_to_page(self._current, force=True)

    # ==================================================================
    # Düzen
    # ==================================================================
    @property
    def view_mode(self) -> ViewMode:
        return self._view_mode

    def set_view_mode(self, mode: ViewMode) -> None:
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self._recompute_zoom()
        self.relayout()
        self.go_to_page(self._current, force=True)

    def _rows(self) -> list[list[PageItem]]:
        """Görünüm moduna göre sayfa satırları."""
        if not self._items:
            return []
        if self._view_mode is ViewMode.SINGLE:
            idx = max(0, min(self._current, len(self._items) - 1))
            return [[self._items[idx]]]
        if self._view_mode is ViewMode.DOUBLE:
            return [self._items[i:i + 2] for i in range(0, len(self._items), 2)]
        return [[item] for item in self._items]

    def relayout(self) -> None:
        rows = self._rows()
        visible_items = {id(it) for row in rows for it in row}
        for item in self._items:
            item.setVisible(id(item) in visible_items)
            item.set_zoom(self._zoom)

        if not rows:
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return

        row_sizes = []
        for row in rows:
            w = sum(it.pixel_size()[0] for it in row) + PAGE_GAP * (len(row) - 1)
            h = max(it.pixel_size()[1] for it in row)
            row_sizes.append((w, h))

        content_w = max(w for w, _ in row_sizes)
        total_h = sum(h for _, h in row_sizes) + PAGE_GAP * (len(rows) - 1)

        y = PAGE_MARGIN
        for row, (row_w, row_h) in zip(rows, row_sizes):
            x = PAGE_MARGIN + (content_w - row_w) / 2
            for item in row:
                iw, ih = item.pixel_size()
                item.setPos(x, y + (row_h - ih) / 2)
                x += iw + PAGE_GAP
            y += row_h + PAGE_GAP

        self._scene.setSceneRect(
            QRectF(0, 0, content_w + PAGE_MARGIN * 2, total_h + PAGE_MARGIN * 2)
        )
        self._update_visible()
        self._position_inline_text_widget()

    # ==================================================================
    # Zoom
    # ==================================================================
    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def zoom_mode(self) -> ZoomMode:
        return self._zoom_mode

    def _reference_page(self) -> PageItem | None:
        if not self._items:
            return None
        idx = max(0, min(self._current, len(self._items) - 1))
        return self._items[idx]

    def _recompute_zoom(self) -> None:
        """Sığdırma modlarında zoom katsayısını yeniden hesaplar."""
        item = self._reference_page()
        if item is None or self._zoom_mode is ZoomMode.CUSTOM:
            return
        vw = max(80, self.viewport().width() - 2 * PAGE_MARGIN - 16)
        vh = max(80, self.viewport().height() - 2 * PAGE_MARGIN)
        per_row = 2 if self._view_mode is ViewMode.DOUBLE and len(self._items) > 1 else 1
        page_w = item.width_pt * per_row + (PAGE_GAP / max(self._zoom, 0.01)) * (per_row - 1)

        if self._zoom_mode is ZoomMode.FIT_WIDTH:
            zoom = vw / max(page_w, 1.0)
        else:
            zoom = min(vw / max(page_w, 1.0), vh / max(item.height_pt, 1.0))
        self._set_zoom_value(max(MIN_ZOOM, min(MAX_ZOOM, zoom)))

    def _set_zoom_value(self, zoom: float) -> None:
        if abs(zoom - self._zoom) < 1e-4:
            return
        self._zoom = zoom
        self.zoomChanged.emit(zoom)

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        """Serbest zoom; ``anchor`` verilirse o nokta sabit kalır."""
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self._zoom) < 1e-4:
            return

        keep = self._anchor_state(anchor)
        self._zoom_mode = ZoomMode.CUSTOM
        self._set_zoom_value(zoom)
        self.relayout()
        self._restore_anchor(keep, anchor)

    def _anchor_state(self, anchor: QPointF | None):
        if anchor is None:
            item = self._reference_page()
            if item is None:
                return None
            center = self.mapToScene(self.viewport().rect().center())
            rel = (center - item.pos()) / max(self._zoom, 1e-6)
            return ("center", item.index, rel)
        scene_pos = self.mapToScene(anchor.toPoint())
        item = self._item_at_scene(scene_pos)
        if item is None:
            return None
        rel = (scene_pos - item.pos()) / max(self._zoom, 1e-6)
        return ("cursor", item.index, rel)

    def _restore_anchor(self, state, anchor: QPointF | None) -> None:
        if state is None:
            return
        kind, index, rel = state
        if index >= len(self._items):
            return
        item = self._items[index]
        target = item.pos() + rel * self._zoom
        if kind == "cursor" and anchor is not None:
            delta = target - self.mapToScene(anchor.toPoint())
            self._scroll_by(delta)
        else:
            self.centerOn(target)

    def _scroll_by(self, delta: QPointF) -> None:
        self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() + delta.x()))
        self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() + delta.y()))

    def zoom_in(self) -> None:
        for step in ZOOM_STEPS:
            if step > self._zoom + 1e-4:
                self.set_zoom(step)
                return
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        for step in reversed(ZOOM_STEPS):
            if step < self._zoom - 1e-4:
                self.set_zoom(step)
                return
        self.set_zoom(self._zoom / 1.25)

    def set_zoom_mode(self, mode: ZoomMode) -> None:
        self._zoom_mode = mode
        if mode is ZoomMode.CUSTOM:
            return
        self._recompute_zoom()
        self.relayout()
        self.go_to_page(self._current, force=True)

    def zoom_actual(self) -> None:
        self.set_zoom(1.0)

    # ==================================================================
    # Gezinme
    # ==================================================================
    @property
    def current_page(self) -> int:
        return self._current

    def go_to_page(self, index: int, force: bool = False, top: bool = True) -> None:
        if not self._items:
            return
        index = max(0, min(index, len(self._items) - 1))
        changed = index != self._current
        self._current = index
        self.controller.set_current_page(index)

        if self._view_mode is ViewMode.SINGLE:
            self.relayout()
            self.verticalScrollBar().setValue(0)
        else:
            item = self._items[index]
            self._suppress_scroll = True
            if top:
                self.verticalScrollBar().setValue(int(item.pos().y()) - PAGE_MARGIN // 2)
            else:
                self.centerOn(item.pos() + QPointF(*item.pixel_size()) / 2)
            self._suppress_scroll = False

        if changed or force:
            self.currentPageChanged.emit(index)
        self._update_visible()

    def next_page(self) -> None:
        step = 2 if self._view_mode is ViewMode.DOUBLE else 1
        self.go_to_page(self._current + step)

    def prev_page(self) -> None:
        step = 2 if self._view_mode is ViewMode.DOUBLE else 1
        self.go_to_page(self._current - step)

    def first_page(self) -> None:
        self.go_to_page(0)

    def last_page(self) -> None:
        self.go_to_page(len(self._items) - 1)

    def _on_scrolled(self, _value: int) -> None:
        if self._suppress_scroll or self._view_mode is ViewMode.SINGLE:
            self._update_visible()
            return
        self._update_visible()
        top = self.mapToScene(QPoint(self.viewport().width() // 2, 8))
        best = None
        for item in self._items:
            if not item.isVisible():
                continue
            r = QRectF(item.pos(), QRectF(0, 0, *item.pixel_size()).size())
            if r.bottom() >= top.y():
                best = item
                break
        if best is not None and best.index != self._current:
            self._current = best.index
            self.controller.set_current_page(best.index)
            self.currentPageChanged.emit(best.index)

    # ==================================================================
    # Render yönetimi
    # ==================================================================
    def _visible_indices(self) -> list[int]:
        if not self._items:
            return []
        view_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        margin = view_rect.height() * 0.6
        probe = view_rect.adjusted(0, -margin, 0, margin)
        out = []
        for item in self._items:
            if not item.isVisible():
                continue
            w, h = item.pixel_size()
            if probe.intersects(QRectF(item.pos().x(), item.pos().y(), w, h)):
                out.append(item.index)
        return out

    def _reposition_form_editor(self) -> None:
        """Kaydırma/yakınlaştırma sonrası düzenleyiciyi alanın üstünde tutar.

        Yerinden kaymış bir düzenleyici, girilen değerin başka bir alana
        yazılacağı izlenimi verir.
        """
        if self._form_editor is None or self._form_field is None:
            return
        item = next(
            (i for i in self._items if i.index == self._form_field.page_index), None
        )
        if item is None:
            self.close_form_editor()
            return
        self._place_form_editor(item, self._form_field)

    def _update_visible(self) -> None:
        self._reposition_form_editor()
        if not self.controller.is_open:
            return
        dpr = self.devicePixelRatioF()
        visible = self._visible_indices()
        for index in visible:
            item = self._items[index]
            if item.has_current_image():
                continue
            image = self.controller.renderer.request_page(index, self._zoom * dpr)
            if image is not None:
                image.setDevicePixelRatio(dpr)
                item.set_image(image, self._zoom)
        # uzaktaki sayfaların pikselleri bırakılır (önbellek zaten tutuyor)
        keep = set(visible)
        for item in self._items:
            if item.index not in keep and item._image is not None:  # noqa: SLF001
                far = abs(item.index - self._current) > 6
                if far:
                    item.clear_image()

    def _on_page_ready(self, index: int, zoom: float, image: QImage) -> None:
        if index >= len(self._items):
            return
        dpr = self.devicePixelRatioF()
        logical = zoom / dpr
        if abs(logical - self._zoom) > 1e-3:
            return  # eski zoom seviyesine ait, at
        image.setDevicePixelRatio(dpr)
        self._items[index].set_image(image, self._zoom)

    def _on_page_content_changed(self, index: int) -> None:
        for item in self._items:
            item.clear_image()
        self._update_visible()
        self.viewport().update()

    # ==================================================================
    # Arama vurguları
    # ==================================================================
    def set_search_results(self, hits: dict[int, list[tuple[float, float, float, float]]]) -> None:
        for item in self._items:
            rects = hits.get(item.index) or []
            item.search_rects = [QRectF(r[0], r[1], r[2] - r[0], r[3] - r[1]) for r in rects]
            item.active_rect = None
            item.update()

    def set_active_hit(self, page: int, rect: tuple[float, float, float, float] | None) -> None:
        for item in self._items:
            if item.active_rect is not None:
                item.active_rect = None
                item.update()
        if rect is None or not (0 <= page < len(self._items)):
            return
        item = self._items[page]
        item.active_rect = QRectF(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
        item.update()
        self.ensure_visible_pt(page, rect)

    def ensure_visible_pt(self, page: int, rect: tuple[float, float, float, float]) -> None:
        if not (0 <= page < len(self._items)):
            return
        if self._view_mode is ViewMode.SINGLE and page != self._current:
            self.go_to_page(page)
        item = self._items[page]
        z = self._zoom
        scene_rect = QRectF(
            item.pos().x() + rect[0] * z,
            item.pos().y() + rect[1] * z,
            max(4.0, (rect[2] - rect[0]) * z),
            max(4.0, (rect[3] - rect[1]) * z),
        )
        self.ensureVisible(scene_rect, 80, 120)

    def clear_search(self) -> None:
        for item in self._items:
            item.search_rects = []
            item.active_rect = None
            item.update()

    # ==================================================================
    # Olaylar
    # ==================================================================
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._zoom_mode is not ZoomMode.CUSTOM:
            self._recompute_zoom()
            self.relayout()
        self._update_visible()
        self._position_inline_text_widget()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        """Kaydırma sırasında canlı metin kutusu sayfayla birlikte hareket eder."""
        super().scrollContentsBy(dx, dy)
        self._position_inline_text_widget()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                factor = 1.12 if delta > 0 else 1 / 1.12
                self.set_zoom(self._zoom * factor, anchor=event.position())
            event.accept()
            return
        if self._view_mode is ViewMode.SINGLE:
            bar = self.verticalScrollBar()
            at_bottom = bar.value() >= bar.maximum() - 1
            at_top = bar.value() <= bar.minimum() + 1
            delta = event.angleDelta().y()
            if delta < 0 and at_bottom and self._current < len(self._items) - 1:
                self.next_page()
                event.accept()
                return
            if delta > 0 and at_top and self._current > 0:
                self.prev_page()
                self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
                event.accept()
                return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if key in (Qt.Key_PageDown,):
            self.next_page()
            event.accept()
            return
        if key in (Qt.Key_PageUp,):
            self.prev_page()
            event.accept()
            return
        if key == Qt.Key_Home and event.modifiers() & Qt.ControlModifier:
            self.first_page()
            event.accept()
            return
        if key == Qt.Key_End and event.modifiers() & Qt.ControlModifier:
            self.last_page()
            event.accept()
            return
        if key == Qt.Key_Escape:
            self._cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_pan = False
            self._sync_cursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _on_tool_changed(self, _tool: Tool) -> None:
        # Başka bir araca geçilirse yazılmakta olan metin kaybolmasın.
        # (Onay slotu widget'ı zaten kaldırdığı için özyineleme oluşmaz.)
        if self._live_text_widget is not None:
            self.commit_live_text_widget()
        self._cancel_drag()
        self._sync_cursor()

    def _sync_cursor(self) -> None:
        from .tools import CURSORS

        if self._space_pan or self._panning:
            self.viewport().setCursor(Qt.ClosedHandCursor if self._panning else Qt.OpenHandCursor)
            return
        self.viewport().setCursor(CURSORS.get(self.tools.tool, Qt.ArrowCursor))

    # -- yardımcılar ---------------------------------------------------
    def _item_at_scene(self, scene_pos: QPointF) -> PageItem | None:
        for item in self._items:
            if not item.isVisible():
                continue
            w, h = item.pixel_size()
            if QRectF(item.pos().x(), item.pos().y(), w, h).contains(scene_pos):
                return item
        return None

    def _nearest_item(self, scene_pos: QPointF) -> PageItem | None:
        best, best_d = None, float("inf")
        for item in self._items:
            if not item.isVisible():
                continue
            w, h = item.pixel_size()
            r = QRectF(item.pos().x(), item.pos().y(), w, h)
            dx = max(r.left() - scene_pos.x(), 0, scene_pos.x() - r.right())
            dy = max(r.top() - scene_pos.y(), 0, scene_pos.y() - r.bottom())
            d = dx * dx + dy * dy
            if d < best_d:
                best, best_d = item, d
        return best

    def _to_page_pt(self, item: PageItem, scene_pos: QPointF) -> QPointF:
        local = scene_pos - item.pos()
        return QPointF(local.x() / self._zoom, local.y() / self._zoom)

    def _clamp_to_page(self, item: PageItem, pt: QPointF) -> QPointF:
        return QPointF(
            max(0.0, min(pt.x(), item.width_pt)),
            max(0.0, min(pt.y(), item.height_pt)),
        )

    def _drag_rect_pt(self) -> QRectF:
        return QRectF(self._drag_start, self._drag_current).normalized()

    def _cancel_drag(self) -> None:
        self._dragging = False
        self._drag_page = None
        self._strokes.clear()
        self._selection_rect = None
        self.viewport().update()

    # ==================================================================
    # Etkileşimli form alanları
    # ==================================================================
    def _form_field_at(self, item: PageItem, pt: QPointF) -> FormField | None:
        """Sayfa noktasındaki düzenlenebilir form alanı."""
        if not self.controller.is_open:
            return None
        try:
            return form_fields.field_at(
                self.controller.document, item.index, pt.x(), pt.y()
            )
        except Exception:  # noqa: BLE001 - bozuk/kapanan belge
            return None

    def _handle_form_click(self, item: PageItem, pt: QPointF) -> bool:
        """Form alanına tıklamayı işler. ``True`` -> olay tüketildi."""
        alan = self._form_field_at(item, pt)
        if alan is None:
            return False

        if alan.is_toggle:
            # Onay kutusu/radyo düzenleyici gerektirmez: tek tıkla çevrilir.
            etiket = "Onay kutusu" if alan.type == "check" else "Seçim"
            with self.controller.edit(etiket, page=item.index) as doc:
                if not form_fields.toggle(doc, alan):
                    self.controller.undo_silently()
            return True

        self._open_form_editor(item, alan)
        return True

    def _open_form_editor(self, item: PageItem, field: FormField) -> None:
        """Alanın tam üzerine bir düzenleyici yerleştirir."""
        self.close_form_editor()

        if field.type in ("combo", "list") and field.options:
            editor: QWidget = FormChoiceEditor(field, self.viewport())
        else:
            editor = FormTextEditor(field, self.viewport())

        editor.committed.connect(
            lambda deger, f=field: self._commit_form_editor(f, deger)
        )
        editor.cancelled.connect(self.close_form_editor)

        self._form_editor = editor
        self._form_field = field
        self._place_form_editor(item, field)
        editor.show()
        editor.setFocus(Qt.MouseFocusReason)

    def _place_form_editor(self, item: PageItem, field: FormField) -> None:
        """Düzenleyiciyi alanın ekran karşılığına oturtur."""
        if self._form_editor is None:
            return
        x0, y0, x1, y1 = field.rect
        ust_sol = self.mapFromScene(
            item.pos() + QPointF(x0 * self._zoom, y0 * self._zoom)
        )
        alt_sag = self.mapFromScene(
            item.pos() + QPointF(x1 * self._zoom, y1 * self._zoom)
        )
        genislik = max(alt_sag.x() - ust_sol.x(), 40)
        # Çok kısa alanlarda düzenleyici okunmaz olur; asgari yükseklik verilir.
        yukseklik = max(alt_sag.y() - ust_sol.y(), 20)
        self._form_editor.setGeometry(ust_sol.x(), ust_sol.y(), genislik, yukseklik)

    def _commit_form_editor(self, field: FormField, value: str) -> None:
        self.close_form_editor()
        if value == field.value:
            return
        with self.controller.edit("Form alanı", page=field.page_index) as doc:
            if not form_fields.set_value(doc, field.page_index, field.name, value):
                self.controller.undo_silently()

    def close_form_editor(self) -> None:
        """Açık düzenleyiciyi **kaydetmeden** kapatır.

        Önce ``cancel()`` çağrılır: ``hide()`` odak kaybı üretir, odak kaybı
        da onaylama sayıldığı için işaretlenmezse iptal edilmiş değer yine
        yazılır. (Başka bir yere tıklayarak onaylama zaten odak kaybıyla,
        buraya gelmeden gerçekleşir.)
        """
        if self._form_editor is None:
            return
        editor, self._form_editor = self._form_editor, None
        self._form_field = None
        iptal = getattr(editor, "cancel", None)
        if callable(iptal):
            iptal()
        editor.hide()
        editor.deleteLater()

    # -- fare ----------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton or self._space_pan or self.tools.tool is Tool.HAND:
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self._sync_cursor()
            event.accept()
            return

        if event.button() != Qt.LeftButton or not self.controller.is_open:
            super().mousePressEvent(event)
            return

        # Boş bir alana tıklamak metni onaylar; ardından araç SELECT'e döner
        # (slot içinde) ve yeni bir kutu AÇILMAZ.
        if self._live_text_widget is not None:
            vp_pos = event.position().toPoint()
            if not self._live_text_widget.geometry().contains(vp_pos):
                self.commit_live_text_widget()
                self._just_committed_inline = True
                event.accept()
                return

        scene_pos = self.mapToScene(event.position().toPoint())
        item = self._item_at_scene(scene_pos) or self._nearest_item(scene_pos)
        if item is None:
            super().mousePressEvent(event)
            return

        if item.index != self._current and self._view_mode is not ViewMode.SINGLE:
            self._current = item.index
            self.controller.set_current_page(item.index)
            self.currentPageChanged.emit(item.index)

        pt = self._clamp_to_page(item, self._to_page_pt(item, scene_pos))

        # Form alanları yalnızca seçim aracındayken etkileşimlidir; aksi hâlde
        # alanın üzerine açıklama eklemek imkânsız olurdu.
        if self.tools.tool is Tool.SELECT:
            if self._form_editor is not None:
                self.close_form_editor()
            if self._handle_form_click(item, pt):
                event.accept()
                return

        self._drag_page = item
        self._drag_start = pt
        self._drag_current = pt
        self._dragging = True
        tool = self.tools.tool

        if tool is Tool.PENCIL:
            self._strokes = [[pt]]
        elif tool is Tool.SELECT:
            self._selection_rect = None
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            pos = event.position().toPoint()
            delta = pos - self._pan_origin
            self._pan_origin = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self._dragging and self._drag_page is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            pt = self._clamp_to_page(self._drag_page, self._to_page_pt(self._drag_page, scene_pos))
            self._drag_current = pt
            if self.tools.tool is Tool.PENCIL and self._strokes:
                last = self._strokes[-1][-1]
                if (pt - last).manhattanLength() >= 1.2:
                    self._strokes[-1].append(pt)
            self.viewport().update()
            event.accept()
            return

        self._update_form_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def _update_form_cursor(self, vp_pos) -> None:
        """Form alanının üzerinde imleci el/metin imlecine çevirir.

        Tıklanabilir olduğu görsel olarak belli olmazsa kullanıcı alanların
        yalnızca resim olduğunu düşünür.
        """
        if (self.tools.tool is not Tool.SELECT or self._panning
                or not self.controller.is_open):
            return
        scene_pos = self.mapToScene(vp_pos)
        item = self._item_at_scene(scene_pos)
        alan = None
        if item is not None:
            alan = self._form_field_at(item, self._to_page_pt(item, scene_pos))
        if alan is None:
            if self._form_cursor_on:
                self._form_cursor_on = False
                self._sync_cursor()
            return
        if not self._form_cursor_on:
            self._form_cursor_on = True
        self.viewport().setCursor(
            Qt.PointingHandCursor if alan.is_toggle else Qt.IBeamCursor
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_just_committed_inline", False):
            self._just_committed_inline = False
            event.accept()
            return

        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self._sync_cursor()
            event.accept()
            return

        if not (self._dragging and self._drag_page is not None and event.button() == Qt.LeftButton):
            super().mouseReleaseEvent(event)
            return

        item = self._drag_page
        rect = self._drag_rect_pt()
        tool = self.tools.tool
        self._dragging = False
        self._drag_page = None

        try:
            self._commit_tool(tool, item, rect)
        finally:
            self._strokes.clear()
            self.viewport().update()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._live_text_widget is not None:
            event.accept()
            return
        if event.button() == Qt.LeftButton and self.controller.is_open:
            scene_pos = self.mapToScene(event.position().toPoint())
            item = self._item_at_scene(scene_pos) or self._nearest_item(scene_pos)
            if item is not None:
                pt = self._to_page_pt(item, scene_pos)
                info = self.controller.find_text_at_point(item.index, (pt.x(), pt.y()))
                if info is not None:
                    self.start_inline_editing(item, info)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    # ==================================================================
    # Canlı metin düzenleyici
    # ==================================================================
    def start_inline_editing(self, item: PageItem, info: dict) -> None:
        """Var olan bir metin span'ını canlı düzenleyiciye yükler.

        Kutunun sol-üstü span'ın ``bbox`` üstüne değil, tespit edilen taban
        çizgisinden geri hesaplanan satır üstüne oturtulur; böylece yazarken
        metin, altındaki orijinal metinle birebir çakışır.
        """
        from ..core import fonts
        from ..core.annotations import TextStyle

        self._discard_live_text_widget()

        style = TextStyle(
            family=info.get("font", fonts.DEFAULT_FAMILY),
            size=float(info.get("size", 14.0)),
            color=info.get("color", (0.0, 0.0, 0.0)),
            bold=bool(info.get("bold", False)),
            italic=bool(info.get("italic", False)),
        )
        rect = info.get("rect") or (0.0, 0.0, 0.0, 0.0)
        origin = info.get("origin")
        if origin is not None:
            # Satırın üst kenarı = baseline - ascent
            asc = fonts.ascender(style.family, style.bold, style.italic)
            top = float(origin[1]) - asc * style.size
            left = float(origin[0])
        else:
            left, top = float(rect[0]), float(rect[1])
        box = (left, top, max(float(rect[2]), left + 40.0), max(float(rect[3]), top + style.size))

        widget = self._make_live_text_widget(item.index, box, style)
        widget.editor.setPlainText(info.get("text", ""))
        widget.editor.selectAll()
        if origin is not None:
            # Kutuyu düzenleyicinin kendi metrikleriyle taban çizgisine oturt;
            # böylece onay anındaki origin, tespit edilen origin ile aynı olur.
            widget.align_baseline_to(float(origin[1]))
        self._editing_info = info
        self._show_live_text_widget(widget)

    def start_new_inline_text(
        self, page_index: int, rect_t: tuple[float, float, float, float]
    ) -> None:
        """Boş bir metin kutusu açar."""
        self._discard_live_text_widget()
        self._editing_info = None
        widget = self._make_live_text_widget(page_index, rect_t, self.tools.defaults.text)
        self._show_live_text_widget(widget)

    def _make_live_text_widget(
        self, page_index: int, rect_t, style
    ) -> InlineCanvasTextWidget:
        widget = InlineCanvasTextWidget(
            page_index=page_index,
            pdf_rect=rect_t,
            zoom=self._zoom,
            default_style=style,
            parent=self.viewport(),
        )
        widget.commitRequested.connect(self._on_inline_text_committed)
        widget.cancelRequested.connect(self._on_inline_text_cancelled)
        widget.rectChanged.connect(self._position_inline_text_widget)
        self._live_text_widget = widget
        self.inline_editor = widget
        return widget

    def _show_live_text_widget(self, widget) -> None:
        self._position_inline_text_widget()
        widget.show()
        widget.raise_()
        widget.editor.setFocus()
        self.viewport().update()

    def _discard_live_text_widget(self):
        """Aktif widget'ı yazmadan kaldırır ve referansını döndürür."""
        widget = self._live_text_widget
        self._live_text_widget = None
        self.inline_editor = None
        self._editing_info = None
        if widget is not None:
            widget.hide()
            widget.deleteLater()
        return widget

    def commit_live_text_widget(self) -> None:
        if self._live_text_widget is not None:
            self._live_text_widget.commit()

    #: Geriye dönük ad — çift tıkla açılan düzenleyiciyi onaylar
    commit_inline_editing = commit_live_text_widget

    def _position_inline_text_widget(self) -> None:
        """Widget'ı, ilk karakteri PDF ``(x0, y0)`` noktasına gelecek şekilde koyar."""
        # Kurulum sırasında (QGraphicsView __init__) çağrılabilir.
        w = getattr(self, "_live_text_widget", None)
        if w is None or not (0 <= w.page_index < len(self._items)):
            return
        item = self._items[w.page_index]
        w.set_zoom(self._zoom)

        z = self._zoom
        x0, y0 = w.pdf_rect[0], w.pdf_rect[1]
        scene_pt = QPointF(item.pos().x() + x0 * z, item.pos().y() + y0 * z)
        vp_pt = self.mapFromScene(scene_pt)

        # Araç çubuğu görünümün üstünden taşacaksa kutunun altına alınır;
        # metin hizası hiçbir koşulda bozulmaz.
        w.set_toolbar_below(vp_pt.y() - w.text_origin_y(toolbar_below=False) < 0)
        offset = w.text_origin()
        w.move(vp_pt.x() - offset.x(), vp_pt.y() - offset.y())
        w.raise_()

    def _on_inline_text_committed(self, result) -> None:
        info = self._editing_info
        self._discard_live_text_widget()

        self.tools.defaults.text = result.style
        if info is not None:
            # Var olan metnin üzerine yazılıyor: önce eskisini temizle.
            ok = self.controller.replace_text(
                result.page_index,
                info["rect"],
                result.text,
                result.style,
                origin=result.origin,
                line_height=result.line_height,
            )
            message = "Metin güncellendi." if ok else "Metin güncellenemedi."
        else:
            ok = self.controller.add_text(
                result.page_index,
                result.rect,
                result.text,
                result.style,
                origin=result.origin,
                line_height=result.line_height,
            )
            message = "Metin eklendi." if ok else "Metin eklenemedi."
        if ok:
            self.status.emit(message)
        # Metin aracı tek kullanımlıktır: onaydan sonra seçim moduna dön.
        self.tools.set_tool(Tool.SELECT)
        self.viewport().update()

    def _on_inline_text_cancelled(self) -> None:
        self._discard_live_text_widget()
        self.tools.set_tool(Tool.SELECT)
        self.viewport().update()

    def _commit_tool(self, tool: Tool, item: PageItem, rect: QRectF) -> None:
        from ..core.annotations import ShapeKind
        from .tools import MARKUP_MAP, SHAPE_MAP

        page = item.index
        rect_t = (rect.left(), rect.top(), rect.right(), rect.bottom())
        p1 = (self._drag_start.x(), self._drag_start.y())
        p2 = (self._drag_current.x(), self._drag_current.y())

        if tool in MARKUP_MAP:
            if rect.width() < 2 and rect.height() < 2:
                return
            self.controller.add_markup(
                page, rect_t, MARKUP_MAP[tool], self.tools.pen_style(for_markup=True)
            )
        elif tool is Tool.PENCIL:
            strokes = [[(p.x(), p.y()) for p in s] for s in self._strokes]
            self.controller.add_ink(page, strokes, self.tools.pen_style())
        elif tool is Tool.ERASER:
            if rect.width() < 3 and rect.height() < 3:
                self.controller.erase_at(page, p2)
            else:
                self.controller.erase_in(page, rect_t)
        elif tool in SHAPE_MAP:
            kind: ShapeKind = SHAPE_MAP[tool]
            if kind in (ShapeKind.LINE, ShapeKind.ARROW):
                self.controller.add_shape(page, kind, p1, p2, self.tools.pen_style())
            else:
                self.controller.add_shape(page, kind, p1, p2, self.tools.pen_style())
        elif tool is Tool.TEXT:
            box = rect if rect.width() > 12 and rect.height() > 10 else QRectF(
                rect.left(), rect.top(), 260, 60
            )
            box_t = (box.left(), box.top(), box.right(), box.bottom())
            self.start_new_inline_text(page, box_t)
        elif tool is Tool.IMAGE:
            if rect.width() > 8 and rect.height() > 8:
                self.requestImage.emit(page, rect)
            else:
                self.status.emit("Görsel için bir alan sürükleyin.")
        elif tool is Tool.SIGNATURE:
            box = rect if rect.width() > 20 and rect.height() > 12 else QRectF(
                rect.left(), rect.top(), 180, 70
            )
            self.requestSignature.emit(page, box)
        elif tool is Tool.SELECT:
            if rect.width() > 3 and rect.height() > 3:
                self._selection_rect = rect
                self._selection_page = page
                text = self.selected_text()
                if text:
                    self.status.emit(f"{len(text)} karakter seçildi (Ctrl+C ile kopyalayın)")

    # -- seçim / kopyalama ---------------------------------------------
    def selected_text(self) -> str:
        rect = self._selection_rect
        if rect is None or not self.controller.is_open:
            return ""
        page = getattr(self, "_selection_page", self._current)
        words = self.controller.document.words(page)
        picked = []
        for x0, y0, x1, y1, word in words:
            wr = QRectF(x0, y0, x1 - x0, y1 - y0)
            inter = wr.intersected(rect)
            if inter.width() * inter.height() >= 0.35 * max(wr.width() * wr.height(), 1e-6):
                picked.append((round(y0, 1), x0, word))
        picked.sort()
        lines: dict[float, list[str]] = {}
        for y, _x, word in picked:
            lines.setdefault(y, []).append(word)
        return "\n".join(" ".join(v) for _, v in sorted(lines.items()))

    def copy_selection(self) -> bool:
        from PySide6.QtWidgets import QApplication

        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)
            self.status.emit("Seçili metin panoya kopyalandı.")
            return True
        return False

    def clear_selection(self) -> None:
        self._selection_rect = None
        self.viewport().update()

    # -- önizleme çizimi -----------------------------------------------
    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # kalıcı seçim
        if self._selection_rect is not None:
            page = getattr(self, "_selection_page", None)
            if page is not None and 0 <= page < len(self._items):
                item = self._items[page]
                painter.setPen(QPen(QColor(theme.current().accent), 1, Qt.DashLine))
                painter.setBrush(QColor(theme.current().selection))
                painter.drawRect(self._scene_rect_for(item, self._selection_rect))

        if not (self._dragging and self._drag_page is not None):
            return

        item = self._drag_page
        tool = self.tools.tool
        color = QColor(self.tools.preview_color())
        z = self._zoom
        pen = QPen(color, max(1.0, self.tools.defaults.width * z))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)

        if tool is Tool.PENCIL:
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            for stroke in self._strokes:
                if len(stroke) < 2:
                    continue
                path = QPainterPath(item.pos() + stroke[0] * z)
                for p in stroke[1:]:
                    path.lineTo(item.pos() + p * z)
                painter.drawPath(path)
            return

        scene_rect = self._scene_rect_for(item, self._drag_rect_pt())

        if tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT):
            fill = QColor(color)
            fill.setAlpha(70)
            painter.setPen(QPen(color, 1, Qt.DashLine))
            painter.setBrush(fill)
            painter.drawRect(scene_rect)
        elif tool is Tool.ERASER:
            painter.setPen(QPen(QColor(theme.current().danger), 1.4, Qt.DashLine))
            painter.setBrush(QColor(239, 83, 80, 40))
            painter.drawRect(scene_rect)
        elif tool is Tool.RECT:
            painter.setPen(pen)
            painter.setBrush(self._preview_fill())
            painter.drawRect(scene_rect)
        elif tool is Tool.ELLIPSE:
            painter.setPen(pen)
            painter.setBrush(self._preview_fill())
            painter.drawEllipse(scene_rect)
        elif tool in LINE_TOOLS:
            a = item.pos() + self._drag_start * z
            b = item.pos() + self._drag_current * z
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(a, b)
            if tool is Tool.ARROW:
                self._draw_arrow_head(painter, a, b, color, z)
        elif tool in (Tool.TEXT, Tool.IMAGE, Tool.SIGNATURE):
            painter.setPen(QPen(QColor(theme.current().accent), 1.4, Qt.DashLine))
            painter.setBrush(QColor(theme.current().selection))
            painter.drawRect(scene_rect)
        elif tool is Tool.SELECT:
            # canlı seçim kutusu: mavi kesikli çerçeve + yarı saydam dolgu
            painter.setPen(QPen(QColor(theme.current().accent), 1.2, Qt.DashLine))
            painter.setBrush(QColor(theme.current().selection))
            painter.drawRect(scene_rect)

    def _preview_fill(self) -> QBrush:
        fill = self.tools.defaults.fill
        if fill is None:
            return QBrush(Qt.NoBrush)
        c = QColor(fill)
        c.setAlphaF(self.tools.defaults.opacity)
        return QBrush(c)

    def _scene_rect_for(self, item: PageItem, rect_pt: QRectF) -> QRectF:
        z = self._zoom
        return QRectF(
            item.pos().x() + rect_pt.left() * z,
            item.pos().y() + rect_pt.top() * z,
            rect_pt.width() * z,
            rect_pt.height() * z,
        )

    @staticmethod
    def _draw_arrow_head(painter: QPainter, a: QPointF, b: QPointF, color: QColor, zoom: float) -> None:
        import math

        dx, dy = b.x() - a.x(), b.y() - a.y()
        length = math.hypot(dx, dy)
        if length < 1:
            return
        size = max(8.0, 5.0 * zoom)
        angle = math.atan2(dy, dx)
        p1 = QPointF(b.x() - size * math.cos(angle - math.pi / 7),
                     b.y() - size * math.sin(angle - math.pi / 7))
        p2 = QPointF(b.x() - size * math.cos(angle + math.pi / 7),
                     b.y() - size * math.sin(angle + math.pi / 7))
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygonF([b, p1, p2]))

    # -- bağlam menüsü -------------------------------------------------
    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self.controller.is_open:
            return
        from . import icons

        scene_pos = self.mapToScene(event.pos())
        item = self._item_at_scene(scene_pos)
        page = item.index if item else self._current

        menu = QMenu(self)
        act_copy = menu.addAction(icons.icon("copy"), "Seçili metni kopyala")
        act_copy.setEnabled(bool(self._selection_rect))
        menu.addSeparator()
        act_cw = menu.addAction(icons.icon("rotate_cw"), "Sayfayı sağa döndür")
        act_ccw = menu.addAction(icons.icon("rotate_ccw"), "Sayfayı sola döndür")
        menu.addSeparator()
        act_clear = menu.addAction(icons.icon("eraser"), "Sayfadaki açıklamaları temizle")
        act_del = menu.addAction(icons.icon("page_delete"), "Sayfayı sil")

        chosen = menu.exec(event.globalPos())
        if chosen is act_copy:
            self.copy_selection()
        elif chosen is act_cw:
            self.controller.rotate([page], 90)
        elif chosen is act_ccw:
            self.controller.rotate([page], -90)
        elif chosen is act_clear:
            if self.controller.clear_annotations(page) == 0:
                self.status.emit("Bu sayfada açıklama yok.")
        elif chosen is act_del:
            self.controller.delete_pages([page])
