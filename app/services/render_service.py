"""Arka planda sayfa render'lama ve LRU önbellek.

MuPDF belge nesneleri thread-safe olmadığından tüm render'lar
:class:`PdfDocument` içindeki kilit üzerinden serileştirilir; buna rağmen
render iş parçacığında yapıldığı için arayüz akıcı kalır.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage

from ..core.document import PdfDocument

# Yaklaşık 320 MB piksel önbelleği
CACHE_BUDGET_BYTES = 320 * 1024 * 1024


def _to_qimage(rendered) -> QImage:
    img = QImage(
        rendered.samples,
        rendered.width,
        rendered.height,
        rendered.stride,
        QImage.Format_RGB888,
    )
    return img.copy()  # MuPDF tamponundan bağımsız derin kopya


@dataclass(frozen=True)
class CacheKey:
    kind: str
    index: int
    zoom_key: int
    generation: int


class _ImageCache:
    def __init__(self, budget: int = CACHE_BUDGET_BYTES) -> None:
        self._data: OrderedDict[CacheKey, QImage] = OrderedDict()
        self._budget = budget
        self._bytes = 0

    def get(self, key: CacheKey) -> QImage | None:
        img = self._data.get(key)
        if img is not None:
            self._data.move_to_end(key)
        return img

    def put(self, key: CacheKey, image: QImage) -> None:
        if key in self._data:
            self._bytes -= self._data[key].sizeInBytes()
            del self._data[key]
        self._data[key] = image
        self._bytes += image.sizeInBytes()
        while self._bytes > self._budget and len(self._data) > 1:
            _, victim = self._data.popitem(last=False)
            self._bytes -= victim.sizeInBytes()

    def clear(self) -> None:
        self._data.clear()
        self._bytes = 0


class _Signals(QObject):
    finished = Signal(object, QImage)  # CacheKey, QImage
    failed = Signal(object, str)


class _RenderTask(QRunnable):
    def __init__(self, doc: PdfDocument, key: CacheKey, zoom: float, signals: _Signals) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._doc = doc
        self._key = key
        self._zoom = zoom
        self._signals = signals
        self.cancelled = False

    def run(self) -> None:  # noqa: D102
        if self.cancelled:
            return
        try:
            if not self._doc.is_open or self._doc.generation != self._key.generation:
                return
            rendered = self._doc.render(self._key.index, self._zoom)
            if self.cancelled:
                return
            self._signals.finished.emit(self._key, _to_qimage(rendered))
        except Exception as exc:  # noqa: BLE001 - render hatası UI'ı düşürmemeli
            if not self.cancelled:
                self._signals.failed.emit(self._key, str(exc))


class RenderService(QObject):
    """Sayfa ve küçük resim render isteklerini yönetir."""

    pageReady = Signal(int, float, QImage)      # index, zoom, image
    thumbnailReady = Signal(int, QImage)        # index, image
    renderFailed = Signal(int, str)

    def __init__(self, document: PdfDocument, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._doc = document
        self._cache = _ImageCache()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(2, min(4, QThreadPool.globalInstance().maxThreadCount())))
        self._pending: dict[CacheKey, _RenderTask] = {}
        self._signals = _Signals()
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)

    # ------------------------------------------------------------------
    @staticmethod
    def _zoom_key(zoom: float) -> int:
        return int(round(zoom * 1000))

    # ------------------------------------------------------------------
    def request_page(self, index: int, zoom: float) -> QImage | None:
        """Önbellekte varsa görüntüyü döndürür, yoksa arka planda üretir."""
        if not self._doc.is_open:
            return None
        key = CacheKey("page", index, self._zoom_key(zoom), self._doc.generation)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._enqueue(key, zoom)
        return None

    def request_thumbnail(self, index: int, width: int = 160) -> QImage | None:
        if not self._doc.is_open:
            return None
        key = CacheKey("thumb", index, width, self._doc.generation)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            page_w, _ = self._doc.page_size(index)
        except Exception:  # noqa: BLE001
            return None
        zoom = max(0.05, width / max(page_w, 1.0))
        self._enqueue(key, zoom)
        return None

    def _enqueue(self, key: CacheKey, zoom: float) -> None:
        if key in self._pending:
            return
        task = _RenderTask(self._doc, key, zoom, self._signals)
        self._pending[key] = task
        self._pool.start(task)

    # ------------------------------------------------------------------
    def cancel_all(self) -> None:
        for task in self._pending.values():
            task.cancelled = True
        self._pending.clear()
        self._pool.clear()

    def invalidate(self) -> None:
        """Belge değiştiğinde eski render'ları at."""
        self.cancel_all()
        self._cache.clear()

    def clear(self) -> None:
        self.cancel_all()
        self._cache.clear()

    def shutdown(self) -> None:
        self.cancel_all()
        self._pool.waitForDone(3000)
        self._cache.clear()

    # ------------------------------------------------------------------
    def _on_finished(self, key: CacheKey, image: QImage) -> None:
        self._pending.pop(key, None)
        if key.generation != self._doc.generation:
            return
        self._cache.put(key, image)
        if key.kind == "page":
            self.pageReady.emit(key.index, key.zoom_key / 1000.0, image)
        else:
            self.thumbnailReady.emit(key.index, image)

    def _on_failed(self, key: CacheKey, message: str) -> None:
        self._pending.pop(key, None)
        self.renderFailed.emit(key.index, message)
