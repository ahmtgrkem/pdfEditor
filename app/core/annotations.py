"""Açıklama (annotation) ve içerik ekleme servisleri.

Tüm fonksiyonlar *görsel* koordinat alır (kullanıcının ekranda gördüğü,
döndürme uygulanmış sayfa uzayı) ve gerekli dönüşümü kendisi yapar.
"""
from __future__ import annotations

import atexit
import io
import math
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from . import fonts
from .document import PdfDocument
from .pdf_backend import Matrix, Point, Rect, fitz

RGB = tuple[float, float, float]


class MarkupKind(str, Enum):
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    SQUIGGLY = "squiggly"


class ShapeKind(str, Enum):
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    ARROW = "arrow"


@dataclass
class PenStyle:
    color: RGB = (0.90, 0.15, 0.15)
    fill: RGB | None = None
    width: float = 2.0
    opacity: float = 1.0


@dataclass
class TextStyle:
    family: str = fonts.DEFAULT_FAMILY
    size: float = 14.0
    color: RGB = (0.0, 0.0, 0.0)
    bold: bool = False
    italic: bool = False
    align: int = 0  # 0=sol 1=orta 2=sağ
    background: RGB | None = None
    border: bool = False
    #: Düzenlenen metnin belgedeki özgün font adı (``ABCDEF+FrutigerLTStd``).
    #: Verilirse ve gömülü font yeni metnin tüm karakterlerini taşıyorsa
    #: **o font** yeniden kullanılır; yazı tipi hiç değişmez.
    source_font: str | None = None


@dataclass
class WatermarkOptions:
    text: str = "TASLAK"
    family: str = fonts.DEFAULT_FAMILY
    size: float = 64.0
    color: RGB = (0.6, 0.6, 0.6)
    opacity: float = 0.25
    angle: float = 45.0
    pages: Sequence[int] | None = None  # None => tüm sayfalar
    image: bytes | None = None
    image_scale: float = 0.5



# ----------------------------------------------------------------------
# Metin işaretleme
# ----------------------------------------------------------------------
def add_markup(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    kind: MarkupKind,
    style: PenStyle,
) -> bool:
    """Seçim dikdörtgeniyle kesişen kelimeleri işaretler."""
    quads = doc.selection_quads(page_index, visual_rect)
    if not quads:
        return False
    with doc.lock:
        page = doc.raw.load_page(page_index)
        pdf_quads = [doc.to_pdf_quad(page_index, q) for q in quads]
        adder = {
            MarkupKind.HIGHLIGHT: page.add_highlight_annot,
            MarkupKind.UNDERLINE: page.add_underline_annot,
            MarkupKind.STRIKEOUT: page.add_strikeout_annot,
            MarkupKind.SQUIGGLY: page.add_squiggly_annot,
        }[kind]
        annot = adder(pdf_quads)
        annot.set_colors(stroke=style.color)
        annot.set_opacity(style.opacity)
        annot.update()
    doc.mark_dirty(page_index)
    return True


# ----------------------------------------------------------------------
# Serbest çizim
# ----------------------------------------------------------------------
def add_ink(
    doc: PdfDocument,
    page_index: int,
    strokes: Sequence[Sequence[tuple[float, float]]],
    style: PenStyle,
) -> bool:
    clean = [s for s in strokes if len(s) >= 2]
    if not clean:
        return False
    with doc.lock:
        page = doc.raw.load_page(page_index)
        derot = page.rotation != 0
        pdf_strokes: list[list[tuple[float, float]]] = []
        for stroke in clean:
            if derot:
                mat = page.derotation_matrix
                pts = [Point(x, y) * mat for x, y in stroke]
                pdf_strokes.append([(p.x, p.y) for p in pts])
            else:
                pdf_strokes.append([(float(x), float(y)) for x, y in stroke])
        annot = page.add_ink_annot(pdf_strokes)
        annot.set_colors(stroke=style.color)
        annot.set_border(width=style.width)
        annot.set_opacity(style.opacity)
        annot.update()
    doc.mark_dirty(page_index)
    return True


# ----------------------------------------------------------------------
# Şekiller
# ----------------------------------------------------------------------
def add_shape(
    doc: PdfDocument,
    page_index: int,
    kind: ShapeKind,
    p1: tuple[float, float],
    p2: tuple[float, float],
    style: PenStyle,
) -> bool:
    with doc.lock:
        page = doc.raw.load_page(page_index)
        derot = page.rotation != 0

        if kind in (ShapeKind.LINE, ShapeKind.ARROW):
            a, b = Point(*p1), Point(*p2)
            if abs(a.x - b.x) < 1 and abs(a.y - b.y) < 1:
                return False
            if derot:
                a = a * page.derotation_matrix
                b = b * page.derotation_matrix
            annot = page.add_line_annot(a, b)
            if kind is ShapeKind.ARROW:
                annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
            annot.set_colors(stroke=style.color)
            if style.fill is not None:
                annot.set_colors(stroke=style.color, fill=style.fill)
        else:
            rect = Rect(min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
            if rect.width < 2 or rect.height < 2:
                return False
            if derot:
                rect = rect * page.derotation_matrix
            annot = (
                page.add_rect_annot(rect)
                if kind is ShapeKind.RECT
                else page.add_circle_annot(rect)
            )
            annot.set_colors(stroke=style.color, fill=style.fill)

        annot.set_border(width=style.width)
        annot.set_opacity(style.opacity)
        annot.update()
    doc.mark_dirty(page_index)
    return True


# ----------------------------------------------------------------------
# Metin ekleme
# ----------------------------------------------------------------------
#: PyMuPDF, ``insert_textbox`` kutusuna sığdırmak için fontu kendiliğinden
#: küçültür. Bunu engellemek adına kutu yüksekliği en az ``fontsize * 1.5``
#: olacak şekilde genişletilir.
MIN_BOX_HEIGHT_FACTOR = 1.5

#: Genişliği verilmemiş kutular için varsayılan genişlik (pt).
DEFAULT_BOX_WIDTH = 320.0

#: Metin değiştirilirken silinecek şeridin taban çizgisine göre yüksekliği
#: (punto çarpanı). Hedef satırın çıkıntılarını tamamen kapsar ama üst/alt
#: satırın gliflerine değmez.
REDACT_ASCENT = 0.90
REDACT_DESCENT = 0.30



# ----------------------------------------------------------------------
# Belgenin kendi gömülü fontunu yeniden kullanma
# ----------------------------------------------------------------------
#: (belge, xref) -> geçici font dosyası. Aynı fontla arka arkaya düzenleme
#: yapıldığında font tekrar tekrar çıkarılmasın.
_EMBEDDED_FONTS: dict[tuple[int, int], str] = {}


@atexit.register
def _cleanup_embedded_fonts() -> None:
    for yol in _EMBEDDED_FONTS.values():
        try:
            os.remove(yol)
        except OSError:
            pass


def _font_key(name: str) -> str:
    """``ABCDEF+Frutiger LT Std-Roman`` -> ``frutigerltstdroman``."""
    return "".join(
        c for c in (name or "").split("+")[-1].lower() if c.isalnum()
    )


def _font_covers(fontfile: str, text: str) -> bool:
    """Font, metindeki **her** karakteri çizebiliyor mu?

    Gömülü fontlar çoğunlukla alt kümedir (yalnızca sayfada geçen glifler).
    Kullanıcı yeni bir harf yazdığında o glif yoksa metin boş kutulara
    dönerdi; bu yüzden kapsama denetlenmeden özgün font kullanılmaz.
    """
    try:
        font = fitz.Font(fontfile=fontfile)
    except Exception:  # noqa: BLE001 - bozuk/desteklenmeyen font
        return False
    return all(
        font.has_glyph(ord(ch))
        for ch in set(text)
        if ch not in "\n\r\t"
    )


def _extract_to_file(doc: PdfDocument, xref: int) -> str | None:
    """Gömülü fontu geçici dosyaya yazar; MuPDF yükleyemiyorsa ``None``."""
    anahtar = (id(doc.raw), int(xref))
    yol = _EMBEDDED_FONTS.get(anahtar)
    if yol is not None:
        return yol if os.path.exists(yol) else None
    try:
        _ad, ext, _t, veri = doc.raw.extract_font(xref)
    except Exception:  # noqa: BLE001
        return None
    if not veri:
        return None
    gecici = tempfile.NamedTemporaryFile(
        prefix="agy_font_", suffix=f".{ext or 'ttf'}", delete=False
    )
    gecici.write(veri)
    gecici.close()
    try:
        fitz.Font(fontfile=gecici.name)
    except Exception:  # noqa: BLE001 - bozuk font gömülmesin
        os.remove(gecici.name)
        return None
    _EMBEDDED_FONTS[anahtar] = gecici.name
    return gecici.name


def embedded_font_files(
    doc: PdfDocument, page_index: int, base_name: str | None
) -> list[str]:
    """Ada uyan **bütün** gömülü font dosyaları (sayfadaki alt kümeler).

    Tek bir dosya döndürmek yetmiyor: bir sayfada aynı adı taşıyan birden
    çok alt küme bulunabiliyor (ör. ``AAAMNC+CharisSIL`` 19 glif,
    ``UMGJVJ+CharisSIL`` 86 glif). İlkini seçmek çoğu zaman metni
    çizemeyen kümeyi seçmek oluyordu; çağıran, işine yarayanı seçer.

    Biçim ayrımı yapılmaz: ``ttf``, ``otf``, ``cff`` (Type1C) ve ``pfa``
    (Type1) hepsi çalışır. ``n/a`` fontun gömülü **olmadığını** söyler.
    """
    if not base_name:
        return []
    hedef = _font_key(base_name)
    if not hedef:
        return []
    yollar: list[str] = []
    with doc.lock:
        try:
            kayitlar = doc.raw.load_page(page_index).get_fonts(full=False)
        except Exception:  # noqa: BLE001 - bozuk kaynak sözlüğü
            return []
        for kayit in kayitlar:
            xref, uzanti, _tur, basefont = kayit[0], kayit[1], kayit[2], kayit[3]
            if uzanti in ("n/a", "", None):
                continue
            # Span'ın bildirdiği ad ile kaynak sözlüğündeki ad birebir aynı
            # olmayabilir ("Georgia" / "AAAAAA+Georgia Regular").
            aday = _font_key(str(basefont))
            if not aday or not (aday == hedef
                                or aday.startswith(hedef)
                                or hedef.startswith(aday)):
                continue
            yol = _extract_to_file(doc, xref)
            if yol:
                yollar.append(yol)
    return yollar


def embedded_font_path(
    doc: PdfDocument, page_index: int, base_name: str | None
) -> str | None:
    """Ekranda göstermek için en zengin alt küme (en çok kod noktası)."""
    en_iyi, en_cok = None, -1
    for yol in embedded_font_files(doc, page_index, base_name):
        try:
            sayi = len(fitz.Font(fontfile=yol).valid_codepoints())
        except Exception:  # noqa: BLE001
            continue
        if sayi > en_cok:
            en_iyi, en_cok = yol, sayi
    return en_iyi


def embedded_fontfile(
    doc: PdfDocument, page_index: int, base_name: str | None, text: str
) -> str | None:
    """Metnin **tamamını** çizebilen gömülü alt kümeyi dosya olarak verir.

    Böylece belgedeki yazı tipi kurulu olmasa bile düzenlenen metin aynı
    fontla yazılır — sistemdeki bir aileye "benzetme" yapılmaz. Hiçbir alt
    küme yetmiyorsa ``None``: eksik glif, metni boş kutulara çevirirdi.
    """
    if not text.strip():
        return None
    for yol in embedded_font_files(doc, page_index, base_name):
        if _font_covers(yol, text):
            return yol
    return None


def add_text(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    text: str,
    style: TextStyle,
    origin: tuple[float, float] | None = None,
    line_height: float | None = None,
    fontfile: str | None = None,
) -> bool:
    """Sayfaya Unicode destekli metin kutusu veya baseline hizalı metin ekler.

    ``origin`` verilirse metin *birebir* o taban çizgisine oturtulur
    (``insert_text``); satır kaydırma/otomatik küçültme uygulanmaz. Canlı metin
    düzenleyici bu yolu kullanır, böylece ekranda görülen konum ile PDF'e
    işlenen konum arasında kayma oluşmaz.

    ``line_height`` satırlar arası taban çizgisi mesafesidir (pt); verilmezse
    PyMuPDF'in font tabanlı varsayılanı kullanılır.

    ``origin`` verilmezse metin ``visual_rect`` içine sığacak şekilde
    kaydırılarak (ve gerekirse punto küçültülerek) yazılır.
    """
    if not text.strip():
        return False

    if fontfile:
        # Belgeden çıkarılan özgün font: takma adı dosyaya göre türetilir.
        fontname = "F" + "".join(
            c for c in os.path.splitext(os.path.basename(fontfile))[0] if c.isalnum()
        )
    else:
        fontname, fontfile = fonts.resolve(style.family, style.bold, style.italic)
    with doc.lock:
        page = doc.raw.load_page(page_index)
        rect = Rect(*visual_rect)
        rect.normalize()
        if rect.width < 10.0:
            rect = Rect(rect.x0, rect.y0, rect.x0 + DEFAULT_BOX_WIDTH, rect.y1)
        min_height = style.size * MIN_BOX_HEIGHT_FACTOR
        if rect.height < min_height:
            rect = Rect(rect.x0, rect.y0, rect.x1, rect.y0 + min_height)

        rotate = 0
        if page.rotation:
            rect = rect * page.derotation_matrix
            rect.normalize()
            rotate = (360 - page.rotation) % 360

        if style.background is not None or style.border:
            shape = page.new_shape()
            shape.draw_rect(rect)
            shape.finish(
                color=style.color if style.border else None,
                fill=style.background,
                width=0.8 if style.border else 0,
            )
            shape.commit(overlay=True)

        # -- 1) Taban çizgisi hizalı yol (WYSIWYG) ----------------------
        # Yalnızca sola dayalı metinde geçerli; ortalama/sağa dayama kutu
        # genişliğine ihtiyaç duyduğu için insert_textbox'a düşer.
        if origin is not None and style.align == 0:
            pdf_origin = doc.to_pdf_point(page_index, Point(*origin))
            # PyMuPDF ``lineheight``i fontsize çarpanı olarak ister.
            multiplier = None
            if line_height and style.size > 0:
                multiplier = max(0.5, float(line_height) / float(style.size))
            try:
                written = page.insert_text(
                    pdf_origin,
                    text.split("\n"),
                    fontsize=style.size,
                    lineheight=multiplier,
                    fontname=fontname,
                    fontfile=fontfile,
                    color=style.color,
                    rotate=rotate,
                    overlay=True,
                )
                if written > 0:
                    doc.mark_dirty(page_index)
                    return True
            except Exception:  # noqa: BLE001 - kutu yoluna düş
                pass

        # -- 2) Kutuya sığdırma yolu ------------------------------------
        # Metin sığana kadar font boyutunu hassasça ayarla
        size = style.size
        while size >= 4:
            rc = page.insert_textbox(
                rect,
                text,
                fontsize=size,
                fontname=fontname,
                fontfile=fontfile,
                color=style.color,
                align=style.align,
                rotate=rotate,
                overlay=True,
            )
            if rc >= 0:
                break
            size -= 0.5
        else:
            return False
    doc.mark_dirty(page_index)
    return True


def find_text_at_point(
    doc: PdfDocument,
    page_index: int,
    visual_point: tuple[float, float],
) -> dict | None:
    """Tıklanan koordinattaki metin bloğunu, origin baseline'ını ve tipografisini tespit eder."""
    vx, vy = visual_point
    with doc.lock:
        page = doc.raw.load_page(page_index)
        pt = Point(vx, vy)
        if page.rotation != 0:
            pt = pt * page.derotation_matrix
        px, py = pt.x, pt.y

        td = page.get_text("dict")
        best_span = None
        min_dist = float("inf")

        for block in td.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text_str = span.get("text", "").strip()
                    if not text_str:
                        continue
                    x0, y0, x1, y1 = span.get("bbox", (0, 0, 0, 0))
                    if (x0 - 6 <= px <= x1 + 6) and (y0 - 6 <= py <= y1 + 6):
                        c_int = span.get("color", 0)
                        r = ((c_int >> 16) & 0xFF) / 255.0
                        g = ((c_int >> 8) & 0xFF) / 255.0
                        b = (c_int & 0xFF) / 255.0

                        v_rect = doc.to_visual_rect(page_index, Rect(x0, y0, x1, y1))
                        rect_tuple = (v_rect.x0, v_rect.y0, v_rect.x1, v_rect.y1)

                        ox, oy = span.get("origin", (x0, y1))
                        v_origin = doc.to_visual_point(page_index, Point(ox, oy))
                        origin_tuple = (v_origin.x, v_origin.y)

                        font_name = str(span.get("font", fonts.DEFAULT_FAMILY))
                        flags = span.get("flags", 0)
                        bold = bool(flags & 16) or ("bold" in font_name.lower())
                        italic = bool(flags & 2) or ("italic" in font_name.lower()) or ("oblique" in font_name.lower())

                        # Kurulu yazı tipleri arasından en yakını. Eskiden
                        # burada sekiz dallı bir zincir vardı ve tanımadığı
                        # her fontu Arial yapıyordu.
                        family = fonts.match(font_name)

                        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                        dist = (px - cx) ** 2 + (py - cy) ** 2
                        if dist < min_dist:
                            min_dist = dist
                            best_span = {
                                "text": text_str,
                                "rect": rect_tuple,
                                "pdf_rect": (x0, y0, x1, y1),
                                "origin": origin_tuple,
                                "pdf_origin": (ox, oy),
                                "size": float(span.get("size", 12.0)),
                                "font": family,
                                "raw_font": font_name,
                                "bold": bold,
                                "italic": italic,
                                "color": (r, g, b),
                            }
        return best_span


def _line_band(page, pdf_rect: Rect, baseline: float,
               size: float) -> tuple[float, float]:
    """Hedef satırın, komşu satırlara taşmayan dikey şeridi.

    Font metriğinden gelen yükseklik sıkı satır aralığında üst/alt satırın
    kutusuna giriyor. Şerit, komşu satırın **kendi şeridinin** kenarında
    kesilir. Her satır için aynı kural işlediğinden şeritler asla üst üste
    binmez; hedefin çıkıntıları içeride kalır, komşununkilere dokunulmaz.
    (Taban çizgileri arasındaki orta nokta fazla ihtiyatlı kalıyor: hedefin
    kendi çıkıntıları şeridin dışında kalınca metin silinmiyordu.)
    """
    ust = baseline - REDACT_ASCENT * size
    alt = baseline + REDACT_DESCENT * size
    try:
        sozluk = page.get_text("dict")
    except Exception:  # noqa: BLE001 - bozuk içerik akışı
        return ust, alt
    for blok in sozluk.get("blocks", []):
        if blok.get("type") != 0:
            continue
        for satir in blok.get("lines", []):
            for span in satir.get("spans", []):
                x0, _y0, x1, _y1 = span.get("bbox", (0, 0, 0, 0))
                if x1 <= pdf_rect.x0 or x0 >= pdf_rect.x1:
                    continue                    # yatayda kesişmiyor
                oy = float(span.get("origin", (0, baseline))[1])
                if abs(oy - baseline) < 0.5:
                    continue                    # hedefin kendi satırı
                komsu = float(span.get("size", size))
                if oy < baseline:
                    ust = max(ust, oy + REDACT_DESCENT * komsu)
                else:
                    alt = min(alt, oy - REDACT_ASCENT * komsu)
    return (ust, alt) if alt > ust else (baseline - 0.1, baseline + 0.1)


def replace_text(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    new_text: str,
    style: TextStyle,
    origin: tuple[float, float] | None = None,
    line_height: float | None = None,
) -> bool:
    """Mevcut metin alanını siler (redaction) ve yerine yeni metni yazar."""
    # Özgün font redaksiyondan **önce** çıkarılır: metin silindikten sonra
    # font kaynak sözlüğünden düşebiliyor ve geri kazanılamıyor.
    ozgun = embedded_fontfile(doc, page_index, style.source_font, new_text)

    with doc.lock:
        page = doc.raw.load_page(page_index)
        v_rect = Rect(*visual_rect)
        pdf_rect = doc.to_pdf_rect(page_index, v_rect)

        if origin is not None and style.size > 0:
            # Span'ın bildirdiği kutu font metriğinden gelir ve sıkı satır
            # aralığında **komşu satıra taşar**; o kutuyla redaksiyon yapmak
            # üstteki satırı da siliyordu. Bunun yerine kutu taban çizgisinden
            # kurulur: hedef tamamen kalkar, komşu satıra dokunulmaz.
            taban = doc.to_pdf_point(page_index, Point(*origin)).y
            ust, alt = _line_band(page, pdf_rect, taban, float(style.size))
            clean_rect = Rect(pdf_rect.x0 - 0.5, ust, pdf_rect.x1 + 0.5, alt)
        else:
            # Orijinal metni kalıntısız silmek için 0.5pt tampon genişletme
            clean_rect = Rect(pdf_rect.x0 - 0.5, pdf_rect.y0 - 0.5,
                              pdf_rect.x1 + 0.5, pdf_rect.y1 + 0.5)
        # ``fill`` verilmez: dolgu, alanı düz bir dikdörtgenle boyar ve
        # metnin altındaki arka planı (desen, logo, renkli zemin) yok eder —
        # kullanıcı düzenlemeye girer girmez metnin ardında beyaz bir kutu
        # belirir. Yalnızca metin kaldırılır; görseller ve çizimler korunur.
        page.add_redact_annot(clean_rect, fill=False)
        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
            )
        except (AttributeError, TypeError):   # eski PyMuPDF sürümleri
            page.apply_redactions()

    return add_text(
        doc, page_index, visual_rect, new_text, style,
        origin=origin, line_height=line_height, fontfile=ozgun,
    )


# ----------------------------------------------------------------------
# Görsel / imza
# ----------------------------------------------------------------------
def add_image(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    image_data: bytes,
    keep_aspect: bool = True,
    front: bool = True,
) -> bool:
    """``front=False`` görseli sayfa içeriğinin **altına** çizer (z sırası)."""
    if not image_data:
        return False
    with doc.lock:
        page = doc.raw.load_page(page_index)
        rect = Rect(*visual_rect)
        if rect.width < 2 or rect.height < 2:
            return False
        rotate = 0
        if page.rotation:
            rect = rect * page.derotation_matrix
            rect.normalize()
            rotate = (360 - page.rotation) % 360
        page.insert_image(
            rect,
            stream=image_data,
            keep_proportion=keep_aspect,
            overlay=front,
            rotate=rotate,
        )
    doc.mark_dirty(page_index)
    return True


# ----------------------------------------------------------------------
# Sayfadaki görselleri seçme / taşıma / silme / z sırası
# ----------------------------------------------------------------------
def list_images(doc: PdfDocument, page_index: int) -> list[dict]:
    """Sayfadaki görsel yerleşimleri; çizim sırasına göre (sonuncu en üstte)."""
    sonuc: list[dict] = []
    with doc.lock:
        if not (0 <= page_index < doc.raw.page_count):
            return []
        try:
            bilgiler = doc.raw.load_page(page_index).get_image_info(xrefs=True)
        except Exception:  # noqa: BLE001 - bozuk kaynak sözlüğü
            return []
        for bilgi in bilgiler:
            kutu = Rect(bilgi.get("bbox", (0, 0, 0, 0)))
            kutu.normalize()
            if kutu.width < 2 or kutu.height < 2:
                continue
            gorsel = doc.to_visual_rect(page_index, kutu)
            sonuc.append({
                "xref": int(bilgi.get("xref", 0)),
                "rect": (gorsel.x0, gorsel.y0, gorsel.x1, gorsel.y1),
                "pdf_rect": (kutu.x0, kutu.y0, kutu.x1, kutu.y1),
            })
    return sonuc


def image_at_point(
    doc: PdfDocument, page_index: int, visual_point: tuple[float, float]
) -> dict | None:
    """Noktadaki görsel. Üst üste binenlerde **en küçüğü** seçilir.

    Tam sayfa bir arka plan görseli varsa en üstteki kural onun üzerindeki
    küçük logoyu seçilemez kılıyordu.
    """
    x, y = visual_point
    en_iyi = None
    en_kucuk = float("inf")
    for gorsel in list_images(doc, page_index):
        x0, y0, x1, y1 = gorsel["rect"]
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        alan = (x1 - x0) * (y1 - y0)
        if alan <= en_kucuk:      # eşitlikte sonraki (üstteki) kazanır
            en_kucuk = alan
            en_iyi = gorsel
    return en_iyi


def image_bytes(doc: PdfDocument, xref: int) -> bytes:
    """Görselin ham baytları; okunamazsa boş."""
    if not xref:
        return b""
    with doc.lock:
        try:
            return doc.raw.extract_image(int(xref)).get("image") or b""
        except Exception:  # noqa: BLE001 - gömülü olmayan/bozuk görsel
            return b""


def remove_image(
    doc: PdfDocument, page_index: int, visual_rect: tuple[float, float, float, float]
) -> bool:
    """Verilen alandaki görseli sayfadan kaldırır; metin ve çizimler kalır."""
    with doc.lock:
        page = doc.raw.load_page(page_index)
        kutu = doc.to_pdf_rect(page_index, Rect(*visual_rect))
        kutu.normalize()
        if kutu.width < 1 or kutu.height < 1:
            return False
        page.add_redact_annot(kutu, fill=False)
        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_REMOVE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_NONE,
            )
        except (AttributeError, TypeError):   # eski PyMuPDF sürümleri
            page.apply_redactions()
    doc.mark_dirty(page_index)
    return True


def move_image(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    new_visual_rect: tuple[float, float, float, float],
    xref: int,
    front: bool = True,
) -> bool:
    """Görseli yeni bir dikdörtgene taşır/boyutlandırır.

    PDF'te bir görselin yerleşimini yerinde düzenlemek yoktur; baytları alınır,
    eski yerleşim kaldırılır ve yeni konuma yeniden çizilir.
    """
    veri = image_bytes(doc, xref)
    if not veri:
        return False
    if not remove_image(doc, page_index, visual_rect):
        return False
    return add_image(
        doc, page_index, new_visual_rect, veri, keep_aspect=False, front=front
    )


# ----------------------------------------------------------------------
# Filigran
# ----------------------------------------------------------------------
def _apply_alpha(image_data: bytes, opacity: float) -> bytes:
    """PNG alfa kanalını ölçekleyerek şeffaflık uygular."""
    from PIL import Image

    img = Image.open(io.BytesIO(image_data)).convert("RGBA")
    alpha = img.getchannel("A").point(lambda v: int(v * max(0.0, min(1.0, opacity))))
    img.putalpha(alpha)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def add_watermark(doc: PdfDocument, opts: WatermarkOptions) -> int:
    """Seçili sayfalara filigran uygular; işlenen sayfa sayısını döndürür."""
    with doc.lock:
        total = doc.raw.page_count
        targets = list(opts.pages) if opts.pages is not None else list(range(total))
        targets = [i for i in targets if 0 <= i < total]
        if not targets:
            return 0

        image_stream = _apply_alpha(opts.image, opts.opacity) if opts.image else None
        fontname, fontfile = (None, None)
        if not image_stream:
            fontname, fontfile = fonts.resolve(opts.family)

        for idx in targets:
            page = doc.raw.load_page(idx)
            rect = page.rect
            if page.rotation:
                rect = rect * page.derotation_matrix
                rect.normalize()
            center = Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)

            if image_stream:
                scale = max(0.05, min(1.0, opts.image_scale))
                w = rect.width * scale
                h = rect.height * scale
                box = Rect(center.x - w / 2, center.y - h / 2, center.x + w / 2, center.y + h / 2)
                page.insert_image(box, stream=image_stream, overlay=True, keep_proportion=True)
                continue

            angle = math.radians(opts.angle)
            morph = (center, Matrix(math.cos(angle), -math.sin(angle),
                                    math.sin(angle), math.cos(angle), 0, 0))
            text_w = fitz.get_text_length(
                opts.text, fontname=fontname, fontsize=opts.size
            ) if fontfile is None else opts.size * 0.55 * len(opts.text)
            start = Point(center.x - text_w / 2, center.y + opts.size * 0.35)
            page.insert_text(
                start,
                opts.text,
                fontsize=opts.size,
                fontname=fontname,
                fontfile=fontfile,
                color=opts.color,
                fill_opacity=opts.opacity,
                stroke_opacity=opts.opacity,
                morph=morph,
                overlay=True,
            )
    for idx in targets:
        doc.mark_dirty(idx)
    return len(targets)


# ----------------------------------------------------------------------
# Sorgulama / silme
# ----------------------------------------------------------------------

def delete_annot_at(doc: PdfDocument, page_index: int, visual_point: tuple[float, float]) -> bool:
    """Verilen noktadaki (en küçük alanlı) annotation'ı siler."""
    pt = Point(*visual_point)
    with doc.lock:
        page = doc.raw.load_page(page_index)
        if page.rotation:
            pt = pt * page.derotation_matrix
        best = None
        best_area = float("inf")
        for annot in page.annots():
            r = annot.rect
            if r.contains(pt):
                area = r.get_area()
                if area < best_area:
                    best, best_area = annot, area
        if best is None:
            return False
        page.delete_annot(best)
    doc.mark_dirty(page_index)
    return True


def delete_annots_in(
    doc: PdfDocument, page_index: int, visual_rect: tuple[float, float, float, float]
) -> int:
    """Silgi sürüklemesi: dikdörtgenle kesişen tüm annotation'ları siler."""
    sel = Rect(*visual_rect)
    with doc.lock:
        page = doc.raw.load_page(page_index)
        if page.rotation:
            sel = sel * page.derotation_matrix
            sel.normalize()
        victims = [a for a in page.annots() if not (Rect(a.rect) & sel).is_empty]
        for annot in victims:
            page.delete_annot(annot)
    if victims:
        doc.mark_dirty(page_index)
    return len(victims)


def clear_page_annots(doc: PdfDocument, page_index: int) -> int:
    with doc.lock:
        page = doc.raw.load_page(page_index)
        annots = list(page.annots())
        for annot in annots:
            page.delete_annot(annot)
    if annots:
        doc.mark_dirty(page_index)
    return len(annots)

