"""Sayfa yönetimi: döndürme, silme, ekleme, sıralama, birleştirme, bölme."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from .document import PdfDocument, PdfError
from .pdf_backend import fitz

A4_PORTRAIT = (595.0, 842.0)


# ----------------------------------------------------------------------
# Sayfa aralığı ayrıştırma
# ----------------------------------------------------------------------
def parse_page_ranges(text: str, page_count: int) -> list[int]:
    """"1-3, 5, 8-" ifadesini 0 tabanlı sayfa indekslerine çevirir."""
    text = (text or "").strip()
    if not text:
        return list(range(page_count))

    indices: list[int] = []
    seen: set[int] = set()
    for chunk in re.split(r"[,;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", chunk)
        if m:
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else page_count
        elif chunk.isdigit():
            start = end = int(chunk)
        else:
            raise ValueError(f"Geçersiz sayfa aralığı: '{chunk}'")
        if start > end:
            start, end = end, start
        for p in range(start, end + 1):
            i = p - 1
            if 0 <= i < page_count and i not in seen:
                seen.add(i)
                indices.append(i)
    if not indices:
        raise ValueError("Sayfa aralığı hiçbir sayfayla eşleşmedi.")
    return indices


def format_ranges(indices: Sequence[int]) -> str:
    """0 tabanlı indeks listesini "1-3, 7" biçiminde metne çevirir."""
    if not indices:
        return ""
    ordered = sorted(set(indices))
    parts: list[str] = []
    start = prev = ordered[0]
    for i in ordered[1:]:
        if i == prev + 1:
            prev = i
            continue
        parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        start = prev = i
    parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
    return ", ".join(parts)


# ----------------------------------------------------------------------
# Döndürme
# ----------------------------------------------------------------------
def rotate_pages(doc: PdfDocument, indices: Iterable[int], delta: int) -> int:
    """Sayfaları ``delta`` derece (90'ın katı) döndürür."""
    count = 0
    with doc.lock:
        total = doc.raw.page_count
        for i in indices:
            if not (0 <= i < total):
                continue
            page = doc.raw.load_page(i)
            page.set_rotation((page.rotation + delta) % 360)
            count += 1
    if count:
        doc.mark_dirty()
    return count


def set_rotation(doc: PdfDocument, indices: Iterable[int], value: int) -> int:
    count = 0
    with doc.lock:
        total = doc.raw.page_count
        for i in indices:
            if 0 <= i < total:
                doc.raw.load_page(i).set_rotation(value % 360)
                count += 1
    if count:
        doc.mark_dirty()
    return count


# ----------------------------------------------------------------------
# Ekleme / silme / sıralama
# ----------------------------------------------------------------------
def delete_pages(doc: PdfDocument, indices: Sequence[int]) -> int:
    with doc.lock:
        total = doc.raw.page_count
        victims = sorted({i for i in indices if 0 <= i < total})
        if not victims:
            return 0
        if len(victims) >= total:
            raise PdfError("Belgedeki tüm sayfalar silinemez.")
        doc.raw.delete_pages(victims)
    doc.mark_dirty()
    return len(victims)


def insert_blank_page(
    doc: PdfDocument, at: int, width: float | None = None, height: float | None = None
) -> int:
    """``at`` konumuna boş sayfa ekler ve yeni sayfanın indeksini döndürür."""
    with doc.lock:
        total = doc.raw.page_count
        at = max(0, min(at, total))
        if width is None or height is None:
            ref = min(at, total - 1) if total else -1
            if ref >= 0:
                r = doc.raw.load_page(ref).rect
                width, height = r.width, r.height
            else:
                width, height = A4_PORTRAIT
        doc.raw.new_page(pno=at, width=width, height=height)
    doc.mark_dirty()
    return at


def duplicate_pages(doc: PdfDocument, indices: Sequence[int]) -> int:
    with doc.lock:
        total = doc.raw.page_count
        targets = sorted({i for i in indices if 0 <= i < total})
        if not targets:
            return 0
        # Sondan başa kopyala ki indeksler kaymasın
        for i in reversed(targets):
            doc.raw.fullcopy_page(i, i + 1)
    doc.mark_dirty()
    return len(targets)


def move_page(doc: PdfDocument, source: int, target: int) -> bool:
    with doc.lock:
        total = doc.raw.page_count
        if not (0 <= source < total) or not (0 <= target <= total) or source == target:
            return False
        doc.raw.move_page(source, target)
    doc.mark_dirty()
    return True


def reorder_pages(doc: PdfDocument, order: Sequence[int]) -> bool:
    """Sayfaları verilen tam permütasyona göre yeniden sıralar."""
    with doc.lock:
        total = doc.raw.page_count
        if sorted(order) != list(range(total)):
            raise PdfError("Geçersiz sayfa sıralaması (tam permütasyon bekleniyor).")
        if list(order) == list(range(total)):
            return False
        doc.raw.select(list(order))
    doc.mark_dirty()
    return True


# ----------------------------------------------------------------------
# Dışa aktarma / birleştirme / bölme
# ----------------------------------------------------------------------
def extract_pages(doc: PdfDocument, indices: Sequence[int], out_path: str) -> str:
    """Seçili sayfaları yeni bir PDF olarak kaydeder."""
    with doc.lock:
        total = doc.raw.page_count
        picks = [i for i in indices if 0 <= i < total]
        if not picks:
            raise PdfError("Dışa aktarılacak sayfa seçilmedi.")
        out = fitz.open()
        try:
            for i in picks:
                out.insert_pdf(doc.raw, from_page=i, to_page=i)
            out.save(out_path, garbage=3, deflate=True)
        finally:
            out.close()
    return out_path


def open_source(path: str, password: str | None = None):
    """Birleştirme/ekleme için kaynak belgeyi açar.

    Dinamik XFA formlarının sayfa akışı tek bir "bu belgeyi görmek için Adobe
    Reader gerekir" uyarı sayfasından oluşur; form içeriği gömülü XML
    şablonundadır. Böyle bir dosya olduğu gibi birleştirilirse çıktıya form
    değil o uyarı sayfası giriyordu. Bu yüzden şablon statik sayfalara
    çizilir (Araçlar ▸ Formu görüntüle ile aynı çizim) ve o belge döndürülür.

    Çağıran döndürülen belgeyi ``close()`` etmelidir.
    """
    doc = fitz.open(path)
    try:
        if doc.needs_pass and not (password and doc.authenticate(password)):
            raise PdfError(f"Parola gerekiyor: {os.path.basename(path)}")

        from . import xfa

        if not xfa.is_dynamic(doc):
            return doc

        from . import xfa_render

        packets = xfa.read_packets(doc)
        if "template" not in packets:
            return doc
        template = xfa.packet_data(doc, packets["template"])
        values = xfa.read_values(
            xfa.packet_data(doc, packets["datasets"]) if "datasets" in packets else b""
        )
        try:
            data = xfa_render.render_bytes(template, values)
        except Exception:  # noqa: BLE001 - olağandışı şablon: uyarı sayfasına düş
            return doc
        rendered = fitz.open(stream=data, filetype="pdf")
        if rendered.page_count == 0:
            rendered.close()
            return doc
    except Exception:
        doc.close()
        raise
    doc.close()
    return rendered


def merge_documents(
    sources: Sequence[tuple[str, str | None, str]],
    out_path: str,
) -> str:
    """Birden çok PDF'i tek dosyada birleştirir.

    ``sources``: (dosya yolu, parola|None, sayfa aralığı ifadesi) üçlüleri.
    """
    if not sources:
        raise PdfError("Birleştirilecek dosya yok.")
    out = fitz.open()
    try:
        for path, password, ranges in sources:
            src = open_source(path, password)
            try:
                picks = parse_page_ranges(ranges, src.page_count)
                for i in picks:
                    out.insert_pdf(src, from_page=i, to_page=i)
            finally:
                src.close()
        if out.page_count == 0:
            raise PdfError("Birleştirme sonucu boş.")
        out.save(out_path, garbage=3, deflate=True)
    finally:
        out.close()
    return out_path


@dataclass
class SplitPart:
    name: str
    indices: list[int]


def plan_split_by_ranges(page_count: int, expression: str) -> list[SplitPart]:
    """"1-3 | 4-6" ifadesini parçalara böler ('|' ayırıcı)."""
    parts: list[SplitPart] = []
    chunks = [p for p in expression.split("|") if p.strip()]
    for n, chunk in enumerate(chunks, start=1):
        indices = parse_page_ranges(chunk, page_count)
        parts.append(SplitPart(name=f"bolum_{n}", indices=indices))
    if not parts:
        raise ValueError("Geçerli bir aralık girilmedi.")
    return parts


def plan_split_every(page_count: int, step: int) -> list[SplitPart]:
    if step < 1:
        raise ValueError("Adım en az 1 olmalı.")
    parts: list[SplitPart] = []
    for n, start in enumerate(range(0, page_count, step), start=1):
        parts.append(SplitPart(name=f"bolum_{n}", indices=list(range(start, min(start + step, page_count)))))
    return parts


def plan_split_single(page_count: int) -> list[SplitPart]:
    return [SplitPart(name=f"sayfa_{i + 1}", indices=[i]) for i in range(page_count)]


def execute_split(
    doc: PdfDocument, parts: Sequence[SplitPart], out_dir: str, prefix: str
) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    with doc.lock:
        for part in parts:
            if not part.indices:
                continue
            out = fitz.open()
            try:
                for i in part.indices:
                    out.insert_pdf(doc.raw, from_page=i, to_page=i)
                path = os.path.join(out_dir, f"{prefix}_{part.name}.pdf")
                out.save(path, garbage=3, deflate=True)
                written.append(path)
            finally:
                out.close()
    return written
