"""PDF belge modeli.

``PdfDocument`` PyMuPDF ``Document`` nesnesini sarmalar ve uygulamanın geri
kalanına thread-safe, Qt'den bağımsız bir arayüz sunar.

Tasarım notları
---------------
* Tüm PyMuPDF çağrıları tek bir ``RLock`` altında serileştirilir; MuPDF
  belge nesneleri thread-safe değildir ve arka plan render iş parçacıkları
  aynı belgeye erişir.
* Sayfa döndürmesi (``/Rotate``) olan belgelerde PyMuPDF metin/arama
  koordinatlarını *görsel* uzayda döndürür, fakat annotation'lar
  *döndürülmemiş* uzayda eklenmelidir. Dönüşüm ``to_pdf_rect`` /
  ``to_visual_rect`` yardımcılarıyla merkezî olarak yapılır.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Sequence

from .pdf_backend import Matrix, Point, Quad, Rect, fitz


class PdfError(RuntimeError):
    """Belge işlemleri için genel hata tipi."""


class PasswordRequired(PdfError):
    """Şifreli belge; parola gerekiyor ya da parola hatalı."""


@dataclass(frozen=True)
class RenderedPage:
    """Ham RGB piksel verisi (QImage'a sıfır kopyayla verilebilir)."""

    index: int
    width: int
    height: int
    stride: int
    samples: bytes
    zoom: float


@dataclass(frozen=True)
class TocEntry:
    level: int
    title: str
    page: int  # 1 tabanlı; 0 => hedef yok


#: Gömülü TTF yazı tiplerinde boşluk ve tire glifleri, ters cmap eşlemesi
#: yüzünden bölünmez boşluk (U+00A0) / yumuşak tire (U+00AD) olarak çıkarılır.
#: Kopyalama, metin dışa aktarma ve arama bağlamlarında düz karşılıkları kullanılır.
_TEXT_REPLACEMENTS = {
    " ": " ",   # bölünmez boşluk
    "­": "-",   # yumuşak tire
    "‐": "-",   # tire
    "‑": "-",   # bölünmez tire
    "ﬁ": "fi",  # ligatürler
    "ﬂ": "fl",
}


def normalize_text(text: str) -> str:
    """Çıkarılan metni panoya/dosyaya uygun düz karakterlere çevirir."""
    if not text:
        return text
    for src, dst in _TEXT_REPLACEMENTS.items():
        if src in text:
            text = text.replace(src, dst)
    return text


#: Dosya imzası -> MuPDF biçim adı. **Yalnızca imzası tutan** biçim denenir:
#: rastgele baytları sırayla her ayrıştırıcıya vermek MuPDF'i çökertiyor.
_MAGIC = (
    (b"%PDF-", ("pdf",)),
    (b"\x89PNG\r\n\x1a\n", ("png",)),
    (b"\xff\xd8\xff", ("jpg",)),
    (b"GIF87a", ("gif",)),
    (b"GIF89a", ("gif",)),
    (b"BM", ("bmp",)),
    (b"II*\x00", ("tiff",)),
    (b"MM\x00*", ("tiff",)),
    (b"PK\x03\x04", ("epub", "xps", "cbz")),   # zip tabanlı biçimler
    (b"<?xml", ("svg",)),
    (b"<svg", ("svg",)),
    (b"P1", ("pnm",)), (b"P2", ("pnm",)), (b"P3", ("pnm",)),
    (b"P4", ("pnm",)), (b"P5", ("pnm",)), (b"P6", ("pnm",)),
)


def _sniff(data: bytes) -> tuple[str, ...]:
    """İçeriğin imzasına göre denenecek biçimler."""
    bas = data[:16]
    for imza, turler in _MAGIC:
        if bas.startswith(imza):
            return turler
    return ()


def _as_pdf(doc: fitz.Document) -> tuple[fitz.Document, bool]:
    """PDF olmayan belgeyi PDF'e çevirir -> (belge, çevrildi mi).

    Görsel/XPS/EPUB gibi dosyalar PDF'e çevrilmeden düzenlenemez; çevrildiğini
    bildirmek önemlidir, çünkü artık kaynak dosyanın üzerine yazılmamalıdır.
    """
    if doc.is_pdf:
        return doc, False
    try:
        veri = doc.convert_to_pdf()
    except Exception:  # noqa: BLE001 - çevrilemiyorsa olduğu gibi bırak
        return doc, False
    finally:
        pass
    yeni = fitz.open(stream=veri, filetype="pdf")
    doc.close()
    return yeni, True


def open_tolerant(path: str) -> tuple[fitz.Document, bool]:
    """Bozuk/etiketi yanlış dosyaları da açmayı dener.

    Sırasıyla: (1) olağan açılış, (2) PDF olduğunu varsayarak baytlardan,
    (3) ``%PDF`` başlığından önceki çöpü atlayarak (indirme artığı ya da
    e-posta üstbilgisi eklenmiş dosyalar), (4) MuPDF'in desteklediği diğer
    biçimler. Döndürdüğü ikinci değer, dosyanın onarılarak açıldığını söyler.

    Amaç: kullanıcının açamadığı bir dosya kalmasın. Onarım MuPDF'in kendi
    kurtarma yolunu kullanır; içerik kaybı olabileceği çağırana bildirilir.
    """
    hatalar: list[str] = []
    try:
        doc = fitz.open(path)
        if doc.page_count > 0 or doc.needs_pass:
            onarildi = bool(getattr(doc, "is_repaired", False))
            doc, cevrildi = _as_pdf(doc)
            return doc, onarildi or cevrildi
        doc.close()
        hatalar.append("belge boş")
    except Exception as exc:  # noqa: BLE001 - kütüphane geniş hata atar
        hatalar.append(str(exc))

    try:
        with open(path, "rb") as dosya:
            veri = dosya.read()
    except OSError as exc:
        raise PdfError(f"Dosya okunamadı: {exc}") from exc
    if not veri:
        raise PdfError("Dosya boş.")

    # (2)/(3): PDF olarak zorla; gerekirse başlıktan itibaren
    adaylar = [veri]
    ofset = veri.find(b"%PDF-")
    if ofset > 0:
        adaylar.append(veri[ofset:])
    for parca in adaylar:
        try:
            doc = fitz.open(stream=parca, filetype="pdf")
            if doc.page_count > 0 or doc.needs_pass:
                return doc, True
            doc.close()
        except Exception as exc:  # noqa: BLE001
            hatalar.append(str(exc))

    # (4): uzantısı yanlış olabilir — imzası tutan biçimleri dene
    for tur in _sniff(veri):
        if tur == "pdf":
            continue                    # (2)'de zaten denendi
        try:
            doc = fitz.open(stream=veri, filetype=tur)
            if doc.page_count > 0:
                return _as_pdf(doc)[0], True
            doc.close()
        except Exception:  # noqa: BLE001 - biçim tutmadı, sıradaki
            continue

    raise PdfError(
        "Dosya açılamadı; tanınan bir belge biçimi değil.\n"
        + "\n".join(dict.fromkeys(hatalar[:3]))
    )


class PdfDocument:
    """Açık bir PDF belgesini temsil eder."""

    def __init__(self) -> None:
        self._doc: fitz.Document | None = None
        self._lock = threading.RLock()
        self._path: str | None = None
        self._password: str | None = None
        self._dirty = False
        #: Dosya onarılarak açıldı mı (bozuk PDF / yanlış uzantı)
        self._repaired = False
        # Yapısal değişiklikte (sayfa ekleme/silme/sıralama) artar -> tüm önbellek düşer
        self._generation = 0
        # Sayfa içeriği değişince artar -> yalnızca o sayfanın önbelleği düşer
        self._page_revs: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Yaşam döngüsü
    # ------------------------------------------------------------------
    @property
    def lock(self) -> threading.RLock:
        return self._lock

    @property
    def raw(self) -> fitz.Document:
        if self._doc is None:
            raise PdfError("Açık belge yok.")
        return self._doc

    @property
    def is_open(self) -> bool:
        return self._doc is not None and not self._doc.is_closed

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def was_repaired(self) -> bool:
        """Dosya onarılarak/biçimi tahmin edilerek açıldıysa ``True``."""
        return self._repaired

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def display_name(self) -> str:
        if self._path:
            return os.path.basename(self._path)
        return "Adsız.pdf"

    def mark_dirty(self, page_index: int | None = None, structural: bool = False) -> None:
        """Belgeyi değişmiş olarak işaretler ve ilgili önbelleği geçersizler.

        ``page_index`` verilirse yalnızca o sayfanın render'ı düşer;
        ``structural=True`` ise (sayfa ekleme/silme/sıralama) tüm önbellek düşer.
        """
        with self._lock:
            self._dirty = True
            self._generation += 1
            if structural or page_index is None:
                self._page_revs.clear()
            else:
                self._page_revs[page_index] = self._page_revs.get(page_index, 0) + 1

    def mark_clean(self) -> None:
        with self._lock:
            self._dirty = False

    def open(self, path: str, password: str | None = None) -> None:
        """Diskten belge açar. Şifreliyse :class:`PasswordRequired` fırlatır."""
        with self._lock:
            doc, onarildi = open_tolerant(path)

            if doc.needs_pass:
                if not password or not doc.authenticate(password):
                    doc.close()
                    raise PasswordRequired("Belge parola korumalı.")

            self.close()
            self._doc = doc
            self._repaired = onarildi
            # PDF olmayan bir kaynak PDF'e çevrildiyse yol taşınmaz: "Kaydet"
            # kullanıcının görselinin/EPUB'ının üzerine PDF yazmamalı.
            cevrildi = onarildi and not path.lower().endswith(".pdf")
            self._path = None if cevrildi else path
            self._password = password
            self._dirty = cevrildi
            self._generation += 1
            self._page_revs.clear()

    def open_stream(self, data: bytes, path: str | None = None,
                    detach: bool = False) -> None:
        """Bellek içindeki PDF baytlarından belge açar (undo/redo için).

        Varsayılan olarak mevcut yol korunur: geri al/yinele aynı dosya
        üzerinde çalışır. ``detach=True`` yolu **siler** — içerik artık
        diskteki dosyanın karşılığı değildir (ör. XFA'dan üretilmiş sürüm) ve
        "Kaydet" özgün dosyanın üzerine yazmamalıdır.
        """
        with self._lock:
            doc = fitz.open(stream=data, filetype="pdf")
            self.close(keep_path=True)
            self._doc = doc
            if detach:
                self._path = None
                self._password = None
            elif path is not None:
                self._path = path
            self._generation += 1
            self._page_revs.clear()

    def new_empty(self, width: float = 595.0, height: float = 842.0) -> None:
        """Boş (tek A4 sayfalı) yeni belge oluşturur."""
        with self._lock:
            doc = fitz.open()
            doc.new_page(width=width, height=height)
            self.close()
            self._doc = doc
            self._path = None
            self._password = None
            self._dirty = True
            self._generation += 1
            self._page_revs.clear()

    def close(self, keep_path: bool = False) -> None:
        with self._lock:
            if self._doc is not None and not self._doc.is_closed:
                self._doc.close()
            self._doc = None
            if not keep_path:
                self._path = None
                self._password = None
                self._dirty = False
                self._repaired = False

    # ------------------------------------------------------------------
    # Sayfa bilgileri
    # ------------------------------------------------------------------
    @property
    def page_count(self) -> int:
        with self._lock:
            return 0 if not self.is_open else self._doc.page_count

    def page_size(self, index: int) -> tuple[float, float]:
        """Görsel (döndürme uygulanmış) sayfa boyutu, punto cinsinden."""
        with self._lock:
            page = self.raw.load_page(index)
            r = page.rect
            return r.width, r.height


    def metadata(self) -> dict:
        with self._lock:
            return dict(self.raw.metadata or {})

    def set_metadata(self, meta: dict) -> None:
        with self._lock:
            self.raw.set_metadata(meta)
            self.mark_dirty()

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, index: int, zoom: float, alpha: bool = False) -> RenderedPage:
        """Sayfayı ``zoom`` katsayısıyla RGB(A) piksellere çevirir."""
        with self._lock:
            page = self.raw.load_page(index)
            pix = page.get_pixmap(matrix=Matrix(zoom, zoom), alpha=alpha)
            return RenderedPage(
                index=index,
                width=pix.width,
                height=pix.height,
                stride=pix.stride,
                samples=pix.samples,
                zoom=zoom,
            )

    def render_dpi(self, index: int, dpi: int, alpha: bool = False) -> RenderedPage:
        return self.render(index, dpi / 72.0, alpha=alpha)

    # ------------------------------------------------------------------
    # Metin / arama
    # ------------------------------------------------------------------
    def page_text(self, index: int) -> str:
        with self._lock:
            return normalize_text(self.raw.load_page(index).get_text("text"))

    def words(self, index: int) -> list[tuple[float, float, float, float, str]]:
        """Sayfadaki kelimeler ve görsel koordinatlı kutuları."""
        with self._lock:
            page = self.raw.load_page(index)
            return [
                (w[0], w[1], w[2], w[3], normalize_text(w[4]))
                for w in page.get_text("words")
            ]

    def search_page(self, index: int, needle: str) -> list[tuple[float, float, float, float]]:
        if not needle:
            return []
        with self._lock:
            page = self.raw.load_page(index)
            return [tuple(r) for r in page.search_for(needle)]

    def selection_quads(
        self, index: int, visual_rect: tuple[float, float, float, float]
    ) -> list[Quad]:
        """Verilen dikdörtgenle kesişen kelimelerin quad'larını döndürür.

        Metin işaretleme (highlight/underline/strikeout) araçları için
        kullanılır; tam metin seçimi UI'ı gerektirmeden güvenilir sonuç verir.
        """
        sel = Rect(*visual_rect)
        if sel.is_empty:
            return []
        quads: list[Quad] = []
        with self._lock:
            page = self.raw.load_page(index)
            for w in page.get_text("words"):
                wr = Rect(w[0], w[1], w[2], w[3])
                inter = wr & sel
                if inter.is_empty:
                    continue
                # Kelimenin en az %35'i seçim içindeyse dahil et
                if wr.get_area() > 0 and inter.get_area() / wr.get_area() >= 0.35:
                    quads.append(wr.quad)
        return quads

    # ------------------------------------------------------------------
    # İçindekiler
    # ------------------------------------------------------------------
    def toc(self) -> list[TocEntry]:
        with self._lock:
            raw = self.raw.get_toc(simple=True) or []
        return [TocEntry(level=int(e[0]), title=str(e[1]), page=int(e[2])) for e in raw]

    def set_toc(self, entries: Sequence[TocEntry]) -> None:
        with self._lock:
            self.raw.set_toc([[e.level, e.title, e.page] for e in entries])
            self.mark_dirty()

    # ------------------------------------------------------------------
    # Koordinat dönüşümleri
    # ------------------------------------------------------------------
    def to_pdf_rect(self, index: int, visual: Rect) -> Rect:
        """Görsel koordinatı annotation eklemek için ham PDF uzayına çevirir."""
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return Rect(visual)
            return Rect(visual) * page.derotation_matrix

    def to_view_rect(self, index: int, pdf: Rect) -> Rect:
        """Ham PDF koordinatını görsel (döndürülmüş) uzaya çevirir.

        :meth:`to_pdf_rect` işleminin tersidir. Annotation/widget
        dikdörtgenleri PDF uzayında saklanır ve sayfa döndürmesinden
        etkilenmez; ekranda doğru yerde göstermek için bu dönüşüm gerekir.
        """
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return Rect(pdf)
            return Rect(pdf) * page.rotation_matrix

    def to_pdf_point(self, index: int, visual: Point) -> Point:
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return Point(visual)
            return Point(visual) * page.derotation_matrix

    def to_pdf_quad(self, index: int, visual: Quad) -> Quad:
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return visual
            return visual * page.derotation_matrix

    def to_visual_rect(self, index: int, pdf_rect: Rect) -> Rect:
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return Rect(pdf_rect)
            return Rect(pdf_rect) * page.rotation_matrix

    def to_visual_point(self, index: int, pdf_point: Point) -> Point:
        with self._lock:
            page = self.raw.load_page(index)
            if page.rotation == 0:
                return Point(pdf_point)
            return Point(pdf_point) * page.rotation_matrix

    # ------------------------------------------------------------------
    # Kaydetme / anlık görüntü
    # ------------------------------------------------------------------
    def snapshot(self) -> bytes:
        """Undo yığını için hızlı bellek anlık görüntüsü."""
        with self._lock:
            return self.raw.tobytes(garbage=0, deflate=False, clean=False)

    def save(
        self,
        path: str | None = None,
        *,
        garbage: int = 3,
        deflate: bool = True,
        clean: bool = False,
        encryption: int | None = None,
        owner_pw: str | None = None,
        user_pw: str | None = None,
        permissions: int | None = None,
    ) -> str:
        """Belgeyi kaydeder ve nihai yolu döndürür."""
        with self._lock:
            target = path or self._path
            if not target:
                raise PdfError("Kayıt yolu belirtilmedi.")

            kwargs: dict = {"garbage": garbage, "deflate": deflate, "clean": clean}
            if encryption is not None:
                kwargs["encryption"] = encryption
                kwargs["owner_pw"] = owner_pw or ""
                kwargs["user_pw"] = user_pw or ""
                if permissions is not None:
                    kwargs["permissions"] = permissions

            same_file = self._path is not None and os.path.abspath(target) == os.path.abspath(
                self._path
            )
            if same_file:
                # Aynı dosyanın üzerine yazarken MuPDF geçici dosya ister.
                data = self.raw.tobytes(**kwargs)
                with open(target, "wb") as fh:
                    fh.write(data)
            else:
                self.raw.save(target, **kwargs)

            self._path = target
            self._dirty = False
            return target

    def to_bytes(self, **kwargs) -> bytes:
        with self._lock:
            return self.raw.tobytes(**kwargs)

