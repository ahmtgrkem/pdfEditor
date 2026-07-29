"""PyMuPDF için ince bir uyumluluk katmanı.

PyMuPDF 1.24 -> 1.28 arasında modül adı ``fitz`` yerine ``pymupdf`` oldu.
Uygulamanın geri kalanı yalnızca buradan import eder.
"""
from __future__ import annotations

try:  # PyMuPDF >= 1.24 önerilen isim
    import pymupdf as fitz
except ImportError:  # pragma: no cover - eski sürümler
    import fitz  # type: ignore

Rect = fitz.Rect
Point = fitz.Point
Matrix = fitz.Matrix
Quad = fitz.Quad
Identity = fitz.Identity

PDF_ENCRYPT_KEEP = fitz.PDF_ENCRYPT_KEEP
PDF_ENCRYPT_NONE = fitz.PDF_ENCRYPT_NONE
PDF_ENCRYPT_AES_256 = fitz.PDF_ENCRYPT_AES_256

# Şifreleme izin bayrakları
PERM_PRINT = fitz.PDF_PERM_PRINT
PERM_MODIFY = fitz.PDF_PERM_MODIFY
PERM_COPY = fitz.PDF_PERM_COPY
PERM_ANNOTATE = fitz.PDF_PERM_ANNOTATE
PERM_ALL = (
    fitz.PDF_PERM_PRINT
    | fitz.PDF_PERM_MODIFY
    | fitz.PDF_PERM_COPY
    | fitz.PDF_PERM_ANNOTATE
    | fitz.PDF_PERM_FORM
    | fitz.PDF_PERM_ACCESSIBILITY
    | fitz.PDF_PERM_ASSEMBLE
    | fitz.PDF_PERM_PRINT_HQ
)


def version() -> str:
    return getattr(fitz, "__doc__", "PyMuPDF").splitlines()[0]


__all__ = [
    "fitz",
    "Rect",
    "Point",
    "Matrix",
    "Quad",
    "Identity",
    "PDF_ENCRYPT_KEEP",
    "PDF_ENCRYPT_NONE",
    "PDF_ENCRYPT_AES_256",
    "PERM_PRINT",
    "PERM_MODIFY",
    "PERM_COPY",
    "PERM_ANNOTATE",
    "PERM_ALL",
    "version",
]
