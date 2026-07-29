"""Küçük resim paneli: önizleme, sürükle-bırak sıralama ve sayfa işlemleri."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ...services.document_controller import DocumentController
from .. import icons, theme

THUMB_WIDTH = 132
INDEX_ROLE = Qt.UserRole + 1


class ThumbnailList(QListWidget):
    """Sürükle-bırak sıralamayı destekleyen liste."""

    orderChanged = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)
        self.setSpacing(6)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setIconSize(QSize(THUMB_WIDTH, int(THUMB_WIDTH * 1.5)))
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideRight)

    def dropEvent(self, event) -> None:  # noqa: N802
        before = [self.item(i).data(INDEX_ROLE) for i in range(self.count())]
        super().dropEvent(event)
        after = [self.item(i).data(INDEX_ROLE) for i in range(self.count())]
        if after != before and None not in after:
            self.orderChanged.emit(after)


class ThumbnailPanel(QWidget):
    """Sayfa önizlemeleri ve sayfa yönetimi."""

    pageActivated = Signal(int)
    status = Signal(str)

    def __init__(self, controller: DocumentController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._syncing = False

        self.list = ThumbnailList(self)
        self.list.setObjectName("thumbList")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.list)
        self.refresh_theme()

        self.list.itemSelectionChanged.connect(self._on_selection)
        self.list.itemClicked.connect(self._on_clicked)
        self.list.orderChanged.connect(self._on_order_changed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_menu)

        controller.renderer.thumbnailReady.connect(self._on_thumb_ready)
        controller.documentReplaced.connect(self.rebuild)
        controller.documentOpened.connect(lambda _: self.rebuild())
        controller.documentClosed.connect(self.rebuild)
        controller.pageContentChanged.connect(self._refresh_page)

    # ------------------------------------------------------------------
    def refresh_theme(self) -> None:
        """Seçili sayfa, önizlemenin üstünü kapatmadan çerçeveyle vurgulanır."""
        p = theme.current()
        self.list.setStyleSheet(
            f"QListWidget#thumbList {{ background: {p.window}; border: none; }}"
            f"QListWidget#thumbList::item {{ color: {p.text_muted};"
            f" border: 2px solid transparent; border-radius: 7px; padding: 4px; }}"
            f"QListWidget#thumbList::item:hover {{ border-color: {p.border}; }}"
            f"QListWidget#thumbList::item:selected {{ background: transparent;"
            f" color: {p.accent}; border-color: {p.accent}; }}"
        )

    def rebuild(self) -> None:
        self.list.clear()
        if not self.controller.is_open:
            return
        placeholder = self._placeholder()
        for i in range(self.controller.page_count):
            item = QListWidgetItem(QIcon(placeholder), str(i + 1))
            item.setData(INDEX_ROLE, i)
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSizeHint(QSize(THUMB_WIDTH + 18, int(THUMB_WIDTH * 1.5) + 30))
            self.list.addItem(item)
        self._request_visible()
        self.set_current(self.controller.current_page)

    def _thumb_px(self) -> int:
        """Ekran ölçeklemesine göre istenecek gerçek piksel genişliği."""
        return max(64, int(round(THUMB_WIDTH * self.devicePixelRatioF())))

    def _placeholder(self) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pm = QPixmap(int(THUMB_WIDTH * ratio), int(THUMB_WIDTH * 1.414 * ratio))
        pm.setDevicePixelRatio(ratio)
        pm.fill(QColor("#ffffff"))
        painter = QPainter(pm)
        painter.setPen(QColor(theme.current().border))
        painter.drawRect(0, 0, THUMB_WIDTH - 1, int(THUMB_WIDTH * 1.414) - 1)
        painter.end()
        return pm

    def _request_visible(self) -> None:
        width = self._thumb_px()
        for i in range(self.list.count()):
            image = self.controller.renderer.request_thumbnail(i, width)
            if image is not None:
                self._apply_thumb(i, image)

    def _on_thumb_ready(self, index: int, image: QImage) -> None:
        self._apply_thumb(index, image)

    def _apply_thumb(self, index: int, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(INDEX_ROLE) == index:
                item.setIcon(QIcon(pixmap))
                return

    def _refresh_page(self, index: int) -> None:
        image = self.controller.renderer.request_thumbnail(index, self._thumb_px())
        if image is not None:
            self._apply_thumb(index, image)

    # ------------------------------------------------------------------
    def set_current(self, index: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            for i in range(self.list.count()):
                item = self.list.item(i)
                if item.data(INDEX_ROLE) == index:
                    self.list.setCurrentItem(item)
                    self.list.scrollToItem(item, QAbstractItemView.EnsureVisible)
                    break
        finally:
            self._syncing = False

    def selected_pages(self) -> list[int]:
        return sorted(item.data(INDEX_ROLE) for item in self.list.selectedItems())

    def _on_selection(self) -> None:
        if self._syncing:
            return
        pages = self.selected_pages()
        if len(pages) == 1:
            self.pageActivated.emit(pages[0])

    def _on_clicked(self, item: QListWidgetItem) -> None:
        if not self._syncing:
            self.pageActivated.emit(item.data(INDEX_ROLE))

    def _on_order_changed(self, order: list) -> None:
        try:
            self.controller.reorder_pages([int(i) for i in order])
            self.status.emit("Sayfa sırası güncellendi.")
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"Sıralama başarısız: {exc}")
            self.rebuild()

    # ------------------------------------------------------------------
    def _show_menu(self, pos) -> None:
        if not self.controller.is_open:
            return
        pages = self.selected_pages()
        item = self.list.itemAt(pos)
        if item is not None and item.data(INDEX_ROLE) not in pages:
            pages = [item.data(INDEX_ROLE)]
            self.list.setCurrentItem(item)
        if not pages:
            return

        menu = QMenu(self)
        act_cw = menu.addAction(icons.icon("rotate_cw"), "Sağa döndür (90°)")
        act_ccw = menu.addAction(icons.icon("rotate_ccw"), "Sola döndür (90°)")
        menu.addSeparator()
        act_blank = menu.addAction(icons.icon("page_add"), "Önüne boş sayfa ekle")
        act_dup = menu.addAction(icons.icon("page_duplicate"), "Sayfaları çoğalt")
        act_extract = menu.addAction(icons.icon("page_extract"), "Seçili sayfaları dışa aktar…")
        menu.addSeparator()
        act_del = menu.addAction(icons.icon("page_delete"), f"{len(pages)} sayfayı sil")

        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is act_cw:
            self.controller.rotate(pages, 90)
        elif chosen is act_ccw:
            self.controller.rotate(pages, -90)
        elif chosen is act_blank:
            self.controller.insert_blank(pages[0])
        elif chosen is act_dup:
            self.controller.duplicate_pages(pages)
        elif chosen is act_extract:
            self.parent_window_extract(pages)
        elif chosen is act_del:
            try:
                self.controller.delete_pages(pages)
            except Exception as exc:  # noqa: BLE001
                self.status.emit(str(exc))

    def parent_window_extract(self, pages: list[int]) -> None:
        """Ana pencereye dışa aktarma isteği iletir."""
        window = self.window()
        handler = getattr(window, "extract_pages", None)
        if callable(handler):
            handler(pages)
