"""Belge içi metin arama paneli (arka planda çalışan tarama ile)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...services.document_controller import DocumentController
from .. import icons, theme

HIT_ROLE = Qt.UserRole + 1


@dataclass(frozen=True)
class Hit:
    page: int
    rect: tuple[float, float, float, float]
    context: str


class _WorkerSignals(QObject):
    pageHits = Signal(int, list)   # sayfa, [Hit]
    finished = Signal(int, int)    # toplam eşleşme, taranan sayfa
    token = Signal(int)


class _SearchTask(QRunnable):
    def __init__(self, controller: DocumentController, needle: str,
                 case_sensitive: bool, token: int, signals: _WorkerSignals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.controller = controller
        self.needle = needle
        self.case_sensitive = case_sensitive
        self.token = token
        self.signals = signals
        self.cancelled = False

    def run(self) -> None:  # noqa: D102
        doc = self.controller.document
        total = 0
        scanned = 0
        try:
            count = doc.page_count
            for index in range(count):
                if self.cancelled or not doc.is_open:
                    break
                try:
                    rects = doc.search_page(index, self.needle)
                except Exception:  # noqa: BLE001
                    rects = []
                hits: list[Hit] = []
                if rects:
                    with doc.lock:
                        page = doc.raw.load_page(index)
                        for r in rects:
                            context = self._context(page, r)
                            if self.case_sensitive and self.needle not in context:
                                continue
                            hits.append(Hit(index, r, context.strip()))
                scanned += 1
                if hits:
                    total += len(hits)
                    if not self.cancelled:
                        self.signals.pageHits.emit(index, hits)
        finally:
            if not self.cancelled:
                self.signals.finished.emit(total, scanned)

    def _context(self, page, rect) -> str:
        from ...core.pdf_backend import Rect

        box = Rect(rect)
        wide = Rect(max(0, box.x0 - 130), box.y0 - 2, box.x1 + 130, box.y1 + 2)
        try:
            text = page.get_textbox(wide)
        except Exception:  # noqa: BLE001
            text = ""
        return " ".join(text.split())


class SearchPanel(QWidget):
    """Arama girişi, sonuç listesi ve sonuçlar arası gezinme."""

    # Not: Signal(dict) C++ tarafında QVariantMap'e karşılık gelir ve yalnızca
    # metin anahtar kabul eder; sayfa numarası anahtarlı sözlük için object gerekir.
    resultsChanged = Signal(object)        # {sayfa: [rect]}
    activeHitChanged = Signal(int, object)  # sayfa, rect | None
    status = Signal(str)

    def __init__(self, controller: DocumentController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._hits: list[Hit] = []
        self._token = 0
        self._task: _SearchTask | None = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _WorkerSignals()
        self._signals.pageHits.connect(self._on_page_hits)
        self._signals.finished.connect(self._on_finished)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Belgede ara…")
        self.input.setClearButtonEnabled(True)

        self.btn_prev = QToolButton(self)
        self.btn_prev.setIcon(icons.icon("prev", size=18))
        self.btn_prev.setToolTip("Önceki sonuç (Shift+F3)")
        self.btn_next = QToolButton(self)
        self.btn_next.setIcon(icons.icon("next", size=18))
        self.btn_next.setToolTip("Sonraki sonuç (F3)")

        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.input, 1)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_next)

        self.case_box = QCheckBox("Büyük/küçük harf duyarlı", self)
        self.count_label = QLabel("", self)
        self.count_label.setStyleSheet(f"color: {theme.current().text_muted};")

        options = QHBoxLayout()
        options.addWidget(self.case_box)
        options.addStretch(1)
        options.addWidget(self.count_label)

        self.results = QListWidget(self)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(7)
        layout.addLayout(top)
        layout.addLayout(options)
        layout.addWidget(self.results, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(280)
        self._debounce.timeout.connect(self.start_search)

        self.input.textChanged.connect(lambda _: self._debounce.start())
        self.input.returnPressed.connect(self.next_hit)
        self.case_box.toggled.connect(lambda _: self.start_search())
        self.results.itemActivated.connect(self._on_item)
        self.results.itemClicked.connect(self._on_item)
        self.btn_next.clicked.connect(self.next_hit)
        self.btn_prev.clicked.connect(self.prev_hit)

        controller.documentReplaced.connect(self._on_document_changed)
        controller.documentOpened.connect(lambda _: self._on_document_changed())
        controller.documentClosed.connect(self.clear)

    # ------------------------------------------------------------------
    def focus_input(self) -> None:
        self.input.setFocus()
        self.input.selectAll()

    def _on_document_changed(self) -> None:
        if self.input.text().strip():
            self.start_search()
        else:
            self.clear()

    def clear(self) -> None:
        self._cancel()
        self._hits.clear()
        self.results.clear()
        self.count_label.setText("")
        self.resultsChanged.emit({})
        self.activeHitChanged.emit(-1, None)

    def _cancel(self) -> None:
        if self._task is not None:
            self._task.cancelled = True
            self._task = None

    # ------------------------------------------------------------------
    def start_search(self) -> None:
        self._cancel()
        needle = self.input.text().strip()
        self._hits.clear()
        self.results.clear()
        self.resultsChanged.emit({})
        self.activeHitChanged.emit(-1, None)

        if not needle or not self.controller.is_open:
            self.count_label.setText("")
            return

        self._token += 1
        self.count_label.setText("aranıyor…")
        self._task = _SearchTask(
            self.controller, needle, self.case_box.isChecked(), self._token, self._signals
        )
        self._pool.start(self._task)

    def _on_page_hits(self, page: int, hits: list) -> None:
        if self._task is None or self._task.cancelled:
            return
        for hit in hits:
            self._hits.append(hit)
            label = f"Sayfa {hit.page + 1}"
            item = QListWidgetItem(f"{label}  ·  {hit.context[:110]}")
            item.setData(HIT_ROLE, len(self._hits) - 1)
            item.setToolTip(hit.context)
            self.results.addItem(item)
        self._emit_results()
        self.count_label.setText(f"{len(self._hits)} sonuç")

    def _on_finished(self, total: int, _scanned: int) -> None:
        self._task = None
        if total == 0:
            self.count_label.setText("sonuç yok")
            self.status.emit("Arama sonucu bulunamadı.")
        else:
            self.count_label.setText(f"{total} sonuç")
            if self.results.currentRow() < 0 and self._hits:
                self.results.setCurrentRow(0)
                self._activate(0)

    def _emit_results(self) -> None:
        grouped: dict[int, list[tuple[float, float, float, float]]] = {}
        for hit in self._hits:
            grouped.setdefault(hit.page, []).append(hit.rect)
        self.resultsChanged.emit(grouped)

    # ------------------------------------------------------------------
    def _on_item(self, item: QListWidgetItem) -> None:
        index = item.data(HIT_ROLE)
        if index is not None:
            self._activate(int(index))

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._hits)):
            return
        hit = self._hits[index]
        self.results.blockSignals(True)
        self.results.setCurrentRow(index)
        self.results.blockSignals(False)
        self.activeHitChanged.emit(hit.page, hit.rect)
        self.count_label.setText(f"{index + 1} / {len(self._hits)}")

    def next_hit(self) -> None:
        if not self._hits:
            self.start_search()
            return
        self._activate((self.results.currentRow() + 1) % len(self._hits))

    def prev_hit(self) -> None:
        if not self._hits:
            return
        self._activate((self.results.currentRow() - 1) % len(self._hits))
