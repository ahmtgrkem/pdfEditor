"""Sayfa üzerinde form alanı düzenleme bileşenleri.

Görüntüleyici sayfaları bitmap olarak çizdiği için PDF widget'ları kendi
başlarına tıklanabilir değildir. Buradaki bileşenler, tıklanan alanın tam
üzerine yerleştirilen geçici Qt düzenleyicileridir; kullanıcı onaylayınca
değer PDF'e yazılır ve sayfa yeniden çizilir.

Onay kutuları ve radyo düğmeleri düzenleyici gerektirmez — tek tıkla
çevrilirler (bkz. :func:`app.core.form_fields.toggle`).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget

from ..core.form_fields import FormField


class FormTextEditor(QLineEdit):
    """Metin alanı için sayfa üzerine yerleştirilen düzenleyici."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, field: FormField, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self.setText(field.value)
        self.selectAll()
        if field.max_len > 0:
            self.setMaxLength(field.max_len)
        self.setStyleSheet(
            "QLineEdit {"
            " background: #ffffff;"
            " border: 1px solid #3b82f6;"
            " border-radius: 2px;"
            " padding: 0 3px;"
            " color: #111827;"
            "}"
        )
        self.returnPressed.connect(self._commit)
        self._committed = False

    def _commit(self) -> None:
        if self._committed:
            return
        self._committed = True
        self.committed.emit(self.text())

    def cancel(self) -> None:
        """Bundan sonra hiçbir olay değer yazmasın.

        ``hide()`` odak kaybı üretir ve odak kaybı onaylama sayıldığı için,
        kapatma öncesi bu işaretlenmezse iptal edilen değer yine yazılır.
        """
        self._committed = True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        # Başka bir yere tıklamak da onaylar; kullanıcı her alan için
        # Enter'a basmak zorunda kalmamalı.
        super().focusOutEvent(event)
        self._commit()


class FormChoiceEditor(QComboBox):
    """Açılır liste alanı için düzenleyici."""

    committed = Signal(str)
    cancelled = Signal()

    def __init__(self, field: FormField, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self.addItem("")                    # boş = seçim yapılmadı
        for secenek in field.options:
            self.addItem(secenek)
        if field.value:
            indeks = self.findText(field.value)
            if indeks >= 0:
                self.setCurrentIndex(indeks)
        self.setStyleSheet(
            "QComboBox {"
            " background: #ffffff;"
            " border: 1.5px solid #3b82f6;"
            " border-radius: 3px;"
            " padding: 1px 22px 1px 4px;"
            " color: #111827;"
            "}"
            "QComboBox::drop-down {"
            " subcontrol-origin: padding;"
            " subcontrol-position: top right;"
            " width: 18px;"
            " border-left: none;"
            " background: transparent;"
            "}"
            "QComboBox::down-arrow {"
            " image: url('data:image/svg+xml;utf8,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"%23111827\" stroke-width=\"2.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M6 9l6 6 6-6\"/></svg>');"
            " width: 10px;"
            " height: 10px;"
            "}"
        )
        self._committed = False
        self.activated.connect(self._commit)

    def _commit(self, *_args) -> None:
        if self._committed:
            return
        self._committed = True
        self.committed.emit(self.currentText())

    def cancel(self) -> None:
        """Bundan sonra hiçbir olay değer yazmasın (bkz. FormTextEditor)."""
        self._committed = True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancel()
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        # Açılır liste görünürken odak kaybı normaldir; onu onay saymayız.
        if not self.view().isVisible():
            self._commit()
