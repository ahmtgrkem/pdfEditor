"""Belge denetleyicisi — çekirdek katman ile arayüz arasındaki tek köprü.

Arayüz bileşenleri PyMuPDF'e doğrudan dokunmaz; her düzenleme buradan geçer.
Böylece geri al/yinele, kirli-durum takibi ve önbellek geçersizleme tek
noktada toplanır.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Sequence

from PySide6.QtCore import QObject, Signal

from ..core import annotations as ann
from ..core import page_ops
from ..core.document import PasswordRequired, PdfDocument, PdfError
from ..core.history import HistoryStack, Snapshot
from .render_service import RenderService


class DocumentController(QObject):
    """Açık belgeyi ve üzerindeki tüm işlemleri yönetir."""

    documentOpened = Signal(str)
    documentClosed = Signal()
    documentReplaced = Signal()          # yapı değişti: her şeyi yeniden kur
    pageContentChanged = Signal(int)     # tek sayfanın içeriği değişti
    dirtyChanged = Signal(bool)
    historyChanged = Signal()
    message = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.document = PdfDocument()
        self.history = HistoryStack()
        self.renderer = RenderService(self.document, self)
        self._current_page = 0

    # ------------------------------------------------------------------
    # Durum
    # ------------------------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self.document.is_open

    @property
    def page_count(self) -> int:
        return self.document.page_count

    @property
    def path(self) -> str | None:
        return self.document.path

    @property
    def is_dirty(self) -> bool:
        return self.document.is_dirty

    @property
    def current_page(self) -> int:
        return self._current_page

    def set_current_page(self, index: int) -> None:
        self._current_page = max(0, min(index, max(0, self.page_count - 1)))

    def title(self) -> str:
        name = self.document.display_name if self.is_open else "Belge yok"
        return f"{'*' if self.is_dirty else ''}{name}"

    # ------------------------------------------------------------------
    # Açma / kapatma / kaydetme
    # ------------------------------------------------------------------
    def open(self, path: str, password: str | None = None) -> None:
        self.renderer.clear()
        self.document.open(path, password)
        self.history.clear()
        self._current_page = 0
        self.documentOpened.emit(path)
        self.dirtyChanged.emit(False)
        self.historyChanged.emit()

    def open_bytes(self, data: bytes, title: str = "") -> None:
        """Bellekteki PDF baytlarını **adsız** belge olarak açar.

        Yol atanmaz: bu belge diskteki bir dosyanın karşılığı değildir
        (ör. XFA formundan üretilen görüntülenebilir sürüm). Böylece
        "Kaydet" doğrudan üzerine yazmak yerine "Farklı Kaydet" sorar ve
        kullanıcının özgün dosyası korunur.
        """
        self.renderer.clear()
        self.document.open_stream(data, detach=True)
        self.document.mark_dirty(structural=True)
        self.history.clear()
        self._current_page = 0
        self.documentOpened.emit("")
        self.dirtyChanged.emit(True)
        self.historyChanged.emit()

    def create_empty(self) -> None:
        self.renderer.clear()
        self.document.new_empty()
        self.history.clear()
        self._current_page = 0
        self.documentOpened.emit("")
        self.dirtyChanged.emit(True)
        self.historyChanged.emit()

    def close(self) -> None:
        self.renderer.clear()
        self.document.close()
        self.history.clear()
        self._current_page = 0
        self.documentClosed.emit()
        self.dirtyChanged.emit(False)
        self.historyChanged.emit()

    def save(self, path: str | None = None) -> str:
        target = self.document.save(path)
        self.dirtyChanged.emit(False)
        self.message.emit(f"Kaydedildi: {os.path.basename(target)}")
        return target

    # ------------------------------------------------------------------
    # Düzenleme oturumu (geri alınabilir)
    # ------------------------------------------------------------------
    @contextmanager
    def edit(self, label: str, structural: bool = False, page: int | None = None) -> Iterator[PdfDocument]:
        """Geri alınabilir bir düzenleme bloğu.

        Blok hatasız biterse anlık görüntü yığına eklenir ve ilgili sinyaller
        yayınlanır; hata olursa yığın değişmez.
        """
        if not self.is_open:
            raise PdfError("Açık belge yok.")
        before = Snapshot(
            label=label,
            data=self.document.snapshot(),
            page_index=self._current_page,
            was_dirty=self.document.is_dirty,
        )
        yield self.document
        self.history.push(before)
        self.historyChanged.emit()
        self._notify_change(structural=structural, page=page)

    def _notify_change(self, structural: bool, page: int | None) -> None:
        if structural or page is None:
            self.renderer.invalidate()
            self.documentReplaced.emit()
        else:
            self.renderer.invalidate()
            self.pageContentChanged.emit(page)
        self.dirtyChanged.emit(self.document.is_dirty)

    # ------------------------------------------------------------------
    # Geri al / yinele
    # ------------------------------------------------------------------
    def can_undo(self) -> bool:
        return self.history.can_undo

    def can_redo(self) -> bool:
        return self.history.can_redo

    def _current_snapshot(self, label: str = "") -> Snapshot:
        return Snapshot(
            label=label,
            data=self.document.snapshot(),
            page_index=self._current_page,
            was_dirty=self.document.is_dirty,
        )

    def undo(self) -> bool:
        if not (self.is_open and self.history.can_undo):
            return False
        state = self.history.undo(self._current_snapshot())
        if state is None:
            return False
        self._restore(state)
        self.message.emit(f"Geri alındı: {state.label}")
        return True

    def redo(self) -> bool:
        if not (self.is_open and self.history.can_redo):
            return False
        state = self.history.redo(self._current_snapshot())
        if state is None:
            return False
        self._restore(state)
        self.message.emit(f"Yinelendi: {state.label}")
        return True

    def _restore(self, state: Snapshot) -> None:
        self.renderer.clear()
        self.document.open_stream(state.data)
        if state.was_dirty:
            self.document.mark_dirty(structural=True)
        else:
            self.document.mark_clean()
        self._current_page = min(state.page_index, max(0, self.page_count - 1))
        self.historyChanged.emit()
        self.documentReplaced.emit()
        self.dirtyChanged.emit(self.document.is_dirty)

    # ==================================================================
    # Yüksek seviyeli işlemler
    # ==================================================================
    # -- açıklamalar ---------------------------------------------------
    def add_markup(self, page: int, rect, kind: ann.MarkupKind, style: ann.PenStyle) -> bool:
        ok = False
        with self.edit(f"{kind.value} işaretleme", page=page):
            ok = ann.add_markup(self.document, page, rect, kind, style)
        if not ok:
            self.undo_silently()
            self.message.emit("Seçilen alanda metin bulunamadı.")
        return ok

    def add_ink(self, page: int, strokes, style: ann.PenStyle) -> bool:
        ok = False
        with self.edit("Serbest çizim", page=page):
            ok = ann.add_ink(self.document, page, strokes, style)
        if not ok:
            self.undo_silently()
        return ok

    def add_shape(self, page: int, kind: ann.ShapeKind, p1, p2, style: ann.PenStyle) -> bool:
        ok = False
        with self.edit(f"{kind.value} ekleme", page=page):
            ok = ann.add_shape(self.document, page, kind, p1, p2, style)
        if not ok:
            self.undo_silently()
        return ok

    def add_text(
        self,
        page: int,
        rect,
        text: str,
        style: ann.TextStyle,
        origin: tuple[float, float] | None = None,
        line_height: float | None = None,
    ) -> bool:
        ok = False
        with self.edit("Metin ekleme", page=page):
            ok = ann.add_text(
                self.document, page, rect, text, style,
                origin=origin, line_height=line_height,
            )
        if not ok:
            self.undo_silently()
            self.message.emit("Metin sayfaya sığmadı.")
        return ok

    def find_text_at_point(self, page: int, visual_point: tuple[float, float]) -> dict | None:
        if not self.is_open:
            return None
        return ann.find_text_at_point(self.document, page, visual_point)

    def replace_text(
        self,
        page: int,
        visual_rect: tuple[float, float, float, float],
        new_text: str,
        style: ann.TextStyle,
        origin: tuple[float, float] | None = None,
        line_height: float | None = None,
    ) -> bool:
        ok = False
        with self.edit("Metin düzenleme", page=page):
            ok = ann.replace_text(
                self.document, page, visual_rect, new_text, style,
                origin=origin, line_height=line_height,
            )
        if not ok:
            self.undo_silently()
            self.message.emit("Metin değiştirilemedi.")
        return ok

    def add_image(self, page: int, rect, data: bytes) -> bool:
        ok = False
        with self.edit("Görsel ekleme", page=page):
            ok = ann.add_image(self.document, page, rect, data)
        if not ok:
            self.undo_silently()
        return ok

    def add_watermark(self, opts: ann.WatermarkOptions) -> int:
        count = 0
        with self.edit("Filigran", structural=True):
            count = ann.add_watermark(self.document, opts)
        if not count:
            self.undo_silently()
        return count

    def erase_at(self, page: int, point) -> bool:
        ok = False
        with self.edit("Açıklama silme", page=page):
            ok = ann.delete_annot_at(self.document, page, point)
        if not ok:
            self.undo_silently()
        return ok

    def erase_in(self, page: int, rect) -> int:
        count = 0
        with self.edit("Açıklama silme", page=page):
            count = ann.delete_annots_in(self.document, page, rect)
        if not count:
            self.undo_silently()
        return count

    def clear_annotations(self, page: int) -> int:
        count = 0
        with self.edit("Açıklamaları temizle", page=page):
            count = ann.clear_page_annots(self.document, page)
        if not count:
            self.undo_silently()
        return count

    # -- sayfa işlemleri -----------------------------------------------
    def rotate(self, indices: Sequence[int], delta: int) -> int:
        count = 0
        with self.edit("Sayfa döndürme", structural=True):
            count = page_ops.rotate_pages(self.document, indices, delta)
        return count

    def delete_pages(self, indices: Sequence[int]) -> int:
        count = 0
        with self.edit("Sayfa silme", structural=True):
            count = page_ops.delete_pages(self.document, indices)
        return count

    def insert_blank(self, at: int) -> int:
        with self.edit("Boş sayfa ekleme", structural=True):
            at = page_ops.insert_blank_page(self.document, at)
        return at

    def duplicate_pages(self, indices: Sequence[int]) -> int:
        count = 0
        with self.edit("Sayfa çoğaltma", structural=True):
            count = page_ops.duplicate_pages(self.document, indices)
        return count

    def move_page(self, source: int, target: int) -> bool:
        ok = False
        with self.edit("Sayfa taşıma", structural=True):
            ok = page_ops.move_page(self.document, source, target)
        if not ok:
            self.undo_silently()
        return ok

    def reorder_pages(self, order: Sequence[int]) -> bool:
        ok = False
        with self.edit("Sayfa sıralama", structural=True):
            ok = page_ops.reorder_pages(self.document, order)
        if not ok:
            self.undo_silently()
        return ok

    def append_documents(self, sources: Sequence[tuple[str, str | None, str]]) -> int:
        """Mevcut belgenin sonuna başka PDF'ler ekler."""
        added = 0
        with self.edit("PDF birleştirme", structural=True):
            from ..core.pdf_backend import fitz

            with self.document.lock:
                for path, password, ranges in sources:
                    src = fitz.open(path)
                    try:
                        if src.needs_pass and not (password and src.authenticate(password)):
                            raise PdfError(f"Parola gerekiyor: {os.path.basename(path)}")
                        for i in page_ops.parse_page_ranges(ranges, src.page_count):
                            self.document.raw.insert_pdf(src, from_page=i, to_page=i)
                            added += 1
                    finally:
                        src.close()
            self.document.mark_dirty(structural=True)
        return added

    def set_toc(self, entries) -> None:
        with self.edit("İçindekiler güncelleme", structural=True):
            self.document.set_toc(entries)

    def set_metadata(self, meta: dict) -> None:
        with self.edit("Belge bilgileri", structural=True):
            self.document.set_metadata(meta)

    # ------------------------------------------------------------------
    def undo_silently(self) -> None:
        """Sonuçsuz kalan bir düzenlemeyi geri alır ve geçmişte iz bırakmaz."""
        state = self.history.discard_last()
        if state is None:
            return
        self.renderer.clear()
        self.document.open_stream(state.data)
        if state.was_dirty:
            self.document.mark_dirty(structural=True)
        else:
            self.document.mark_clean()
        self.history.discard_redo()
        self.historyChanged.emit()
        self.documentReplaced.emit()
        self.dirtyChanged.emit(self.document.is_dirty)

    def shutdown(self) -> None:
        self.renderer.shutdown()
        self.document.close()


__all__ = ["DocumentController", "PasswordRequired", "PdfError"]
