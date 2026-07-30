"""Metin araçları için font çözümleme.

PDF'in dahili (base-14) fontları Türkçe karakterleri (ş, ğ, ı, İ) taşımaz;
bu yüzden metin ve filigran araçları sistemdeki gerçek font dosyalarını gömer.

Neden sabit liste değil
-----------------------
Önceden burada elle yazılmış dokuz aile vardı. Belgede başka bir yazı tipi
geçtiğinde (kurumsal formlarda kural bu) düzenlenen metin sessizce Arial'e
dönüşüyordu. Artık sistemdeki **bütün** font dosyaları taranır: her dosyanın
``name`` tablosundan aile adı ve stili okunur, aile -> (kalın, yatık) -> dosya
indeksi kurulur. Böylece belgedeki yazı tipi kuruluysa aynısıyla yazılır.

Tarama tembeldir (ilk kullanımda) ve dosyaların yalnızca başlık + ``name``
tablosu okunur; tüm font dosyalarını belleğe almak gereksiz.
"""
from __future__ import annotations

import os
import struct
import sys
from functools import lru_cache

DEFAULT_FAMILY = "Arial"

#: Font dosyası uzantıları (sfnt tabanlı olanlar)
_EXTENSIONS = (".ttf", ".otf", ".ttc", ".otc")

#: ``name`` tablosunda aile/stil adı taşıyan kayıtlar
_NAME_FAMILY = 1
_NAME_SUBFAMILY = 2
_NAME_TYPO_FAMILY = 16
_NAME_TYPO_SUBFAMILY = 17

#: Gömülü font adlarındaki stil ekleri (eşleme sırasında atılır)
_STYLE_WORDS = frozenset({
    # "book"/"text" bilinçli olarak yok: "Book Antiqua" ve "Segoe UI Text"
    # gerçek aile adları, stil eki değil.
    "regular", "normal", "roman", "plain",
    "bold", "semibold", "demibold", "demi", "medium", "light", "extralight",
    "ultralight", "thin", "black", "heavy", "extrabold", "ultrabold",
    "italic", "oblique", "bolditalic", "boldoblique", "it",
    "mt", "ms", "ps", "psmt", "std", "pro", "condensed", "cond",
})

#: Base-14 yedeği: kurulu font bulunamazsa yazı tipinin karakterine göre
_BASE14 = {
    "serif": ("tiro", "tibo", "tiit", "tibi"),
    "mono": ("cour", "cobo", "coit", "cobi"),
    "sans": ("helv", "hebo", "heit", "hebi"),
}

#: PDF base-14 adları -> yaygın sistem karşılıkları
_ALIASES = {
    "helvetica": "Arial",
    "arialmt": "Arial",
    "arial": "Arial",
    "timesnewromanpsmt": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "times": "Times New Roman",
    "couriernew": "Courier New",
    "courier": "Courier New",
    "symbol": "Segoe UI Symbol",
    "zapfdingbats": "Wingdings",
}


def _font_dirs() -> list[str]:
    dirs: list[str] = []
    if sys.platform == "win32":
        win = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":  # pragma: no cover - geliştirme kolaylığı
        dirs += ["/System/Library/Fonts", "/Library/Fonts",
                 os.path.expanduser("~/Library/Fonts")]
    else:  # pragma: no cover - geliştirme kolaylığı
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dirs if os.path.isdir(d)]


# ======================================================================
# sfnt ``name`` tablosu okuma
# ======================================================================
def _decode(raw: bytes, platform_id: int) -> str:
    """``name`` kaydını çözer; Windows kayıtları UTF-16BE'dir."""
    try:
        if platform_id == 3:
            return raw.decode("utf-16-be", "ignore")
        return raw.decode("latin-1", "ignore")
    except Exception:  # noqa: BLE001 - bozuk kayıt
        return ""


def _name_score(platform_id: int, language_id: int) -> int:
    """Kayıt tercih puanı — yüksek olan kazanır.

    Dil gözetilmezse dosyadaki son çeviri kalıyor: ``arialbd.ttf``ten
    İngilizce "Bold" yerine İspanyolca "Negreta" okunuyor ve stil tespiti
    çöküyordu.
    """
    if platform_id == 3:
        return 4 if language_id == 0x0409 else 3
    if platform_id == 1:
        return 2 if language_id == 0 else 1
    return 0


def _read_names(fh, offset: int) -> dict[int, str]:
    """Tek bir sfnt fontunun ``name`` kayıtlarını okur (İngilizce tercihli)."""
    fh.seek(offset)
    head = fh.read(12)
    if len(head) < 12:
        return {}
    tablo_sayisi = struct.unpack(">H", head[4:6])[0]
    dizin = fh.read(16 * tablo_sayisi)
    name_offset = name_length = 0
    for i in range(tablo_sayisi):
        kayit = dizin[i * 16:(i + 1) * 16]
        if len(kayit) < 16:
            break
        if kayit[:4] == b"name":
            name_offset, name_length = struct.unpack(">II", kayit[8:16])
            break
    if not name_offset or not name_length:
        return {}

    fh.seek(name_offset)
    govde = fh.read(name_length)
    if len(govde) < 6:
        return {}
    kayit_sayisi, depo = struct.unpack(">HH", govde[2:6])

    sonuc: dict[int, str] = {}
    oncelik: dict[int, int] = {}
    for i in range(kayit_sayisi):
        bas = 6 + i * 12
        alan = govde[bas:bas + 12]
        if len(alan) < 12:
            break
        platform, _enc, dil, ad_id, uzunluk, ofset = struct.unpack(">HHHHHH", alan)
        if ad_id not in (_NAME_FAMILY, _NAME_SUBFAMILY,
                         _NAME_TYPO_FAMILY, _NAME_TYPO_SUBFAMILY):
            continue
        puan = _name_score(platform, dil)
        if puan <= oncelik.get(ad_id, 0):
            continue
        ham = govde[depo + ofset:depo + ofset + uzunluk]
        metin = _decode(ham, platform).strip()
        if metin:
            sonuc[ad_id] = metin
            oncelik[ad_id] = puan
    return sonuc


def _font_offsets(fh) -> list[int]:
    """Dosyadaki sfnt fontlarının ofsetleri (``.ttc`` birden çok taşır)."""
    fh.seek(0)
    imza = fh.read(4)
    if imza == b"ttcf":
        fh.seek(8)
        (sayi,) = struct.unpack(">I", fh.read(4))
        if not 0 < sayi < 256:
            return []
        return list(struct.unpack(f">{sayi}I", fh.read(4 * sayi)))
    if imza in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        return [0]
    return []


def _style_flags(subfamily: str) -> tuple[bool, bool]:
    """``"Bold Italic"`` -> ``(True, True)``.

    Kelime kelime bakılır: ``Semibold``/``Demibold`` ayrı bir ağırlıktır ve
    ailenin kalın yüzü değildir; ``"bold" in metin`` demek Segoe UI'ın kalın
    yüzünü Semibold dosyasına bağlıyordu.
    """
    kelimeler = subfamily.replace("-", " ").lower().split()
    kalin = "bold" in kelimeler
    yatik = "italic" in kelimeler or "oblique" in kelimeler
    return kalin, yatik


# ======================================================================
# Font indeksi
# ======================================================================
@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, dict[tuple[bool, bool], str]], dict[str, str]]:
    """``(aile_kucuk -> {(kalin, yatik): dosya}, aile_kucuk -> gorunen_ad)``."""
    aileler: dict[str, dict[tuple[bool, bool], str]] = {}
    adlar: dict[str, str] = {}

    for klasor in _font_dirs():
        try:
            girdiler = sorted(os.listdir(klasor))
        except OSError:
            continue
        for dosya in girdiler:
            if not dosya.lower().endswith(_EXTENSIONS):
                continue
            yol = os.path.join(klasor, dosya)
            try:
                with open(yol, "rb") as fh:
                    for ofset in _font_offsets(fh):
                        isimler = _read_names(fh, ofset)
                        # ID1 önce: Windows/Word font listesinde görünen ad
                        # budur. ID16 ("tercih edilen aile") Arial Narrow'u
                        # Arial'in içine katlıyor, kullanıcı aradığını bulamıyor.
                        aile = (isimler.get(_NAME_FAMILY)
                                or isimler.get(_NAME_TYPO_FAMILY) or "").strip()
                        if not aile:
                            continue
                        alt = (isimler.get(_NAME_SUBFAMILY)
                               or isimler.get(_NAME_TYPO_SUBFAMILY) or "")
                        anahtar = aile.lower()
                        adlar.setdefault(anahtar, aile)
                        stil = _style_flags(alt)
                        # İlk gelen kazanır: Windows klasörü kullanıcı
                        # klasöründen önce taranır, sistem sürümü tercih edilir.
                        aileler.setdefault(anahtar, {}).setdefault(stil, yol)
            except (OSError, struct.error):
                continue
    return aileler, adlar


def available_families() -> list[str]:
    """Sistemde kurulu font aileleri (alfabetik). Hiç yoksa varsayılan."""
    _aileler, adlar = _index()
    return sorted(adlar.values(), key=str.lower) or [DEFAULT_FAMILY]


def has_family(family: str) -> bool:
    return (family or "").strip().lower() in _index()[0]


def _base14_kind(family: str) -> str:
    ad = (family or "").lower()
    if any(k in ad for k in ("mono", "courier", "consol", "code")):
        return "mono"
    if any(k in ad for k in ("times", "serif", "georgia", "garamond",
                             "book", "cambria", "roman")):
        return "serif"
    return "sans"


def resolve(family: str, bold: bool = False, italic: bool = False) -> tuple[str, str | None]:
    """``(fontname, fontfile)`` çiftini döndürür.

    ``fontfile`` ``None`` ise PyMuPDF'in dahili base-14 fontu kullanılır.
    """
    aileler, _adlar = _index()
    varyantlar = aileler.get((family or "").strip().lower())
    if varyantlar is None and family:
        # Kurulu değil: belgeden gelen bir ad olabilir ("Univers",
        # "NimbusRomNo9L"). Önce en yakın kurulu aile aranır; doğrudan
        # Arial'e düşmek serif bir belgeyi sans yapıyordu.
        varyantlar = aileler.get(match(family, DEFAULT_FAMILY).lower())
    if varyantlar:
        # İstenen stil yoksa en yakınına düşülür: tam eşleşme -> yalnız
        # kalın/yatık -> düz. Sentetik kalın üretmek yerine var olan dosya.
        for aday in ((bold, italic), (bold, False), (False, italic), (False, False)):
            yol = varyantlar.get(aday)
            if yol:
                # PyMuPDF gömülü font için benzersiz, ASCII bir takma ad ister.
                takma = "F" + "".join(
                    c for c in os.path.splitext(os.path.basename(yol))[0]
                    if c.isalnum()
                )
                return takma or "Fembedded", yol
        yol = next(iter(varyantlar.values()))
        return "F" + os.path.splitext(os.path.basename(yol))[0].replace(" ", ""), yol

    idx = (1 if bold else 0) + (2 if italic else 0)
    return _BASE14[_base14_kind(family)][idx], None


# ======================================================================
# Belgedeki font adını kurulu bir aileye eşleme
# ======================================================================
def _normalize(name: str) -> str:
    """``ABCDEF+FrutigerLTStd-Roman`` -> ``frutigerlt``."""
    ad = (name or "").split("+")[-1]
    ad = ad.replace("_", "-").replace(",", "-")
    parcalar: list[str] = []
    for parca in ad.split("-"):
        # CamelCase'i de böl: ``TimesNewRomanPSMT`` -> Times New Roman PSMT
        kelime = ""
        for ch in parca:
            if ch.isupper() and kelime and not kelime[-1].isupper():
                parcalar.append(kelime)
                kelime = ch
            else:
                kelime += ch
        if kelime:
            parcalar.append(kelime)
    temiz = [p for p in parcalar if p and p.lower() not in _STYLE_WORDS]
    return "".join(temiz).lower() or "".join(parcalar).lower()


def match(pdf_font_name: str, fallback: str = DEFAULT_FAMILY) -> str:
    """Belgedeki font adına en yakın **kurulu** aileyi bulur.

    Eşleşme bulunamazsa ``fallback`` döner. Eskiden burada sekiz dallı bir
    ``if/elif`` vardı ve tanımadığı her yazı tipini Arial yapıyordu; belgedeki
    metin düzenlenir düzenlenmez yazı tipi değişiyordu.
    """
    ham = (pdf_font_name or "").split("+")[-1]
    if not ham:
        return fallback
    aileler, adlar = _index()

    dumduz = ham.replace(" ", "").replace("-", "").lower()
    if dumduz in _ALIASES and _ALIASES[dumduz].lower() in aileler:
        return adlar[_ALIASES[dumduz].lower()]

    # 1) Adın kendisi bir aile mi? ("Segoe UI", "Frutiger LT Std")
    for aday in (ham.lower(), ham.replace("-", " ").lower()):
        if aday in aileler:
            return adlar[aday]

    # 2) Stil ekleri atılmış hâliyle boşluksuz karşılaştır.
    hedef = _normalize(ham)
    if not hedef:
        return fallback
    sikistirilmis = {
        k.replace(" ", ""): k for k in aileler
    }
    if hedef in sikistirilmis:
        return adlar[sikistirilmis[hedef]]

    # 3) En uzun ortak önek: "FrutigerLTStd" -> "Frutiger LT Std" yoksa
    #    "Frutiger"e düşer. Yanlış aileye sapmamak için en az 4 karakter.
    en_iyi = ""
    for sikisik in sikistirilmis:
        if len(sikisik) < 4:
            continue
        if hedef.startswith(sikisik) or sikisik.startswith(hedef):
            if len(sikisik) > len(en_iyi):
                en_iyi = sikisik
    if en_iyi:
        return adlar[sikistirilmis[en_iyi]]

    if dumduz in _ALIASES:
        return _ALIASES[dumduz]
    return fallback


# ======================================================================
# Ölçüyle eşleme — ada bakmadan "hangi aileye benziyor?"
# ======================================================================
#: Karşılaştırma havuzu: yaygın **gövde metni** aileleri (serif/sans/mono).
#: Havuz bilinçli olarak dar: 231 ailenin hepsini yüklemek ~2 sn sürüyor ve
#: süsleme fontlarından birinin genişlikleri rastgele tutabiliyor — okunur
#: bir gövde fontuna benzetmek her zaman daha doğru.
_METRIC_POOL = (
    "Times New Roman", "Georgia", "Cambria", "Garamond", "Book Antiqua",
    "Palatino Linotype", "Constantia", "Arial", "Calibri", "Verdana",
    "Tahoma", "Segoe UI", "Trebuchet MS", "Courier New", "Consolas",
)
#: Genişlik profili çıkarılacak karakterler
_METRIC_SAMPLE = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
#: Anlamlı bir karşılaştırma için gereken en az ortak glif
_METRIC_MIN_GLYPHS = 5


def _advance_profile(fontfile: str | None, fontname: str | None = None
                     ) -> dict[str, float]:
    """Karakter -> em birimli ilerleme genişliği."""
    try:
        from .pdf_backend import fitz

        font = fitz.Font(fontname=None if fontfile else fontname,
                         fontfile=fontfile)
    except Exception:  # noqa: BLE001 - okunamayan font
        return {}
    profil: dict[str, float] = {}
    for ch in _METRIC_SAMPLE:
        try:
            if font.has_glyph(ord(ch)):
                profil[ch] = float(font.glyph_advance(ord(ch)))
        except Exception:  # noqa: BLE001
            continue
    return profil


@lru_cache(maxsize=None)
def _pool_profiles() -> tuple[tuple[str, tuple[tuple[str, float], ...]], ...]:
    """Havuzdaki kurulu ailelerin genişlik profilleri (bir kez hesaplanır)."""
    sonuc = []
    for aile in _METRIC_POOL:
        if not has_family(aile):
            continue
        _ad, yol = resolve(aile)
        profil = _advance_profile(yol)
        if len(profil) >= _METRIC_MIN_GLYPHS:
            sonuc.append((aile, tuple(sorted(profil.items()))))
    return tuple(sonuc)


def closest_by_metrics(fontfile: str) -> str | None:
    """Dosyadaki fonta **genişlik metrikleriyle** en yakın kurulu aile.

    Belgedeki yazı tipi sistemde kurulu değilse ada bakarak tahmin yürütmek
    işe yaramıyor: ``CharisSIL``, ``Univers``, ``NimbusRomNo9L`` gibi adlar
    hiçbir kalıba uymuyor ve hepsi Arial'e düşüyordu — serif bir belge
    düzenlemeye girince ekranda sans oluyordu. Harf genişlikleri ise fontun
    kendi ölçüsüdür ve serif/sans ayrımını güvenilir biçimde taşır.
    """
    hedef = _advance_profile(fontfile)
    if len(hedef) < _METRIC_MIN_GLYPHS:
        return None
    en_iyi, en_kucuk = None, float("inf")
    for aile, ciftler in _pool_profiles():
        profil = dict(ciftler)
        ortak = [c for c in hedef if c in profil]
        if len(ortak) < _METRIC_MIN_GLYPHS:
            continue
        fark = sum(abs(hedef[c] - profil[c]) for c in ortak) / len(ortak)
        if fark < en_kucuk:
            en_iyi, en_kucuk = aile, fark
    return en_iyi


# ======================================================================
# Ağırlık ölçümü — "kalın mı?" sorusunu ada değil mürekkebe sorarak
# ======================================================================
#: Ölçüm puntosu ve render ölçeği
_STEM_SIZE = 100.0
_STEM_ZOOM = 2.0
#: Em birimi cinsinden gövde kalınlığı bu değerin üstündeyse kalın sayılır.
#: Kurulu 57 ailenin **hiçbir** düz yüzü bu eşiği aşmıyor (en kalın düz yüz
#: Bodoni MT, 0.115); yanlış pozitif üretmemesi için eşik yukarıda tutuldu.
#: Bazı zarif serif ailelerin kalın yüzü altında kalıyor (Garamond 0.105) —
#: onları span bayrağı ve font adı zaten yakalıyor.
BOLD_STEM_EM = 0.13


def stem_width(fontfile: str | None, sample: str) -> float | None:
    """Fontun gövde (stem) kalınlığı — em birimi. Ölçülemezse ``None``.

    Ağırlığın doğrudan ölçüsü. Metin büyütülüp çizilir ve x-yüksekliği
    bandında en sık görülen koyu piksel koşusu alınır: bu koşu harflerin
    dikey gövdesidir.

    Neden ölçüm: ``/StemV`` alanı üreticiler tarafından doldurulmuyor
    (``Poppins-Regular`` 500, ``Wingdings-Regular`` 580 yazıyor), font adı da
    her zaman söylemiyor (``FormataOTFMd`` = Medium). Kaplama oranı ise
    x-yüksekliğine göre değişip yanlış pozitif veriyor.
    """
    if not fontfile or not sample.strip():
        return None
    from collections import Counter

    try:
        from .pdf_backend import fitz

        doc = fitz.open()
        try:
            sayfa = doc.new_page(width=4000, height=400)
            sayfa.insert_text((20, 250), sample[:24], fontsize=_STEM_SIZE,
                              fontname="FStem", fontfile=fontfile)
            kutu = None
            for blok in sayfa.get_text("dict").get("blocks", []):
                for satir in blok.get("lines", []):
                    for span in satir.get("spans", []):
                        r = fitz.Rect(span["bbox"])
                        kutu = r if kutu is None else (kutu | r)
            if kutu is None or kutu.is_empty:
                return None
            pix = sayfa.get_pixmap(clip=kutu, colorspace=fitz.csGRAY,
                                   alpha=False,
                                   matrix=fitz.Matrix(_STEM_ZOOM, _STEM_ZOOM))
            en, boy, veri = pix.width, pix.height, pix.samples
            if not veri or en < 2 or boy < 4:
                return None
            kosular: Counter = Counter()
            # Yalnızca orta bant: üstte serifler/aksanlar, altta kuyruklar var.
            for y in range(int(boy * 0.35), int(boy * 0.65)):
                satir_bas = y * en
                uzunluk = 0
                for x in range(en):
                    if veri[satir_bas + x] < 128:
                        uzunluk += 1
                    elif uzunluk:
                        kosular[uzunluk] += 1
                        uzunluk = 0
                if uzunluk:
                    kosular[uzunluk] += 1
            if not kosular:
                return None
            return kosular.most_common(1)[0][0] / (_STEM_SIZE * _STEM_ZOOM)
        finally:
            doc.close()
    except Exception:  # noqa: BLE001 - çizilemeyen font
        return None


def looks_bold(fontfile: str, sample: str) -> bool:
    """Font kalın bir yüz mü? (gövde kalınlığı ölçülerek)

    Belgedeki yüz çoğu zaman ne tam düz ne tam kalındır (``Formata Medium``,
    ``Roboto Medium``); gövdesi kalın tarafa düşüyorsa kalın gösterilir.
    """
    olcum = stem_width(fontfile, sample)
    return olcum is not None and olcum >= BOLD_STEM_EM


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
