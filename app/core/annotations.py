"""Açıklama (annotation) ve içerik ekleme servisleri.

Tüm fonksiyonlar *görsel* koordinat alır (kullanıcının ekranda gördüğü,
döndürme uygulanmış sayfa uzayı) ve gerekli dönüşümü kendisi yapar.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from . import fonts
from .document import PdfDocument
from .pdf_backend import Matrix, Point, Quad, Rect, fitz

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


@dataclass
class AnnotInfo:
    """Silgi/seçim için hafif annotation tanımı (görsel koordinatlı)."""

    index: int
    kind: int
    type_name: str
    rect: tuple[float, float, float, float]
    info: dict = field(default_factory=dict)


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


def baseline_origin(
    visual_rect: tuple[float, float, float, float], style: TextStyle
) -> tuple[float, float]:
    """Kutunun sol-üst köşesine oturan metnin taban çizgisi (baseline) noktası.

    ``insert_text`` için ``origin`` noktası metnin *taban çizgisidir*; kutunun
    üst kenarı değil. Bu yüzden fontun üst çıkıntısı eklenir::

        origin_x = x0
        origin_y = y0 + ascender * fontsize
    """
    asc = fonts.ascender(style.family, style.bold, style.italic)
    return float(visual_rect[0]), float(visual_rect[1]) + asc * float(style.size)


def add_text(
    doc: PdfDocument,
    page_index: int,
    visual_rect: tuple[float, float, float, float],
    text: str,
    style: TextStyle,
    origin: tuple[float, float] | None = None,
    line_height: float | None = None,
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

                        fn_lower = font_name.lower()
                        if "times" in fn_lower:
                            family = "Times New Roman"
                        elif "courier" in fn_lower:
                            family = "Courier New"
                        elif "consolas" in fn_lower:
                            family = "Consolas"
                        elif "georgia" in fn_lower:
                            family = "Georgia"
                        elif "verdana" in fn_lower:
                            family = "Verdana"
                        elif "tahoma" in fn_lower:
                            family = "Tahoma"
                        elif "segoe" in fn_lower:
                            family = "Segoe UI"
                        elif "calibri" in fn_lower:
                            family = "Calibri"
                        else:
                            family = "Arial"

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
    with doc.lock:
        page = doc.raw.load_page(page_index)
        v_rect = Rect(*visual_rect)
        pdf_rect = doc.to_pdf_rect(page_index, v_rect)

        # Orijinal metni kalıntısız silmek için 0.5pt tampon genişletme
        clean_rect = Rect(pdf_rect.x0 - 0.5, pdf_rect.y0 - 0.5, pdf_rect.x1 + 0.5, pdf_rect.y1 + 0.5)
        page.add_redact_annot(clean_rect, fill=(1, 1, 1))
        page.apply_redactions()

    return add_text(
        doc, page_index, visual_rect, new_text, style,
        origin=origin, line_height=line_height,
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
) -> bool:
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
            overlay=True,
            rotate=rotate,
        )
    doc.mark_dirty(page_index)
    return True


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
def list_annots(doc: PdfDocument, page_index: int) -> list[AnnotInfo]:
    result: list[AnnotInfo] = []
    with doc.lock:
        page = doc.raw.load_page(page_index)
        for i, annot in enumerate(page.annots()):
            vrect = annot.rect
            if page.rotation:
                vrect = Rect(vrect) * page.rotation_matrix
                vrect.normalize()
            result.append(
                AnnotInfo(
                    index=i,
                    kind=annot.type[0],
                    type_name=annot.type[1],
                    rect=(vrect.x0, vrect.y0, vrect.x1, vrect.y1),
                    info=dict(annot.info or {}),
                )
            )
    return result


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

