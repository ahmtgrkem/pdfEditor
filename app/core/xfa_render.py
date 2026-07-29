"""XFA şablonunu görüntülenebilir, doldurulabilir bir PDF'e dönüştürür.

Neden gerekli
-------------
Dinamik XFA formlarında sayfa akışı yalnızca "Adobe Reader gerekli" uyarısını
içerir; formun kendisi gömülü XML şablonundadır (bkz. :mod:`app.core.xfa`).
Bu modül şablonu **çizer**: yerleşimi hesaplar, metin/çizgi/görselleri sayfaya
işler ve alanları gerçek **AcroForm widget'ları** olarak ekler. Sonuç, her
görüntüleyicide açılan ve doldurulabilen sıradan bir PDF'tir.

Yerleşim modeli
---------------
XFA'nın alt kümesi uygulanır:

``position`` (varsayılan)
    Çocuklar kendi ``x``/``y`` değerleriyle konumlanır.
``tb``
    Çocuklar yukarıdan aşağıya yığılır; ``y`` yükseklik kadar ilerler.
``table`` / ``row``
    Satırlar dikey, satır içindekiler yatay dizilir.

Koordinat sistemi XFA'da da PyMuPDF ``Rect``'te de sol-üst köşeden başlar ve
``y`` aşağı doğru büyür; bu yüzden çevirme gerekmez.

Uygulanmayanlar: betik kuralları (koşullu alanlar, hesaplamalar), zengin
metin biçimlendirmesi, taşma halinde dinamik sayfa üretimi (içerik alanına
sığmayan bölümler yeni sayfaya taşınır ama XFA'nın ``overflow`` kuralları
birebir izlenmez).
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass, field as dataclass_field
from xml.etree import ElementTree as ET

import fitz

from . import fonts
from .xfa import READONLY_TYPES, _local, _UI_TYPES

#: 1 mm kaç punto
_MM = 72.0 / 25.4
_UNITS = {
    "mm": _MM,
    "cm": _MM * 10,
    "in": 72.0,
    "pt": 1.0,
    "px": 0.75,        # XFA'da px = 1/96 inç
}
_MEASURE_RE = re.compile(r"^\s*(-?[\d.]+)\s*([a-z]*)\s*$", re.I)

#: Varsayılan sayfa boyutu (A4)
DEFAULT_PAGE = (210 * _MM, 297 * _MM)
#: Yazı tipi bulunamazsa kullanılan punto
DEFAULT_FONT_SIZE = 9.0
#: Alan etiketi için ayrılan varsayılan genişlik
DEFAULT_CAPTION_RESERVE = 20 * _MM

#: XFA yazı tipi adı -> uygulamanın font çözümleyicisindeki aile
_TYPEFACE_MAP = {
    "myriad pro": "Arial",
    "myriad pro bold": "Arial",
    "courier new": "Courier New",
    "courier std": "Courier New",
    "times new roman": "Times New Roman",
    "arial": "Arial",
    "helvetica": "Arial",
    "verdana": "Verdana",
    "tahoma": "Tahoma",
    "calibri": "Calibri",
}


def parse_measure(value: str | None, default: float = 0.0) -> float:
    """``"12.5mm"`` -> punto. Tanınmayan girdide ``default``."""
    if not value:
        return default
    eslesme = _MEASURE_RE.match(str(value))
    if not eslesme:
        return default
    try:
        sayi = float(eslesme.group(1))
    except ValueError:
        return default
    return sayi * _UNITS.get(eslesme.group(2).lower(), 1.0)


# ======================================================================
# Yerleşim
# ======================================================================
@dataclass
class Box:
    """Sayfaya yerleştirilmiş tek bir öğe (punto, sayfa koordinatları)."""

    node: ET.Element
    kind: str                       # "draw" | "field"
    x: float
    y: float
    w: float
    h: float
    path: str = ""
    #: Şablonda ``presence="hidden"`` işaretli mi? (betikle açılan içerik)
    hidden: bool = False

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(self.x, self.y, self.x + self.w, self.y + self.h)


@dataclass
class Layout:
    """Hesaplanmış yerleşim: sayfa başına kutular."""

    pages: list[list[Box]] = dataclass_field(default_factory=list)
    page_size: tuple[float, float] = DEFAULT_PAGE
    #: ``pageArea`` süslemeleri (arka plan görseli, logo, sayfa numarası).
    #: Her sayfada, içeriğin **altına** çizilir.
    background: list[Box] = dataclass_field(default_factory=list)
    #: Altbilgideki gömülü alan kimliği -> ``"current"`` | ``"total"``.
    #: Sayfa numarası alanları betikle hesaplandığı için burada karşılanır.
    page_field_ids: dict[str, str] = dataclass_field(default_factory=dict)

    @property
    def box_count(self) -> int:
        return sum(len(s) for s in self.pages)


def _content_area(root: ET.Element) -> tuple[float, float, float, float]:
    """``pageArea/contentArea`` -> (x, y, w, h) punto."""
    for dugum in root.iter():
        if _local(dugum.tag) != "contentArea":
            continue
        return (
            parse_measure(dugum.get("x"), 10 * _MM),
            parse_measure(dugum.get("y"), 10 * _MM),
            parse_measure(dugum.get("w"), 190 * _MM),
            parse_measure(dugum.get("h"), 277 * _MM),
        )
    return (10 * _MM, 10 * _MM, 190 * _MM, 277 * _MM)


def _page_size(root: ET.Element) -> tuple[float, float]:
    for dugum in root.iter():
        if _local(dugum.tag) != "medium":
            continue
        genis = parse_measure(dugum.get("short"), DEFAULT_PAGE[0])
        yuksek = parse_measure(dugum.get("long"), DEFAULT_PAGE[1])
        if dugum.get("orientation") == "landscape":
            genis, yuksek = yuksek, genis
        return (genis, yuksek)
    return DEFAULT_PAGE


#: Yerleşimde kap sayılan düğümler
_CONTAINERS = ("subform", "subformSet", "exclGroup", "area")
#: Yerleşimde yaprak (çizilen) sayılan düğümler
_LEAVES = ("draw", "field")


def _node_text(node: ET.Element) -> str:
    """``value`` altındaki düz metin (``exData`` HTML'i sadeleştirilir)."""
    for cocuk in node:
        if _local(cocuk.tag) != "value":
            continue
        for icerik in cocuk:
            etiket = _local(icerik.tag)
            if etiket == "text":
                return (icerik.text or "").strip()
            if etiket == "exData":
                ham = "".join(icerik.itertext())
                return re.sub(r"\s+", " ", ham).strip()
    return ""


def _is_visible(node: ET.Element, show_hidden: bool = True) -> bool:
    """Öğe çizilmeli mi?

    ``presence="invisible"`` **her zaman** atlanır: bunlar ekranda yer kaplayan
    ama çizilmeyen veri taşıyıcılarıdır (dosya eki içeriği gibi) ve görünür
    alanlarla üst üste biner.

    ``presence="hidden"`` bölümler dinamik XFA'da betikle açılır. Betikleri
    çalıştırmadığımız için bunlara uyulsaydı formun büyük bölümü — bu belgede
    11 alt formun tamamı: kimlik, profil, hedef gruplar… — kaybolurdu. Statik
    çıktının amacı formu görünür kılmak olduğundan varsayılan olarak çizilirler.
    """
    varlik = node.get("presence")
    if varlik == "invisible":
        return False
    if varlik in ("hidden", "inactive"):
        if not show_hidden:
            return False
        # Gizli kaplar arasında ayrım: etiketli alan taşıyanlar gerçek form
        # bölümleridir (kimlik, profil…) ve gösterilmelidir. Hiç etiketi
        # olmayanlar dosya eki içeriği gibi iç veri taşıyıcılarıdır; bunları
        # çizmek kullanıcıya anlamsız kutular ve geliştirici notları gösterir.
        if _local(node.tag) in _CONTAINERS:
            return _has_captioned_field(node)
    return True


def _has_captioned_field(node: ET.Element) -> bool:
    """Kapsayıcı, kullanıcıya gösterilecek etiketli bir alan içeriyor mu?"""
    for alt in node.iter():
        if _local(alt.tag) != "field":
            continue
        for cocuk in alt:
            if _local(cocuk.tag) == "caption" and _node_text(cocuk):
                return True
    return False


def _natural_height(node: ET.Element) -> float:
    """Yükseklik verilmemiş öğeler için makul bir varsayılan."""
    h = parse_measure(node.get("h"))
    if h > 0:
        return h
    etiket = _local(node.tag)
    if etiket == "field":
        return 9 * _MM
    if etiket == "draw":
        return 5 * _MM
    return 0.0


class _Layouter:
    """Şablon ağacını gezip sayfalara dağıtılmış kutu listesi üretir.

    İki aşamalıdır:

    1. :meth:`_measure` her kabı **göreli** olarak ölçer (kutular kabın sol-üst
       köşesine göre) ve yüksekliğini döndürür.
    2. :meth:`run` kök akıştaki bölümleri sayfalara yerleştirir.

    Ayrım önemli: ölçüm sırasında sayfa kırma yapmak, kap içindeki mutlak
    konumlu çocukların birbirinden kopmasına yol açar. Bu yüzden sayfalama
    yalnızca en üst düzeydeki bölümler arasında yapılır.
    """

    #: Bozuk şablon sonsuz sayfa üretmesin
    MAX_PAGES = 80

    def __init__(self, root: ET.Element, show_hidden: bool = True) -> None:
        self.root = root
        self.show_hidden = show_hidden
        self.page_w, self.page_h = _page_size(root)
        self.ca_x, self.ca_y, self.ca_w, self.ca_h = _content_area(root)

    # -- 1) ölçüm ------------------------------------------------------
    def _measure(
        self, node: ET.Element, avail_w: float, path: list[str],
    ) -> tuple[list[Box], float]:
        """``node`` içeriğini göreli konumlarla ölçer -> (kutular, yükseklik)."""
        duzen = (node.get("layout") or "position").lower()
        ad = node.get("name")
        yeni_yol = path + [ad] if ad else path

        kutular: list[Box] = []
        akis_y = 0.0
        akis_x = 0.0
        alt_sinir = 0.0

        for cocuk in node:
            etiket = _local(cocuk.tag)
            if etiket not in _CONTAINERS + _LEAVES:
                continue
            if not _is_visible(cocuk, self.show_hidden):
                continue

            c_w = parse_measure(cocuk.get("w")) or avail_w
            c_h = parse_measure(cocuk.get("h"))

            if duzen in ("tb", "table"):
                cx = parse_measure(cocuk.get("x"))
                cy = akis_y
            elif duzen == "row":
                cx = akis_x
                cy = parse_measure(cocuk.get("y"))
            else:                                    # position (varsayılan)
                cx = parse_measure(cocuk.get("x"))
                cy = parse_measure(cocuk.get("y"))

            if etiket in _CONTAINERS:
                ic_kutular, ic_h = self._measure(cocuk, c_w, yeni_yol)
                if not c_h:
                    c_h = ic_h
                for k in ic_kutular:
                    k.x += cx
                    k.y += cy
                    kutular.append(k)
            else:
                if not c_h:
                    c_h = _natural_height(cocuk)
                kutular.append(
                    Box(node=cocuk, kind=etiket, x=cx, y=cy, w=c_w, h=c_h,
                        path=".".join(yeni_yol + [cocuk.get("name") or ""]),
                        hidden=cocuk.get("presence") == "hidden"),
                )

            if duzen in ("tb", "table"):
                akis_y += c_h
            elif duzen == "row":
                akis_x += c_w
            alt_sinir = max(alt_sinir, cy + c_h)

        return kutular, max(alt_sinir, akis_y)

    # -- 2) akış öğeleri ----------------------------------------------
    def _flow_items(
        self, node: ET.Element, avail_w: float, path: list[str],
    ) -> list[tuple[list[Box], float, float]]:
        """Sayfalanabilir en küçük parçaları üretir -> (kutular, x, yükseklik).

        ``tb``/``table`` kaplarının **içine iner**: bütün bir bölümü tek parça
        saymak, uzun bir bölümün tamamını tek sayfaya sıkıştırıp geri kalan
        sayfaları boş bırakır. Mutlak konumlu (``position``) kaplar ise
        bölünemez; çocukları birbirine göre konumlandığı için bir bütündür.
        """
        duzen = (node.get("layout") or "position").lower()
        ad = node.get("name")
        yeni_yol = path + [ad] if ad else path
        ogeler: list[tuple[list[Box], float, float]] = []

        for cocuk in node:
            etiket = _local(cocuk.tag)
            if etiket not in _CONTAINERS + _LEAVES:
                continue
            if not _is_visible(cocuk, self.show_hidden):
                continue

            c_x = parse_measure(cocuk.get("x"))
            c_w = parse_measure(cocuk.get("w")) or avail_w

            if etiket in _CONTAINERS:
                ic_duzen = (cocuk.get("layout") or "position").lower()
                if duzen in ("tb", "table") and ic_duzen in ("tb", "table"):
                    ogeler.extend(self._flow_items(cocuk, c_w, yeni_yol))
                    continue
                kutular, yukseklik = self._measure(cocuk, c_w, yeni_yol)
                yukseklik = parse_measure(cocuk.get("h")) or yukseklik
            else:
                yukseklik = parse_measure(cocuk.get("h")) or _natural_height(cocuk)
                kutular = [
                    Box(node=cocuk, kind=etiket, x=0, y=0, w=c_w, h=yukseklik,
                        path=".".join(yeni_yol + [cocuk.get("name") or ""]),
                        hidden=cocuk.get("presence") == "hidden")
                ]
            ogeler.append((kutular, c_x, yukseklik))

        return ogeler

    # -- pageArea süslemeleri ------------------------------------------
    def _page_furniture(self) -> tuple[list[Box], dict[str, str]]:
        """``pageArea`` içindeki çizimler: arka plan görseli, logo, altbilgi.

        Bunlar kök alt formun dışındadır; yalnızca alt formu gezmek arka plan
        deseninin ve AB bayrağının tamamen kaybolmasına yol açar.

        Ayrıca sayfa sayacı alanlarının kimlikleri toplanır: altbilgi metni
        bunlara ``xfa:embed`` ile atıfta bulunur ve değerleri betikle
        hesaplandığı için çizim sırasında yerine konur.
        """
        kutular: list[Box] = []
        sayac_kimlikleri: dict[str, str] = {}
        for sayfa_alani in self.root.iter():
            if _local(sayfa_alani.tag) != "pageArea":
                continue
            for cocuk in sayfa_alani:
                if _local(cocuk.tag) == "field":
                    # Sayaçlar doldurulabilir alan değildir; yalnızca
                    # altbilgide gösterilmek üzere kimlikleri kaydedilir.
                    ad = cocuk.get("name")
                    kimlik = cocuk.get("id")
                    if kimlik and ad in ("CurrentPage", "PageCount"):
                        sayac_kimlikleri[kimlik] = (
                            "current" if ad == "CurrentPage" else "total"
                        )
                    continue
                if _local(cocuk.tag) != "draw" or not _is_visible(cocuk):
                    continue
                kutular.append(
                    Box(
                        node=cocuk, kind="draw",
                        x=parse_measure(cocuk.get("x")),
                        y=parse_measure(cocuk.get("y")),
                        w=parse_measure(cocuk.get("w")) or self.page_w,
                        h=parse_measure(cocuk.get("h")) or _natural_height(cocuk),
                        path=cocuk.get("name") or "",
                    )
                )
            break           # tek ana sayfa şablonu destekleniyor
        return kutular, sayac_kimlikleri

    # -- 3) sayfalara dağıtım -----------------------------------------
    def run(self) -> Layout:
        arka_plan, sayac_kimlikleri = self._page_furniture()
        kok_sf = next((c for c in self.root if _local(c.tag) == "subform"), None)
        if kok_sf is None:
            return Layout(pages=[[]], page_size=(self.page_w, self.page_h),
                          background=arka_plan,
                          page_field_ids=sayac_kimlikleri)

        sayfalar: list[list[Box]] = [[]]
        imlec = self.ca_y
        alt = self.ca_y + self.ca_h
        sag = self.ca_x + self.ca_w

        for kutular, ofset_x, yukseklik in self._flow_items(kok_sf, self.ca_w, []):
            if imlec > self.ca_y and imlec + yukseklik > alt:
                if len(sayfalar) >= self.MAX_PAGES:
                    break
                sayfalar.append([])
                imlec = self.ca_y

            for k in kutular:
                k.x += self.ca_x + ofset_x
                k.y += imlec
                # Şablonun bildirdiği genişlik kabı aşabiliyor (özellikle
                # genişliği verilmemiş satır hücrelerinde); sayfa dışına
                # taşan widget hiçbir görüntüleyicide tıklanamaz.
                if k.x + k.w > sag:
                    k.w = max(sag - k.x, 0.0)
                if k.w > 0 and k.h > 0 and k.x < sag:
                    sayfalar[-1].append(k)
            imlec += yukseklik

        return Layout(pages=sayfalar, page_size=(self.page_w, self.page_h),
                      background=arka_plan, page_field_ids=sayac_kimlikleri)


def layout_template(template: bytes, show_hidden: bool = False) -> Layout:
    """Şablonu çözümleyip yerleşimi hesaplar."""
    if not template:
        return Layout(pages=[[]])
    try:
        kok = ET.fromstring(template)
    except ET.ParseError:
        return Layout(pages=[[]])
    return _Layouter(kok, show_hidden=show_hidden).run()


# ======================================================================
# Çizim
# ======================================================================
#: Zengin metinde başka bir alanın değerini gömen öznitelik
#: (``xfa-data`` ad alanı; :mod:`app.core.xfa` ile aynı sabit).
_EMBED_ATTR = "{http://www.xfa.org/schema/xfa-data/1.0/}embed"


def _embedded_text(node: ET.Element, values: dict[str, str]) -> str:
    """Zengin metni ``xfa:embed`` referanslarını çözerek düzleştirir.

    Altbilgi ``Page <embed CurrentPage> of <embed PageCount>`` biçimindedir;
    referanslar çözülmezse sayfada "Page of" yazar.
    """
    parcalar: list[str] = []
    for alt in node.iter():
        kimlik = alt.get(_EMBED_ATTR)
        if kimlik:
            parcalar.append(values.get(kimlik.lstrip("#"), ""))
        if alt.text and alt.text.strip():
            parcalar.append(alt.text.strip())
        if alt.tail and alt.tail.strip():
            parcalar.append(alt.tail.strip())
    return re.sub(r"\s+", " ", " ".join(p for p in parcalar if p)).strip()


def _draw_text_for_page(node: ET.Element, page_values: dict[str, str]) -> str:
    """Çizim metni; sayfa sayaçları varsa yerine konmuş hâliyle."""
    for cocuk in node:
        if _local(cocuk.tag) != "value":
            continue
        for icerik in cocuk:
            if _local(icerik.tag) == "exData" and page_values:
                if any(a.get(_EMBED_ATTR) for a in icerik.iter()):
                    return _embedded_text(icerik, page_values)
    return _node_text(node)


def _fit_image_rect(rect: fitz.Rect, stream: bytes) -> fitz.Rect:
    """Görseli oranını koruyarak kutuya sığdırır, **üst ortaya** yaslar.

    PyMuPDF oranı korurken görseli kutuda dikey olarak ortalar. XFA
    yerleşiminde görsel kutusu çoğunlukla gerçek görselden yüksektir; ortalama
    yapılınca görsel aşağı kayar ve altındaki başlığın üzerine biner.
    """
    try:
        with fitz.open(stream=stream) as gorsel:
            en, boy = gorsel[0].rect.width, gorsel[0].rect.height
    except Exception:  # noqa: BLE001 - tanınmayan biçim
        return rect
    if en <= 0 or boy <= 0:
        return rect

    olcek = min(rect.width / en, rect.height / boy)
    yeni_en, yeni_boy = en * olcek, boy * olcek
    sol = rect.x0 + (rect.width - yeni_en) / 2
    return fitz.Rect(sol, rect.y0, sol + yeni_en, rect.y0 + yeni_boy)


def _node_image(node: ET.Element) -> bytes | None:
    for cocuk in node:
        if _local(cocuk.tag) != "value":
            continue
        for icerik in cocuk:
            if _local(icerik.tag) != "image":
                continue
            ham = (icerik.text or "").strip()
            if not ham:
                return None
            try:
                return base64.b64decode(ham)
            except (binascii.Error, ValueError):
                return None
    return None


def _font_of(node: ET.Element) -> tuple[str, float, bool]:
    """(aile, punto, kalın) — düğümün ya da alt düğümlerinin font ayarı."""
    for alt in node.iter():
        if _local(alt.tag) != "font":
            continue
        tipografi = (alt.get("typeface") or "").strip().lower()
        aile = _TYPEFACE_MAP.get(tipografi, "Arial")
        boyut = parse_measure(alt.get("size"), DEFAULT_FONT_SIZE)
        kalin = (alt.get("weight") or "").lower() == "bold" or "bold" in tipografi
        return aile, max(boyut, 4.0), kalin
    return "Arial", DEFAULT_FONT_SIZE, False


def _align_of(node: ET.Element) -> int:
    for alt in node.iter():
        if _local(alt.tag) != "para":
            continue
        return {
            "left": fitz.TEXT_ALIGN_LEFT,
            "center": fitz.TEXT_ALIGN_CENTER,
            "right": fitz.TEXT_ALIGN_RIGHT,
            "justify": fitz.TEXT_ALIGN_JUSTIFY,
        }.get((alt.get("hAlign") or "left").lower(), fitz.TEXT_ALIGN_LEFT)
    return fitz.TEXT_ALIGN_LEFT


def _caption_of(node: ET.Element) -> tuple[str, float, str]:
    """Alanın etiketi, ayrılan genişlik ve yerleşimi.

    XFA'da ``placement`` etiketin **hangi tarafta** durduğunu söyler ve
    varsayılanı ``left``\'tir. Onay kutularında genelde ``right`` kullanılır:
    küçük kutu solda, açıklaması sağında. Bu yok sayılırsa kutular satırın
    en sağına düşer ve etiketleriyle ilişkisi kopar.
    """
    for cocuk in node:
        if _local(cocuk.tag) != "caption":
            continue
        if not _is_visible(cocuk):
            return "", 0.0, "left"
        return (
            _node_text(cocuk),
            parse_measure(cocuk.get("reserve"), DEFAULT_CAPTION_RESERVE),
            (cocuk.get("placement") or "left").lower(),
        )
    return "", 0.0, "left"


def _split_caption(
    box_rect: fitz.Rect, reserve: float, placement: str,
) -> tuple[fitz.Rect, fitz.Rect]:
    """Alan dikdörtgenini (etiket, widget) olarak böler."""
    x0, y0, x1, y1 = box_rect
    genislik = x1 - x0
    yukseklik = y1 - y0
    if placement == "right":
        pay = min(reserve, genislik * 0.9)
        return (fitz.Rect(x1 - pay, y0, x1, y1), fitz.Rect(x0, y0, x1 - pay, y1))
    if placement == "top":
        pay = min(reserve or yukseklik / 2, yukseklik * 0.6)
        return (fitz.Rect(x0, y0, x1, y0 + pay), fitz.Rect(x0, y0 + pay, x1, y1))
    if placement == "bottom":
        pay = min(reserve or yukseklik / 2, yukseklik * 0.6)
        return (fitz.Rect(x0, y1 - pay, x1, y1), fitz.Rect(x0, y0, x1, y1 - pay))
    pay = min(reserve, genislik * 0.9)          # left (varsayılan)
    return (fitz.Rect(x0, y0, x0 + pay, y1), fitz.Rect(x0 + pay, y0, x1, y1))


def _ui_type(node: ET.Element) -> str:
    for cocuk in node:
        if _local(cocuk.tag) != "ui":
            continue
        for torun in cocuk:
            tur = _UI_TYPES.get(_local(torun.tag))
            if tur:
                return tur
    return "text"


def _is_round_button(node: ET.Element) -> bool:
    """``checkButton shape="round"`` -> radyo düğmesi.

    Yuvarlak onay kutuları XFA'da birbirini dışlayan seçim (radyo) demektir;
    kare kutu olarak çizilirse kullanıcı birden çok seçenek işaretlenebilir
    sanır.
    """
    for cocuk in node:
        if _local(cocuk.tag) != "ui":
            continue
        for torun in cocuk:
            if _local(torun.tag) == "checkButton":
                return (torun.get("shape") or "square").lower() == "round"
    return False


def _options(node: ET.Element) -> list[tuple[str, str]]:
    gorunen: list[str] = []
    kaydedilen: list[str] = []
    for cocuk in node:
        if _local(cocuk.tag) != "items":
            continue
        degerler = [(t.text or "").strip() for t in cocuk if _local(t.tag) == "text"]
        if cocuk.get("save") == "1":
            kaydedilen = degerler
        else:
            gorunen = degerler
    if not gorunen:
        gorunen = kaydedilen
    if not kaydedilen:
        kaydedilen = gorunen
    return list(zip(gorunen, kaydedilen))


def _insert_text(page, rect: fitz.Rect, text: str, node: ET.Element,
                 color=(0, 0, 0)) -> None:
    """Metni kutuya sığdırır; sığmazsa puntoyu kademeli küçültür."""
    if not text or rect.is_empty:
        return
    aile, boyut, kalin = _font_of(node)
    fontname, fontfile = fonts.resolve(aile, bold=kalin)
    hiza = _align_of(node)
    for deneme in (boyut, boyut * 0.85, boyut * 0.7, boyut * 0.55):
        try:
            artan = page.insert_textbox(
                rect, text, fontname=fontname, fontfile=fontfile,
                fontsize=deneme, color=color, align=hiza,
            )
        except Exception:  # noqa: BLE001 - font/kutu uyuşmazlığı
            return
        if artan >= 0:
            return


def _apply_margin(rect: fitz.Rect, node: ET.Element) -> fitz.Rect:
    """``<margin>`` iç boşluklarını uygular.

    XFA'da alan kutusu, içeriğin çizildiği alandan bu kadar geniştir.
    Uygulanmazsa bitişik alanlar birbirine yapışır ve tek bir blok gibi
    görünür — özgün belgede aralarında ince bir boşluk vardır.
    """
    for cocuk in node:
        if _local(cocuk.tag) != "margin":
            continue
        sol = parse_measure(cocuk.get("leftInset"))
        sag = parse_measure(cocuk.get("rightInset"))
        ust = parse_measure(cocuk.get("topInset"))
        alt = parse_measure(cocuk.get("bottomInset"))
        daraltilmis = fitz.Rect(
            rect.x0 + sol, rect.y0 + ust, rect.x1 - sag, rect.y1 - alt
        )
        # Boşluklar kutudan büyükse özgün dikdörtgen korunur.
        if daraltilmis.width > 1 and daraltilmis.height > 1:
            return daraltilmis
        return rect
    return rect


def _parse_color(node: ET.Element | None, default=(0.35, 0.35, 0.35)):
    """``<color value="r,g,b"/>`` -> 0-1 aralığında RGB."""
    if node is None:
        return default
    for cocuk in node:
        if _local(cocuk.tag) != "color":
            continue
        parcalar = (cocuk.get("value") or "").split(",")
        if len(parcalar) != 3:
            continue
        try:
            return tuple(min(max(int(p), 0), 255) / 255.0 for p in parcalar)
        except ValueError:
            return default
    return default


def _border_node(node: ET.Element) -> ET.Element | None:
    """Çizilecek kenarlık düğümü.

    XFA'da iki ayrı kenarlık olabilir: ``ui/<düzenleyici>/border`` görünen
    kutuyu, ``field/border`` ise doğrulama vurgusunu tanımlar (bu formda
    kırmızı). Görsel olarak geçerli olan ``ui`` altındakidir; yoksa
    düğümün kendi kenarlığına düşülür.
    """
    for cocuk in node:
        if _local(cocuk.tag) != "ui":
            continue
        for duzenleyici in cocuk:
            for torun in duzenleyici:
                if _local(torun.tag) == "border":
                    return torun
    for cocuk in node:
        if _local(cocuk.tag) == "border":
            return cocuk
    return None


def _draw_borders(page, rect: fitz.Rect, node: ET.Element) -> None:
    """XFA kenar modeline göre kenarlık çizer.

    ``border`` altında tek ``edge`` varsa dört kenara da uygulanır; dört
    ``edge`` varsa sırası **üst, sağ, alt, sol**\'dur. Bu form alanlarının
    çoğunda yalnızca alt kenar görünür — Foxit/Adobe'de gördüğünüz alt
    çizgi stili buradan gelir. Kenar kenar çizilmezse alanlar kutu gibi
    görünür ve özgün tasarımdan uzaklaşır.
    """
    kenarlik = _border_node(node)
    if kenarlik is None:
        return
    kenarlar = [k for k in kenarlik if _local(k.tag) == "edge"]
    if not kenarlar:
        return

    x0, y0, x1, y1 = rect
    if len(kenarlar) == 1:
        kenarlar = kenarlar * 4
    kenarlar = (kenarlar + kenarlar[-1:] * 4)[:4]

    cizgiler = (
        ((x0, y0), (x1, y0)),        # üst
        ((x1, y0), (x1, y1)),        # sağ
        ((x0, y1), (x1, y1)),        # alt
        ((x0, y0), (x0, y1)),        # sol
    )
    for kenar, (bas, son) in zip(kenarlar, cizgiler):
        if kenar.get("presence") in ("hidden", "inactive"):
            continue
        kalinlik = parse_measure(kenar.get("thickness"), 0.5)
        try:
            page.draw_line(fitz.Point(*bas), fitz.Point(*son),
                           color=_parse_color(kenar),
                           width=max(min(kalinlik, 2.0), 0.3))
        except Exception:  # noqa: BLE001 - geçersiz koordinat
            return


_WIDGET_TYPES = {
    "text": fitz.PDF_WIDGET_TYPE_TEXT,
    "number": fitz.PDF_WIDGET_TYPE_TEXT,
    "date": fitz.PDF_WIDGET_TYPE_TEXT,
    "password": fitz.PDF_WIDGET_TYPE_TEXT,
    "check": fitz.PDF_WIDGET_TYPE_CHECKBOX,
    "choice": fitz.PDF_WIDGET_TYPE_COMBOBOX,
}

#: Onay kutusu/radyo widget'ının kenar uzunluğu — XFA'da alan kutusu
#: etiketiyle birlikte tanımlandığı için tıklama alanı satır boyunca uzar.
_TOGGLE_SIZE = 4.2 * _MM


def _add_widget(page, rect: fitz.Rect, node: ET.Element, path: str,
                value: str) -> bool:
    """Alanı gerçek bir AcroForm widget'ı olarak ekler."""
    tur = _ui_type(node)
    if tur in READONLY_TYPES:
        return False
    widget_turu = _WIDGET_TYPES.get(tur)
    if widget_turu is None or rect.is_empty:
        return False

    aile, boyut, kalin = _font_of(node)
    fontname, _dosya = fonts.resolve(aile, bold=kalin)

    if widget_turu == fitz.PDF_WIDGET_TYPE_CHECKBOX and _is_round_button(node):
        widget_turu = fitz.PDF_WIDGET_TYPE_RADIOBUTTON

    w = fitz.Widget()
    w.rect = rect
    w.field_type = widget_turu
    w.field_name = path or (node.get("name") or "alan")
    w.fill_color = (0.93, 0.94, 0.99)

    if widget_turu in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                       fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
        # Kenarlıksız bir onay kutusu/radyo yalnızca soluk bir leke gibi
        # görünür; çerçeve olmadan tıklanabilir olduğu anlaşılmaz.
        w.border_color = (0.45, 0.47, 0.55)
        w.border_width = 0.8
    else:
        # Metin alanlarında kenarlık sayfaya ayrıca çizilir (çoğunlukla
        # yalnızca alt kenar); widget da çerçeve çizerse alt çizgi stili
        # kutuya dönüşür.
        w.border_width = 0

    if widget_turu in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                       fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
        # Yalnızca veri, kutunun "açık" değerine eşitse işaretli çizilir.
        # Boş dize kapalı demektir (bkz. app.core.xfa: şablondaki <value>
        # onay kutusunda durum değil, açık değeridir).
        acik_degerler = {k for _g, k in _options(node) if k}
        w.field_value = bool(value) and (not acik_degerler or value in acik_degerler)
    elif widget_turu == fitz.PDF_WIDGET_TYPE_COMBOBOX:
        secenekler = _options(node)
        w.choice_values = [g for g, _k in secenekler] or [""]
        if value:
            eslesen = next((g for g, k in secenekler if k == value), value)
            w.field_value = eslesen
    else:
        # Gömülü olmayan fontlar widget'ta bozuk görünebilir; base-14 güvenli.
        w.text_font = "Helv" if fontname.lower() not in ("cour", "tiro") else fontname
        w.text_fontsize = min(boyut, 11.0)
        w.field_value = value or ""

    try:
        page.add_widget(w)
    except Exception:  # noqa: BLE001 - desteklenmeyen alan yapılandırması
        return False
    return True


#: Gizli bir çizimin, görünür olanın "yerine geçmiş" sayılması için gereken
#: örtüşme oranı
_OVERLAP_LIMIT = 0.4


def _visible_draws(boxes: list[Box]) -> list[Box]:
    """Çizilecek ``draw`` kutuları; örtüşen gizli kopyalar elenir.

    Şablonlarda aynı yere iki başlık konup biri gizlenebilir (koşullu metin).
    Betikleri çalıştırmadığımız için ikisi de çizilir ve üst üste binerek
    okunmaz hâle gelir. Görünür bir çizimle ciddi biçimde örtüşen gizli
    çizim, onun alternatifi kabul edilip atlanır.
    """
    cizimler = [k for k in boxes if k.kind == "draw"]
    gorunur = [k for k in cizimler if not k.hidden]
    sonuc: list[Box] = []
    for kutu in cizimler:
        if kutu.hidden and _overlaps_any(kutu, gorunur):
            continue
        sonuc.append(kutu)
    return sonuc


def _overlaps_any(box: Box, others: list[Box]) -> bool:
    alan = box.w * box.h
    if alan <= 0:
        return False
    for diger in others:
        kesisim = box.rect & diger.rect
        if kesisim.is_valid and not kesisim.is_empty:
            if (kesisim.width * kesisim.height) / alan >= _OVERLAP_LIMIT:
                return True
    return False


def render(template: bytes, values: dict[str, str] | None = None,
           show_hidden: bool = False) -> fitz.Document:
    """Şablonu çizip yeni bir PDF belgesi döndürür.

    ``values`` verilirse alanlar dolu oluşturulur (yol -> değer).
    Sonuç belgede XFA yoktur; sıradan bir AcroForm PDF'idir.

    ``show_hidden=True`` betikle açılan bölümleri de çizer: özgün görünüme
    sadık kalmaz ama formun tamamını tek seferde doldurulabilir kılar.
    """
    yerlesim = layout_template(template, show_hidden=show_hidden)
    degerler = values or {}
    doc = fitz.open()
    genis, yuksek = yerlesim.page_size

    toplam_sayfa = len(yerlesim.pages) or 1
    for sayfa_no, kutular in enumerate(yerlesim.pages or [[]], start=1):
        sayfa = doc.new_page(width=genis, height=yuksek)

        # Altbilgideki sayaçlar betikle hesaplandığı için burada karşılanır.
        sayac_degerleri = {
            kimlik: str(sayfa_no if rol == "current" else toplam_sayfa)
            for kimlik, rol in yerlesim.page_field_ids.items()
        }

        # 1) Sayfa süslemeleri (arka plan deseni, logo) her sayfada en altta.
        for kutu in yerlesim.background:
            gorsel = _node_image(kutu.node)
            if gorsel:
                try:
                    sayfa.insert_image(_fit_image_rect(kutu.rect, gorsel),
                                       stream=gorsel, overlay=False)
                except Exception:  # noqa: BLE001 - bozuk görsel
                    pass
                continue
            _insert_text(sayfa, kutu.rect,
                         _draw_text_for_page(kutu.node, sayac_degerleri),
                         kutu.node)

        # 2) Önce çizimler, sonra alanlar: widget'lar üstte kalsın.
        for kutu in _visible_draws(kutular):
            gorsel = _node_image(kutu.node)
            if gorsel:
                try:
                    sayfa.insert_image(kutu.rect, stream=gorsel, keep_proportion=True)
                except Exception:  # noqa: BLE001 - bozuk/desteklenmeyen görsel
                    pass
                continue
            _draw_borders(sayfa, kutu.rect, kutu.node)
            _insert_text(sayfa, kutu.rect, _node_text(kutu.node), kutu.node)

        for kutu in [k for k in kutular if k.kind == "field"]:
            # DİKKAT: değişken adı ``yerlesim`` olamaz — dış kapsamdaki
            # Layout nesnesini gölgeler ve ikinci sayfada çökertir.
            etiket, ayrilan, etiket_yeri = _caption_of(kutu.node)
            alan_dikdortgen = kutu.rect
            if etiket and ayrilan > 0:
                etiket_dik, alan_dikdortgen = _split_caption(
                    kutu.rect, ayrilan, etiket_yeri
                )
                _insert_text(sayfa, etiket_dik, etiket, kutu.node,
                             color=(0.15, 0.15, 0.15))

            alan_turu = _ui_type(kutu.node)

            # Resim alanları (logo, bayrak) doldurulabilir değildir ama
            # değerlerindeki görsel sayfanın parçasıdır; çizilmezse belgenin
            # görünümü özgününden belirgin biçimde ayrılır.
            if alan_turu == "image":
                gorsel = _node_image(kutu.node)
                if gorsel:
                    hedef = _fit_image_rect(
                        _apply_margin(kutu.rect, kutu.node), gorsel
                    )
                    try:
                        sayfa.insert_image(hedef, stream=gorsel)
                    except Exception:  # noqa: BLE001 - bozuk görsel
                        pass
                continue

            alan_dikdortgen = _apply_margin(alan_dikdortgen, kutu.node)

            # Onay kutusu/radyo: XFA kutusu etiketi de kapsadığı için
            # satır boyunca uzar. Küçük bir kareye indirilir, yoksa
            # tıklama alanı metnin üzerine taşar.
            if alan_turu == "check":
                merkez_y = (alan_dikdortgen.y0 + alan_dikdortgen.y1) / 2
                kenar = min(_TOGGLE_SIZE, alan_dikdortgen.height or _TOGGLE_SIZE)
                alan_dikdortgen = fitz.Rect(
                    alan_dikdortgen.x0, merkez_y - kenar / 2,
                    alan_dikdortgen.x0 + kenar, merkez_y + kenar / 2,
                )
            else:
                _draw_borders(sayfa, alan_dikdortgen, kutu.node)

            _add_widget(
                sayfa, alan_dikdortgen, kutu.node, kutu.path,
                degerler.get(kutu.path, ""),
            )

    return doc


def render_bytes(template: bytes, values: dict[str, str] | None = None,
                 show_hidden: bool = False) -> bytes:
    """:func:`render` sonucunu bayt olarak verir."""
    doc = render(template, values, show_hidden=show_hidden)
    try:
        return doc.tobytes(deflate=True, garbage=3)
    finally:
        doc.close()
