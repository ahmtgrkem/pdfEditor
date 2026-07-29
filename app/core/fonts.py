"""Metin ekleme araçları için font çözümleme.

PDF'in dahili (base-14) fontları Türkçe karakterleri (ş, ğ, ı, İ) taşımaz.
Bu yüzden metin ve filigran araçları sistemdeki gerçek TrueType dosyalarını
gömer. Font bulunamazsa base-14'e düşülür.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache

# Kullanıcıya gösterilen ad -> (regular, bold, italic, bolditalic) dosya adları
_WINDOWS_FAMILIES: dict[str, tuple[str, str, str, str]] = {
    "Arial": ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "Calibri": ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "Courier New": ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
}

# Base-14 yedekleri (dosya bulunamazsa)
_BASE14 = {
    "Arial": ("helv", "hebo", "heit", "hebi"),
    "Calibri": ("helv", "hebo", "heit", "hebi"),
    "Segoe UI": ("helv", "hebo", "heit", "hebi"),
    "Verdana": ("helv", "hebo", "heit", "hebi"),
    "Tahoma": ("helv", "hebo", "heit", "hebi"),
    "Times New Roman": ("tiro", "tibo", "tiit", "tibi"),
    "Georgia": ("tiro", "tibo", "tiit", "tibi"),
    "Courier New": ("cour", "cobo", "coit", "cobi"),
    "Consolas": ("cour", "cobo", "coit", "cobi"),
}

DEFAULT_FAMILY = "Arial"


def _font_dirs() -> list[str]:
    dirs: list[str] = []
    if sys.platform == "win32":
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:  # pragma: no cover - geliştirme kolaylığı
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return [d for d in dirs if os.path.isdir(d)]


@lru_cache(maxsize=None)
def _find_file(filename: str) -> str | None:
    for d in _font_dirs():
        candidate = os.path.join(d, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


def available_families() -> list[str]:
    """Sistemde gerçekten bulunan aileler (yoksa yine de listelenir)."""
    found = [name for name, files in _WINDOWS_FAMILIES.items() if _find_file(files[0])]
    return found or list(_WINDOWS_FAMILIES)


def resolve(family: str, bold: bool = False, italic: bool = False) -> tuple[str, str | None]:
    """(fontname, fontfile) çiftini döndürür.

    ``fontfile`` None ise PyMuPDF'in dahili base-14 fontu kullanılır.
    """
    family = family if family in _WINDOWS_FAMILIES else DEFAULT_FAMILY
    idx = (1 if bold else 0) + (2 if italic else 0)
    files = _WINDOWS_FAMILIES[family]
    path = _find_file(files[idx]) or _find_file(files[0])
    if path:
        # PyMuPDF gömülü font için benzersiz, ASCII bir takma ad ister.
        alias = "F" + os.path.splitext(os.path.basename(path))[0].replace(" ", "")
        return alias, path
    return _BASE14.get(family, _BASE14[DEFAULT_FAMILY])[idx], None


#: Font metriği okunamazsa kullanılacak makul varsayılanlar (em birimi).
_FALLBACK_ASCENDER = 0.90
_FALLBACK_DESCENDER = -0.21


@lru_cache(maxsize=None)
def metrics(family: str, bold: bool = False, italic: bool = False) -> tuple[float, float]:
    """Fontun ``(ascender, descender)`` oranlarını em birimiyle döndürür.

    Taban çizgisi (baseline) hesabı için gereklidir::

        baseline_y = kutu_üst_y + ascender * fontsize
    """
    fontname, fontfile = resolve(family, bold, italic)
    try:
        from .pdf_backend import fitz

        font = fitz.Font(fontname=None if fontfile else fontname, fontfile=fontfile)
        ascender = float(font.ascender)
        descender = float(font.descender)
    except Exception:  # noqa: BLE001 - font okunamazsa varsayılana düş
        return _FALLBACK_ASCENDER, _FALLBACK_DESCENDER
    if not 0.1 < ascender < 2.0:
        ascender = _FALLBACK_ASCENDER
    if not -1.0 < descender <= 0.0:
        descender = _FALLBACK_DESCENDER
    return ascender, descender


def ascender(family: str, bold: bool = False, italic: bool = False) -> float:
    """Fontun üst çıkıntı (ascent) oranı — ``fontsize`` ile çarpılarak kullanılır."""
    return metrics(family, bold, italic)[0]
