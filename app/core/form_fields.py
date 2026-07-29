"""Etkileşimli PDF form alanları (AcroForm widget'ları).

Görüntüleyici sayfaları düz görüntü olarak çizdiği için widget'lar
kendiliğinden tıklanabilir değildir. Bu modül alanları listeler ve
değerlerini yazar; arayüz katmanı (:mod:`app.ui.page_view`) tıklamayı
yakalayıp buradaki işlevleri çağırır.

Koordinatlar **sayfa puntosu** cinsindendir ve görünüm dönüşümüne
(:meth:`PdfDocument.to_pdf_rect`) uygun olarak döndürme uygulanmış hâlde
verilir; böylece döndürülmüş sayfalarda da alanlar doğru yerde bulunur.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .document import PdfDocument
from .pdf_backend import Rect, fitz

#: Kullanıcının değiştirebileceği alan türleri
EDITABLE_TYPES = frozenset({"text", "check", "radio", "combo", "list"})

_TYPE_NAMES = {
    fitz.PDF_WIDGET_TYPE_TEXT: "text",
    fitz.PDF_WIDGET_TYPE_CHECKBOX: "check",
    fitz.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    fitz.PDF_WIDGET_TYPE_COMBOBOX: "combo",
    fitz.PDF_WIDGET_TYPE_LISTBOX: "list",
    fitz.PDF_WIDGET_TYPE_BUTTON: "button",
    fitz.PDF_WIDGET_TYPE_SIGNATURE: "signature",
}


@dataclass
class FormField:
    """Sayfadaki tek bir form alanı."""

    page_index: int
    name: str
    type: str
    #: Görünüm (sayfa) koordinatlarında dikdörtgen — punto
    rect: tuple[float, float, float, float]
    value: str = ""
    options: list[str] = dataclass_field(default_factory=list)
    readonly: bool = False
    max_len: int = 0
    #: Aynı adı taşıyan radyo düğmeleri arasında bu düğmenin "açık" değeri
    on_state: str = ""

    @property
    def editable(self) -> bool:
        return not self.readonly and self.type in EDITABLE_TYPES

    @property
    def is_toggle(self) -> bool:
        return self.type in ("check", "radio")

    @property
    def checked(self) -> bool:
        return self.type in ("check", "radio") and self.value not in ("", "Off", "0")

    def contains(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 <= x <= x1 and y0 <= y <= y1


def _read_only(widget) -> bool:
    bayraklar = getattr(widget, "field_flags", 0) or 0
    return bool(bayraklar & 1)          # PDF: ReadOnly = 1. bit


def _widget_on_state(widget) -> str:
    """Onay kutusu/radyo için "açık" durumun adı (genelde ``Yes``)."""
    try:
        durumlar = widget.button_states() or {}
    except Exception:  # noqa: BLE001 - bağı kopmuş widget
        return "Yes"
    for anahtar in ("normal", "down"):
        for durum in durumlar.get(anahtar, []) or []:
            if durum != "Off":
                return durum
    return "Yes"


def list_fields(doc: PdfDocument, page_index: int) -> list[FormField]:
    """Sayfadaki form alanlarını görünüm koordinatlarıyla verir."""
    with doc.lock:
        if not doc.is_open or not (0 <= page_index < doc.raw.page_count):
            return []
        page = doc.raw.load_page(page_index)
        alanlar: list[FormField] = []
        for widget in page.widgets() or []:
            tur = _TYPE_NAMES.get(widget.field_type, "button")
            gorunum = doc.to_view_rect(page_index, Rect(widget.rect))
            deger = widget.field_value
            if isinstance(deger, bool):
                deger = "Yes" if deger else "Off"
            alanlar.append(
                FormField(
                    page_index=page_index,
                    name=widget.field_name or "",
                    type=tur,
                    rect=(gorunum.x0, gorunum.y0, gorunum.x1, gorunum.y1),
                    value="" if deger is None else str(deger),
                    options=list(widget.choice_values or []),
                    readonly=_read_only(widget),
                    max_len=int(getattr(widget, "text_maxlen", 0) or 0),
                    on_state=_widget_on_state(widget)
                    if tur in ("check", "radio") else "",
                )
            )
    return alanlar


def field_at(doc: PdfDocument, page_index: int, x: float, y: float) -> FormField | None:
    """Verilen noktadaki düzenlenebilir alan (yoksa ``None``).

    Üst üste binen alanlarda **en küçüğü** seçilir: onay kutuları çoğunlukla
    daha geniş bir metin alanının üzerinde durur ve büyük olan seçilirse
    kutuya tıklamak mümkün olmaz.
    """
    adaylar = [a for a in list_fields(doc, page_index)
               if a.editable and a.contains(x, y)]
    if not adaylar:
        return None
    return min(adaylar, key=lambda a: (a.rect[2] - a.rect[0]) * (a.rect[3] - a.rect[1]))


def set_value(doc: PdfDocument, page_index: int, name: str, value: str) -> bool:
    """Alanın değerini yazar. Aynı adlı tüm widget'lar güncellenir.

    Radyo gruplarında bu şarttır: bir düğme seçilince aynı adı paylaşan
    diğerleri ``Off`` olmalıdır, aksi hâlde birden çok seçenek işaretli
    görünür.
    """
    if not name:
        return False
    with doc.lock:
        if not doc.is_open or not (0 <= page_index < doc.raw.page_count):
            return False
        page = doc.raw.load_page(page_index)
        degisti = False
        for widget in page.widgets() or []:
            if (widget.field_name or "") != name:
                continue
            tur = _TYPE_NAMES.get(widget.field_type, "button")
            try:
                if tur in ("check", "radio"):
                    widget.field_value = value not in ("", "Off", "0")
                else:
                    widget.field_value = value
                widget.update()
                degisti = True
            except Exception:  # noqa: BLE001 - desteklenmeyen alan
                continue
    if degisti:
        doc.mark_dirty(page_index)
    return degisti


def toggle(doc: PdfDocument, field: FormField) -> bool:
    """Onay kutusunu/radyoyu çevirir.

    Radyo düğmeleri **kapatılmaz**: bir grupta seçili olanın üzerine
    tıklamak onu boşa düşürmemelidir (HTML radyo davranışı).
    """
    if field.type == "radio":
        if field.checked:
            return False
        return set_value(doc, field.page_index, field.name, field.on_state or "Yes")
    yeni = "Off" if field.checked else (field.on_state or "Yes")
    return set_value(doc, field.page_index, field.name, yeni)
