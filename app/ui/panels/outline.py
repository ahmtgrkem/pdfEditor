"""İçindekiler / yer işaretleri paneli."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.document import TocEntry
from ...services.document_controller import DocumentController

PAGE_ROLE = Qt.UserRole + 1


class OutlinePanel(QWidget):
    """PDF içindekiler ağacını gösterir ve gezinme sağlar."""

    pageActivated = Signal(int)

    def __init__(self, controller: DocumentController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_clicked)

        self.empty = QLabel("Bu belgede içindekiler bilgisi yok.", self)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: palette(placeholder-text); padding: 20px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.tree)
        layout.addWidget(self.empty)

        controller.documentReplaced.connect(self.rebuild)
        controller.documentOpened.connect(lambda _: self.rebuild())
        controller.documentClosed.connect(self.rebuild)
        self.rebuild()

    # ------------------------------------------------------------------
    def rebuild(self) -> None:
        self.tree.clear()
        entries: list[TocEntry] = []
        if self.controller.is_open:
            try:
                entries = self.controller.document.toc()
            except Exception:  # noqa: BLE001
                entries = []

        has_entries = bool(entries)
        self.tree.setVisible(has_entries)
        self.empty.setVisible(not has_entries)
        if not has_entries:
            return

        stack: list[tuple[int, QTreeWidgetItem]] = []
        for entry in entries:
            node = QTreeWidgetItem([entry.title.strip() or "(başlıksız)"])
            node.setData(0, PAGE_ROLE, max(0, entry.page - 1))
            node.setToolTip(0, f"{entry.title}  ·  sayfa {entry.page}")
            while stack and stack[-1][0] >= entry.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.tree.addTopLevelItem(node)
            stack.append((entry.level, node))

        self.tree.expandToDepth(1)

    def _on_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        page = item.data(0, PAGE_ROLE)
        if page is not None:
            self.pageActivated.emit(int(page))

    def sync_to_page(self, page: int) -> None:
        """Etkin sayfaya karşılık gelen başlığı vurgular."""
        best: QTreeWidgetItem | None = None
        best_page = -1

        def walk(node: QTreeWidgetItem) -> None:
            nonlocal best, best_page
            value = node.data(0, PAGE_ROLE)
            if value is not None and best_page <= int(value) <= page:
                best, best_page = node, int(value)
            for i in range(node.childCount()):
                walk(node.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

        if best is not None and best is not self.tree.currentItem():
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(best)
            self.tree.blockSignals(False)
