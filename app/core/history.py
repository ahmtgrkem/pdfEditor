"""Anlık görüntü tabanlı geri al / yinele yığını.

PDF düzenleme işlemleri (annotation ekleme, sayfa silme, sıralama...) çok
farklı biçimlerde belgeyi değiştirir. Her işlem için ayrı bir ters işlem
yazmak yerine, işlem öncesi belge baytları saklanır. Basit, hatasız ve
tipik belge boyutlarında yeterince hızlıdır.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LIMIT = 40
DEFAULT_MEMORY_BUDGET = 512 * 1024 * 1024  # 512 MB


@dataclass
class Snapshot:
    label: str
    data: bytes
    page_index: int = 0
    was_dirty: bool = False

    @property
    def size(self) -> int:
        return len(self.data)


class HistoryStack:
    def __init__(self, limit: int = DEFAULT_LIMIT, budget: int = DEFAULT_MEMORY_BUDGET) -> None:
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        self._limit = limit
        self._budget = budget

    # -- durum ---------------------------------------------------------
    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    @property
    def redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    @property
    def memory_usage(self) -> int:
        return sum(s.size for s in self._undo) + sum(s.size for s in self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    # -- işlemler ------------------------------------------------------
    def push(self, snapshot: Snapshot) -> None:
        """Bir değişiklik *öncesi* durumu kaydeder."""
        self._undo.append(snapshot)
        self._redo.clear()
        self._trim()

    def undo(self, current: Snapshot) -> Snapshot | None:
        if not self._undo:
            return None
        state = self._undo.pop()
        self._redo.append(
            Snapshot(
                label=state.label,
                data=current.data,
                page_index=current.page_index,
                was_dirty=current.was_dirty,
            )
        )
        return state

    def redo(self, current: Snapshot) -> Snapshot | None:
        if not self._redo:
            return None
        state = self._redo.pop()
        self._undo.append(
            Snapshot(
                label=state.label,
                data=current.data,
                page_index=current.page_index,
                was_dirty=current.was_dirty,
            )
        )
        return state

    def discard_last(self) -> Snapshot | None:
        """Sonuçsuz kalan bir işlemin anlık görüntüsünü geri yığından çıkarır."""
        if not self._undo:
            return None
        return self._undo.pop()

    def discard_redo(self) -> None:
        self._redo.clear()

    # -- iç ------------------------------------------------------------
    def _trim(self) -> None:
        while len(self._undo) > self._limit:
            self._undo.pop(0)
        while self._undo and self.memory_usage > self._budget and len(self._undo) > 1:
            self._undo.pop(0)
