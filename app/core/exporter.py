"""Dönüştürme ve dışa aktarma araçları: görsel, metin, sıkıştırma, güvenlik."""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Callable, Sequence

from .document import PdfDocument, PdfError, normalize_text
from .pdf_backend import (
    PDF_ENCRYPT_AES_256,
    PDF_ENCRYPT_NONE,
    PERM_ALL,
    PERM_ANNOTATE,
    PERM_COPY,
    PERM_MODIFY,
    PERM_PRINT,
    Matrix,
    fitz,
)

ProgressFn = Callable[[int, int], bool]
"""(tamamlanan, toplam) -> devam edilsin mi"""


IMAGE_FORMATS = {
    "PNG": ".png",
    "JPG": ".jpg",
    "TIFF": ".tif",
    "BMP": ".bmp",
    "WEBP": ".webp",
}


@dataclass
class ImageExportOptions:
    out_dir: str
    fmt: str = "PNG"
    dpi: int = 150
    pages: Sequence[int] | None = None
    prefix: str = "sayfa"
    jpeg_quality: int = 90
    grayscale: bool = False
    transparent: bool = False
    multipage_tiff: bool = False


def _pil_from_pixmap(pix) -> "object":
    from PIL import Image

    mode = "RGBA" if pix.alpha else "RGB"
    if pix.n - pix.alpha == 1:
        mode = "LA" if pix.alpha else "L"
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples)


def export_images(
    doc: PdfDocument, opts: ImageExportOptions, progress: ProgressFn | None = None
) -> list[str]:
    fmt = opts.fmt.upper()
    if fmt not in IMAGE_FORMATS:
        raise PdfError(f"Desteklenmeyen görsel biçimi: {opts.fmt}")

    os.makedirs(opts.out_dir, exist_ok=True)
    with doc.lock:
        total_pages = doc.raw.page_count
        targets = list(opts.pages) if opts.pages is not None else list(range(total_pages))
        targets = [i for i in targets if 0 <= i < total_pages]
        if not targets:
            raise PdfError("Dışa aktarılacak sayfa yok.")

        zoom = opts.dpi / 72.0
        matrix = Matrix(zoom, zoom)
        alpha = opts.transparent and fmt in ("PNG", "TIFF", "WEBP")
        colorspace = fitz.csGRAY if opts.grayscale else fitz.csRGB
        written: list[str] = []
        tiff_frames = []
        digits = max(3, len(str(total_pages)))

        for done, idx in enumerate(targets, start=1):
            page = doc.raw.load_page(idx)
            pix = page.get_pixmap(matrix=matrix, alpha=alpha, colorspace=colorspace)
            name = f"{opts.prefix}_{idx + 1:0{digits}d}{IMAGE_FORMATS[fmt]}"
            path = os.path.join(opts.out_dir, name)

            # MuPDF yalnızca PNG/JPEG ailesini yazabilir; TIFF, WEBP ve BMP
            # ile özel kaliteli JPEG için Pillow üzerinden gidilir.
            use_pillow = (
                fmt in ("TIFF", "WEBP", "BMP")
                or (fmt == "JPG" and opts.jpeg_quality != 90)
            )
            if use_pillow:
                img = _pil_from_pixmap(pix)
                if fmt == "TIFF" and opts.multipage_tiff:
                    tiff_frames.append(img)
                elif fmt == "JPG":
                    img.convert("RGB").save(path, "JPEG", quality=opts.jpeg_quality, optimize=True)
                    written.append(path)
                elif fmt == "WEBP":
                    img.save(path, "WEBP", quality=opts.jpeg_quality)
                    written.append(path)
                elif fmt == "BMP":
                    img.convert("RGB").save(path, "BMP")   # BMP saydamlık desteklemez
                    written.append(path)
                else:
                    img.save(path, "TIFF", compression="tiff_deflate")
                    written.append(path)
            else:
                pix.save(path)
                written.append(path)

            if progress and not progress(done, len(targets)):
                break

        if fmt == "TIFF" and opts.multipage_tiff and tiff_frames:
            path = os.path.join(opts.out_dir, f"{opts.prefix}.tif")
            tiff_frames[0].save(
                path,
                "TIFF",
                save_all=True,
                append_images=tiff_frames[1:],
                compression="tiff_deflate",
            )
            written = [path]

    return written


def export_text(doc: PdfDocument, out_path: str, pages: Sequence[int] | None = None) -> str:
    with doc.lock:
        total = doc.raw.page_count
        targets = list(pages) if pages is not None else list(range(total))
        chunks = []
        for i in targets:
            if 0 <= i < total:
                body = normalize_text(doc.raw.load_page(i).get_text("text"))
                chunks.append(f"--- Sayfa {i + 1} ---\n{body}")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(chunks))
    return out_path


def export_html(doc: PdfDocument, out_path: str, pages: Sequence[int] | None = None) -> str:
    with doc.lock:
        total = doc.raw.page_count
        targets = [i for i in (pages if pages is not None else range(total)) if 0 <= i < total]
        body = "\n".join(doc.raw.load_page(i).get_text("html") for i in targets)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{os.path.basename(out_path)}</title></head><body>{body}</body></html>"
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out_path


# ----------------------------------------------------------------------
# Sıkıştırma
# ----------------------------------------------------------------------
@dataclass
class CompressOptions:
    image_dpi: int = 150          # 0 => görselleri yeniden örnekleme
    jpeg_quality: int = 70
    downsample_images: bool = True
    subset_fonts: bool = True
    remove_metadata: bool = False
    garbage: int = 4


@dataclass
class CompressResult:
    out_path: str
    before: int
    after: int

    @property
    def saved_ratio(self) -> float:
        return 0.0 if self.before <= 0 else max(0.0, 1.0 - self.after / self.before)


def compress(doc: PdfDocument, out_path: str, opts: CompressOptions) -> CompressResult:
    """Belgeyi optimize ederek yeni bir dosyaya yazar."""
    original = doc.to_bytes(garbage=0, deflate=False)
    work = fitz.open(stream=original, filetype="pdf")
    try:
        if opts.downsample_images and hasattr(work, "rewrite_images"):
            try:
                work.rewrite_images(
                    dpi_threshold=max(opts.image_dpi + 20, 72) if opts.image_dpi else None,
                    dpi_target=opts.image_dpi or 0,
                    quality=opts.jpeg_quality,
                    lossy=True,
                    lossless=True,
                )
            except Exception:  # noqa: BLE001 - bozuk görsellerde sıkıştırmayı atla
                pass

        if opts.subset_fonts:
            try:
                work.subset_fonts(fallback=False)
            except Exception:  # noqa: BLE001
                pass

        if opts.remove_metadata:
            work.set_metadata({})
            work.del_xml_metadata()

        work.save(
            out_path,
            garbage=opts.garbage,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
            use_objstms=1,
        )
    finally:
        work.close()

    return CompressResult(out_path=out_path, before=len(original), after=os.path.getsize(out_path))


# ----------------------------------------------------------------------
# Güvenlik
# ----------------------------------------------------------------------
@dataclass
class SecurityOptions:
    user_password: str = ""
    owner_password: str = ""
    allow_print: bool = True
    allow_copy: bool = True
    allow_modify: bool = False
    allow_annotate: bool = True

    def permissions(self) -> int:
        perms = 0
        if self.allow_print:
            perms |= PERM_PRINT
        if self.allow_copy:
            perms |= PERM_COPY
        if self.allow_modify:
            perms |= PERM_MODIFY
        if self.allow_annotate:
            perms |= PERM_ANNOTATE
        return perms or PERM_PRINT


def encrypt(doc: PdfDocument, out_path: str, opts: SecurityOptions) -> str:
    if not opts.user_password and not opts.owner_password:
        raise PdfError("En az bir parola girilmelidir.")
    with doc.lock:
        doc.raw.save(
            out_path,
            garbage=3,
            deflate=True,
            encryption=PDF_ENCRYPT_AES_256,
            owner_pw=opts.owner_password or opts.user_password,
            user_pw=opts.user_password,
            permissions=opts.permissions(),
        )
    return out_path


def decrypt(doc: PdfDocument, out_path: str) -> str:
    """Açık (parolası çözülmüş) belgeyi şifresiz kaydeder."""
    with doc.lock:
        doc.raw.save(
            out_path,
            garbage=3,
            deflate=True,
            encryption=PDF_ENCRYPT_NONE,
            permissions=PERM_ALL,
        )
    return out_path


def describe_permissions(doc: PdfDocument) -> dict[str, bool]:
    with doc.lock:
        perms = doc.raw.permissions
    return {
        "Yazdırma": bool(perms & PERM_PRINT),
        "Kopyalama": bool(perms & PERM_COPY),
        "Değiştirme": bool(perms & PERM_MODIFY),
        "Açıklama ekleme": bool(perms & PERM_ANNOTATE),
    }


# ----------------------------------------------------------------------
# Görselden PDF
# ----------------------------------------------------------------------
def images_to_pdf(image_paths: Sequence[str], out_path: str, page_size: str = "fit") -> str:
    """Görselleri tek bir PDF'e dönüştürür."""
    if not image_paths:
        raise PdfError("Görsel seçilmedi.")
    out = fitz.open()
    try:
        for path in image_paths:
            with open(path, "rb") as fh:
                data = fh.read()
            img_doc = fitz.open(stream=data, filetype=os.path.splitext(path)[1].lstrip("."))
            try:
                pdf_bytes = img_doc.convert_to_pdf()
            finally:
                img_doc.close()
            src = fitz.open(stream=pdf_bytes, filetype="pdf")
            try:
                out.insert_pdf(src)
            finally:
                src.close()
        out.save(out_path, garbage=3, deflate=True)
    finally:
        out.close()
    return out_path
