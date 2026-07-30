"""XFA şablonunu **canlı** bir HTML formuna derler.

Neden HTML
----------
:mod:`app.core.xfa_render` şablonun tek bir anlık görüntüsünü PDF'e çizer.
Dinamik XFA formları ise betikle yaşar: bir radyo düğmesi seçilince bölümler
açılır, tablolara satır eklenir, listeler ülkeye göre doldurulur. Bunları
çizmek değil **çalıştırmak** gerekir.

Şablondaki betikler zaten JavaScript'tir (``application/x-javascript``); bu
belgede 190 KB'lık ``LAYOUT_FUNCTIONS`` kütüphanesi de öyle. Bu yüzden şablon
HTML'e çevrilir ve gerçek bir JS motorunda (Qt WebEngine) çalıştırılır:
Foxit/Adobe'deki davranışın tamamı — koşullu bölümler, doğrulamalar, açılır
liste doldurma, satır ekleme/silme — olduğu gibi işler.

Yerleşim eşlemesi
-----------------
XFA kutu modeli CSS'e birebir oturur:

``position`` (varsayılan)
    Kap ``position: relative``, çocuklar ``position: absolute`` (x/y).
``tb`` / ``table``
    Normal akış (blok); çocuk ``x``'i sol boşluk olur. Bir bölüm gizlenince
    tarayıcı geri kalanı kendiliğinden yukarı çeker — dinamik formun can alıcı
    davranışı bedavaya gelir.
``row``
    ``display: flex``.

Ölçüler punto (``pt``) olarak yazılır; CSS punto = 1/72 inç, XFA punto da öyle.

Bu modül yalnızca **derler**. Nesne modeli, olay gönderimi ve sayfalama
:mod:`app.core.xfa_runtime` içindeki JS çalışma zamanındadır.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field as dataclass_field
from xml.etree import ElementTree as ET

from .xfa import _local
from .xfa_render import parse_measure

#: 1 mm kaç punto
_MM = 72.0 / 25.4

#: XFA'da yazı tipi belirtilmemişse kullanılan punto (XFA 3.3 varsayılanı)
DEFAULT_FONT_SIZE = 10.0

#: XFA yazı tipi -> tarayıcıda bulunabilecek karşılığı. Myriad Pro kurulu
#: olmadığı için ölçüleri en yakın olan yaygın fontlara düşülür.
#: Şablonun ``typeface`` adı -> CSS yığını. İlk sıra her zaman ailenin kendi
#: adıdır: belge yazı tipini gömmüşse (bkz. ``xfa.embedded_font_css``) sayfa
#: onu kullanır, gömmemişse yığındaki en yakın sistem ailesine düşer.
#: Yedekler *metrik olarak yakın* seçilmelidir; Myriad Pro yerine Arial
#: konunca satırlar ~%6 uzuyor ve etiketler sarıp taşıyordu.
_TYPEFACE_CSS = {
    "myriad pro": "'Myriad Pro', 'Segoe UI', Candara, Arial, sans-serif",
    "courier new": "'Courier New', monospace",
    "courier std": "'Courier New', monospace",
    "times new roman": "'Times New Roman', serif",
    "arial": "Arial, Helvetica, sans-serif",
    "helvetica": "Arial, Helvetica, sans-serif",
    "verdana": "Verdana, sans-serif",
    "tahoma": "Tahoma, sans-serif",
    "calibri": "Calibri, sans-serif",
    "wingdings": "'Wingdings', sans-serif",
}

#: Kap sayılan düğümler
_CONTAINERS = ("subform", "subformSet", "exclGroup", "area")
#: Yaprak (çizilen) düğümler
_LEAVES = ("draw", "field")

#: XFA arayüz düğümü -> HTML denetimi
_UI_HTML = {
    "textEdit": "text",
    "numericEdit": "number",
    "dateTimeEdit": "date",
    "passwordEdit": "password",
    "checkButton": "check",
    "choiceList": "choice",
    "button": "button",
    "signature": "signature",
    "imageEdit": "image",
    "barcode": "barcode",
}

_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}

#: Zengin metinde başka bir alanın değerini gömen öznitelik
_EMBED_ATTR = "{http://www.xfa.org/schema/xfa-data/1.0/}embed"


def esc(text: str) -> str:
    return "".join(_ESCAPE.get(k, k) for k in str(text))


def _pt(value: float) -> str:
    return f"{value:.3f}pt"


# ======================================================================
# Küçük çözümleyiciler
# ======================================================================
def _child(node: ET.Element, tag: str) -> ET.Element | None:
    for cocuk in node:
        if _local(cocuk.tag) == tag:
            return cocuk
    return None


def _children(node: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in node if _local(c.tag) == tag]


def _color(node: ET.Element | None, default: str | None = None) -> str | None:
    """``<color value="r,g,b"/>`` -> ``#rrggbb``."""
    if node is None:
        return default
    renk = _child(node, "color")
    if renk is None:
        return default
    parcalar = (renk.get("value") or "").split(",")
    if len(parcalar) != 3:
        return default
    try:
        r, g, b = (min(max(int(p), 0), 255) for p in parcalar)
    except ValueError:
        return default
    return f"#{r:02x}{g:02x}{b:02x}"


def _text_value(node: ET.Element | None) -> str:
    """``<value><text>`` / ``<exData>`` içindeki düz metin."""
    if node is None:
        return ""
    deger = _child(node, "value")
    if deger is None:
        return ""
    for icerik in deger:
        etiket = _local(icerik.tag)
        if etiket == "text":
            return (icerik.text or "").strip()
        if etiket == "exData":
            # Zengin metin (XHTML): satır sonlarını koruyup etiketleri at.
            return _rich_text(icerik)
        if etiket in ("integer", "decimal", "float", "date", "dateTime", "time"):
            return (icerik.text or "").strip()
    return ""


def _rich_text(node: ET.Element) -> str:
    """``exData`` içindeki XHTML'i düz metne indirger (``<br>`` -> satır sonu)."""
    parcalar: list[str] = []

    def gez(dugum) -> None:
        for alt in dugum:
            etiket = _local(alt.tag)
            if etiket == "br":
                parcalar.append("\n")
            if alt.text:
                parcalar.append(alt.text)
            gez(alt)
            if etiket in ("p", "div"):
                parcalar.append("\n")
            if alt.tail:
                parcalar.append(alt.tail)

    if node.text:
        parcalar.append(node.text)
    gez(node)
    ham = "".join(parcalar)
    ham = re.sub(r"[ \t]+", " ", ham)
    return "\n".join(s.strip() for s in ham.split("\n")).strip()


def _column_widths(node: ET.Element) -> list[float] | None:
    """``layout="table"`` alt formunun ``columnWidths`` ölçüleri (punto)."""
    ham = (node.get("columnWidths") or "").split()
    olculer = [parse_measure(p) for p in ham]
    return olculer or None


def _font_css(node: ET.Element, inherited: dict) -> tuple[str, dict]:
    """``<font>`` -> CSS bildirimleri + alt düğümlere geçecek miras."""
    yazi = _child(node, "font")
    miras = dict(inherited)
    if yazi is None:
        return "", miras

    css: list[str] = []
    tipografi = (yazi.get("typeface") or "").strip()
    if tipografi:
        aile = _TYPEFACE_CSS.get(tipografi.lower())
        if aile is None:
            aile = f"'{tipografi}', Arial, sans-serif"
        css.append(f"font-family:{aile}")
        miras["family"] = aile

    boyut = parse_measure(yazi.get("size"), 0.0)
    if boyut > 0:
        css.append(f"font-size:{_pt(boyut)}")
        miras["size"] = boyut

    agirlik = (yazi.get("weight") or "").lower()
    if agirlik:
        css.append(f"font-weight:{'bold' if agirlik == 'bold' else 'normal'}")
    if (yazi.get("posture") or "").lower() == "italic":
        css.append("font-style:italic")
    if (yazi.get("underline") or "0") not in ("0", ""):
        css.append("text-decoration:underline")

    renk = _color(yazi)
    if renk:
        css.append(f"color:{renk}")
        miras["color"] = renk
    return ";".join(css), miras


_H_ALIGN = {"left": "left", "center": "center", "right": "right",
            "justify": "justify", "justifyAll": "justify", "radix": "right"}
#: ``safe`` öneki: içerik kutudan taşarsa hizalama iptal edilip üstten
#: başlanır. Olmazsa ortalı/alta yaslı uzun metinlerin ilk satırları kırpılır.
_V_ALIGN = {"top": "flex-start", "middle": "safe center",
            "bottom": "safe flex-end"}


def _para_css(node: ET.Element) -> tuple[str, str]:
    """``<para>`` -> (metin CSS'i, flex dikey hizalaması)."""
    para = _child(node, "para")
    if para is None:
        return "", "flex-start"
    css: list[str] = []
    yatay = _H_ALIGN.get((para.get("hAlign") or "left"), "left")
    css.append(f"text-align:{yatay}")
    dikey = _V_ALIGN.get((para.get("vAlign") or "top"), "flex-start")

    sol = parse_measure(para.get("marginLeft"), 0.0)
    sag = parse_measure(para.get("marginRight"), 0.0)
    ust = parse_measure(para.get("spaceAbove"), 0.0)
    alt = parse_measure(para.get("spaceBelow"), 0.0)
    if sol or sag or ust or alt:
        css.append(
            f"padding:{_pt(ust)} {_pt(sag)} {_pt(alt)} {_pt(sol)}"
        )
    yukseklik = parse_measure(para.get("lineHeight"), 0.0)
    if yukseklik > 0:
        css.append(f"line-height:{_pt(yukseklik)}")
    return ";".join(css), dikey


def _margin_css(node: ET.Element) -> str:
    """``<margin>`` iç boşlukları -> ``padding``."""
    kenar = _child(node, "margin")
    if kenar is None:
        return ""
    return (
        f"padding:{_pt(parse_measure(kenar.get('topInset')))} "
        f"{_pt(parse_measure(kenar.get('rightInset')))} "
        f"{_pt(parse_measure(kenar.get('bottomInset')))} "
        f"{_pt(parse_measure(kenar.get('leftInset')))}"
    )


_EDGE_SIDES = ("top", "right", "bottom", "left")


def _radius_css(border: ET.Element | None) -> str:
    if border is None:
        return ""
    yuvarlak = _child(border, "corner")
    if yuvarlak is None:
        return ""
    yaricap = parse_measure(yuvarlak.get("radius"), 0.0)
    return f"border-radius:{_pt(yaricap)}" if yaricap > 0 else ""


def _fill_css(border: ET.Element | None) -> str:
    """``<border><fill>`` -> zemin rengi (öğenin kendi üzerinde durur)."""
    if border is None:
        return ""
    dolgu = _child(border, "fill")
    if dolgu is None or dolgu.get("presence") in ("hidden", "inactive"):
        return ""
    renk = _color(dolgu)
    return f"background-color:{renk}" if renk else ""


def _edge_css(border: ET.Element | None, ignore_presence: bool = False) -> str:
    """``<border><edge>`` -> kenar çizgileri.

    XFA'da tek ``edge`` dört kenara da uygulanır; dört ``edge`` varsa sıra
    **üst, sağ, alt, sol**'dur. Bu formdaki alanların çoğunda yalnızca alt
    kenar görünür — Foxit'teki alt çizgi görünümü buradan gelir.

    ``ignore_presence`` doğrulama vurgusu katmanı içindir: kenar gizli
    tanımlanmış olsa bile stili üretilir, çünkü betikler bu katmanı sonradan
    ``border.presence = "visible"`` ile açar.
    """
    if border is None:
        return ""
    kenarlar = _children(border, "edge")
    if not kenarlar:
        return ""
    if len(kenarlar) == 1:
        kenarlar = kenarlar * 4
    kenarlar = (kenarlar + kenarlar[-1:] * 4)[:4]

    css: list[str] = []
    for yan, kenar in zip(_EDGE_SIDES, kenarlar):
        if not ignore_presence and kenar.get("presence") in ("hidden", "inactive"):
            continue
        kalinlik = parse_measure(kenar.get("thickness"), 0.5)
        kalinlik = max(min(kalinlik, 3.0), 0.4)
        stil = {"dashed": "dashed", "dotted": "dotted",
                "lowered": "solid", "raised": "solid"}.get(
            (kenar.get("stroke") or "solid"), "solid")
        css.append(f"border-{yan}:{_pt(kalinlik)} {stil} {_color(kenar, '#595959')}")
    return ";".join(css)


def _overlay(border: ET.Element | None) -> str:
    """Kenarlık katmanı (``.xhl``); kenar tanımı yoksa boş dize.

    Katman, kenarlar gizli tanımlanmış olsa bile üretilir: doğrulama betikleri
    (``RULES.checkRules``) hatalı alanları ``border.presence = "visible"`` ile
    kırmızı çerçeveye alır, ``LAYOUT_FUNCTIONS.clearErrors`` ise geri kapatır.
    """
    if border is None or not _children(border, "edge"):
        return ""
    kenarlar = _edge_css(border, ignore_presence=True)
    if not kenarlar:
        return ""
    gorunur = (
        border.get("presence") not in ("hidden", "inactive", "invisible")
        and any(k.get("presence") not in ("hidden", "inactive")
                for k in _children(border, "edge"))
    )
    varlik = "visible" if gorunur else "hidden"
    gizle = "" if gorunur else ";display:none"
    return (f'<div class="xhl" data-presence="{varlik}" '
            f'style="{kenarlar};{_radius_css(border)}{gizle}"></div>')


def _ui_node(node: ET.Element) -> tuple[str, ET.Element | None]:
    """Alanın (arayüz türü, arayüz düğümü) çifti."""
    arayuz = _child(node, "ui")
    if arayuz is None:
        return "text", None
    for torun in arayuz:
        tur = _UI_HTML.get(_local(torun.tag))
        if tur:
            return tur, torun
    return "text", None


def _items(node: ET.Element) -> list[tuple[str, str]]:
    """``<items>`` -> (gösterilen, kaydedilen) çiftleri."""
    gorunen: list[str] = []
    kaydedilen: list[str] = []
    for cocuk in _children(node, "items"):
        degerler = [(t.text or "").strip() for t in cocuk
                    if _local(t.tag) in ("text", "integer", "decimal")]
        if cocuk.get("save") == "1":
            kaydedilen = degerler
        else:
            gorunen = degerler
    if not gorunen:
        gorunen = kaydedilen
    if not kaydedilen:
        kaydedilen = gorunen
    return list(zip(gorunen, kaydedilen))


def _image_data(node: ET.Element) -> str:
    """``<value><image>`` -> ``data:`` adresi (bulunamazsa boş dize)."""
    deger = _child(node, "value")
    if deger is None:
        return ""
    gorsel = _child(deger, "image")
    if gorsel is None or not (gorsel.text or "").strip():
        return ""
    ham = re.sub(r"\s+", "", (gorsel.text or "").strip())
    tur = (gorsel.get("contentType") or "").strip()
    if not tur:
        try:
            bayt = base64.b64decode(ham[:64] + "=" * (-len(ham[:64]) % 4))
        except (binascii.Error, ValueError):
            bayt = b""
        if bayt.startswith(b"\x89PNG"):
            tur = "image/png"
        elif bayt.startswith(b"GIF"):
            tur = "image/gif"
        elif bayt.startswith(b"\xff\xd8"):
            tur = "image/jpeg"
        else:
            tur = "image/png"
    return f"data:{tur};base64,{ham}"


def _tooltip(node: ET.Element) -> str:
    yardim = _child(node, "assist")
    if yardim is None:
        return ""
    for cocuk in yardim:
        if _local(cocuk.tag) in ("toolTip", "speak"):
            return (cocuk.text or "").strip()
    return ""


# ======================================================================
# Derleyici
# ======================================================================
@dataclass
class Compiled:
    """Derlenmiş form: tam HTML belgesi ve özet bilgiler."""

    html: str
    root: str = "form"
    field_count: int = 0
    script_count: int = 0
    page_size: tuple[float, float] = (595.28, 841.89)
    #: Şablonda çözümlenemeyen düğümler (tanı için)
    warnings: list[str] = dataclass_field(default_factory=list)


class _Compiler:
    def __init__(self, root: ET.Element, values: dict[str, str]) -> None:
        self.root = root
        self.values = values
        self.scripts: list[dict] = []
        self.variables: list[dict] = []
        self.field_count = 0
        self.warnings: list[str] = []
        #: İçinde bulunulan ``layout="table"`` alt formunun sütun genişlikleri.
        #: Satır hücreleri kendi ``w``leri yerine bunları kullanır.
        self._cols: list[float] | None = None
        #: ``pageArea`` içindeki sayaç alanlarının ``id`` -> ``ad`` eşlemesi.
        #: Altbilgi metni bunlara ``xfa:embed`` ile atıfta bulunur; bu yüzden
        #: çizimler derlenmeden **önce** toplanır.
        self.counter_ids: dict[str, str] = {}
        for sayfa in root.iter():
            if _local(sayfa.tag) != "pageArea":
                continue
            for cocuk in sayfa:
                if _local(cocuk.tag) == "field" and cocuk.get("id"):
                    self.counter_ids[cocuk.get("id")] = cocuk.get("name") or ""
            break

    # -- sayfa ölçüleri -------------------------------------------------
    def page_geometry(self) -> tuple[tuple[float, float], tuple[float, float, float, float]]:
        genis, yuksek = 210 * _MM, 297 * _MM
        for dugum in self.root.iter():
            if _local(dugum.tag) == "medium":
                genis = parse_measure(dugum.get("short"), genis)
                yuksek = parse_measure(dugum.get("long"), yuksek)
                if dugum.get("orientation") == "landscape":
                    genis, yuksek = yuksek, genis
                break
        alan = (10 * _MM, 10 * _MM, genis - 20 * _MM, yuksek - 20 * _MM)
        for dugum in self.root.iter():
            if _local(dugum.tag) == "contentArea":
                alan = (
                    parse_measure(dugum.get("x"), alan[0]),
                    parse_measure(dugum.get("y"), alan[1]),
                    parse_measure(dugum.get("w"), alan[2]),
                    parse_measure(dugum.get("h"), alan[3]),
                )
                break
        return (genis, yuksek), alan

    # -- betikler -------------------------------------------------------
    def collect_variables(self) -> None:
        """``<variables>`` altındaki JS kütüphanelerini toplar.

        XFA'da bunlar ad alanı nesnesi olur (``LAYOUT_FUNCTIONS.populate_*``);
        çalışma zamanı aynı adla bir nesne kurar.
        """
        for dugum in self.root.iter():
            if _local(dugum.tag) != "variables":
                continue
            for betik in dugum:
                if _local(betik.tag) != "script" or not (betik.text or "").strip():
                    continue
                self.variables.append(
                    {"name": betik.get("name") or "vars", "code": betik.text}
                )

    def collect_events(self, node: ET.Element, som: str) -> None:
        for olay in _children(node, "event"):
            betik = _child(olay, "script")
            if betik is None or not (betik.text or "").strip():
                continue
            tur = (betik.get("contentType") or "application/x-javascript").lower()
            self.scripts.append({
                "som": som,
                "activity": olay.get("activity") or "click",
                "ref": olay.get("ref") or "",
                "lang": "formcalc" if "formcalc" in tur else "js",
                "code": betik.text,
            })
        # <calculate>/<validate> kendi betiklerini taşır.
        for etiket, aktivite in (("calculate", "calculate"), ("validate", "validate")):
            hesap = _child(node, etiket)
            if hesap is None:
                continue
            betik = _child(hesap, "script")
            if betik is None or not (betik.text or "").strip():
                continue
            tur = (betik.get("contentType") or "application/x-javascript").lower()
            self.scripts.append({
                "som": som,
                "activity": aktivite,
                "ref": "",
                "lang": "formcalc" if "formcalc" in tur else "js",
                "code": betik.text,
            })

    # -- kutu konumu ----------------------------------------------------
    def _box_style(self, node: ET.Element, parent_layout: str,
                   default_w: float | None, col_w: float | None = None) -> str:
        x = parse_measure(node.get("x"))
        y = parse_measure(node.get("y"))
        w = parse_measure(node.get("w"))
        h = parse_measure(node.get("h"))
        css: list[str] = []

        # Tablo hücresi: genişliği ``columnWidths`` belirler, hücrenin kendi
        # ``w``si değil. Şablonlar hücreye tasarım aracından kalma dar bir
        # ``w`` bırakır (ör. 30mm), gerçek sütun 175mm'dir; sütun yok
        # sayılınca tablo başlıkları ile satırlar birbirinden kayıyordu.
        if col_w:
            olcu = _pt(col_w)
            genislik = f"flex:0 0 {olcu};width:{olcu};max-width:{olcu};min-width:0"
            if h:
                genislik += f";min-height:{_pt(h)}"
            return f"position:relative;{genislik}"

        if parent_layout in ("tb", "table"):
            css.append("position:relative")
            if x:
                css.append(f"margin-left:{_pt(x)}")
            css.append(f"width:{_pt(w) if w else '100%'}")
            if h:
                # Akıştaki kaplar büyüyebilmeli: yükseklik alt sınırdır.
                css.append(f"min-height:{_pt(h)}")
        elif parent_layout == "row":
            # ``0 1 auto``: hücreler bildirilen genişliği korur ama satır
            # taşarsa büzülür. Sabitlenirse satır sayfa kenarını aşıyor.
            css.append("position:relative;flex:0 1 auto;min-width:0")
            if y:
                css.append(f"margin-top:{_pt(y)}")
            css.append(f"width:{_pt(w)}" if w else "flex:1 1 auto")
            if h:
                css.append(f"min-height:{_pt(h)}")
        else:                                   # position
            css.append(f"position:absolute;left:{_pt(x)};top:{_pt(y)}")
            if w:
                css.append(f"width:{_pt(w)}")
            elif default_w:
                css.append(f"width:{_pt(default_w)}")
            if h:
                css.append(f"height:{_pt(h)}")
        return ";".join(css)

    def _container_style(self, node: ET.Element, layout: str) -> str:
        """Kabın **kendi içi** için düzen CSS'i.

        ``position`` düzeninde hiçbir şey yazılmaz: kabın kendi konumu
        :meth:`_box_style` tarafından belirlenmiştir ve buradan bir
        ``position`` bildirimi onu ezerdi.
        """
        if layout == "row":
            return "display:flex;align-items:flex-start;max-width:100%"
        if layout in ("tb", "table"):
            return "display:block"
        return ""

    # -- düğüm derleme ---------------------------------------------------
    def compile_node(self, node: ET.Element, parent_layout: str, som: str,
                     inherited: dict, default_w: float | None = None,
                     col_w: float | None = None) -> str:
        etiket = _local(node.tag)
        if etiket in _CONTAINERS:
            return self._container(node, parent_layout, som, inherited,
                                   default_w, col_w)
        if etiket == "field":
            return self._field(node, parent_layout, som, inherited,
                               default_w, col_w)
        if etiket == "draw":
            return self._draw(node, parent_layout, som, inherited,
                              default_w, col_w)
        return ""

    def _presence_attrs(self, node: ET.Element) -> tuple[str, str]:
        varlik = node.get("presence") or "visible"
        gizle = ";display:none" if varlik in ("hidden", "inactive") else ""
        if varlik == "invisible":
            gizle = ";visibility:hidden"
        return varlik, gizle

    def _container(self, node: ET.Element, parent_layout: str, som: str,
                   inherited: dict, default_w: float | None,
                   col_w: float | None = None) -> str:
        etiket = _local(node.tag)
        ad = node.get("name") or ""
        yeni_som = f"{som}.{ad}" if ad else som
        duzen = (node.get("layout") or "position").lower()
        varlik, gizle = self._presence_attrs(node)

        yazi_css, miras = _font_css(node, inherited)
        kutu = self._box_style(node, parent_layout, default_w, col_w)
        ic = self._container_style(node, duzen)
        kenarlik = _child(node, "border")
        dolgu = _fill_css(kenarlik)
        katman = _overlay(kenarlik)

        genislik = col_w or parse_measure(node.get("w")) or default_w

        # Sütun bağlamı: satırın hücreleri kapsayan tablonun sütunlarını
        # kullanır; hücrenin *içindeki* iç içe tablolar kendi sütunlarını
        # kurar, o yüzden bağlam iniş sırasında kaydedilip geri alınır.
        disaridaki = self._cols
        self._cols = _column_widths(node) if duzen == "table" else None
        sutunlar = disaridaki if duzen == "row" else None

        parcalar: list[str] = []
        sutun = 0
        for cocuk in node:
            if _local(cocuk.tag) not in _CONTAINERS + _LEAVES:
                continue
            hucre_g = None
            if sutunlar and sutun < len(sutunlar):
                kapsam = int(cocuk.get("colSpan") or 1)
                if kapsam < 0:                  # -1: satırın kalan sütunları
                    kapsam = len(sutunlar) - sutun
                hucre_g = sum(sutunlar[sutun:sutun + kapsam]) or None
                sutun += max(kapsam, 1)
            parcalar.append(
                self.compile_node(cocuk, duzen, yeni_som, miras, genislik, hucre_g)
            )
        self._cols = disaridaki

        self.collect_events(node, yeni_som)

        # Yinelenebilir kap (``<occur max>``): çalışma zamanı örnek ekleyip
        # silebilsin diye kalıp olarak işaretlenir.
        tekrar = ""
        occur = _child(node, "occur")
        if occur is not None:
            en_cok = occur.get("max") or "1"
            if en_cok != "1":
                tekrar = (f' data-repeat="1" data-min="{esc(occur.get("min") or "1")}"'
                          f' data-max="{esc(en_cok)}"')

        kirilma = ' data-break="1"' if _child(node, "breakBefore") is not None else ""
        sinif = "xg" if etiket == "exclGroup" else "xs"
        return (
            f'<div class="{sinif}" data-som="{esc(yeni_som)}" data-name="{esc(ad)}"'
            f' data-kind="{etiket}" data-layout="{duzen}" data-presence="{varlik}"'
            f'{tekrar}{kirilma}'
            f' style="{kutu};{ic};{dolgu};{yazi_css}{gizle}">'
            + katman + "".join(parcalar) +
            "</div>"
        )

    # -- alan ------------------------------------------------------------
    def _field(self, node: ET.Element, parent_layout: str, som: str,
               inherited: dict, default_w: float | None,
               col_w: float | None = None) -> str:
        ad = node.get("name") or ""
        yeni_som = f"{som}.{ad}" if ad else som
        self.field_count += 1
        self.collect_events(node, yeni_som)

        varlik, gizle = self._presence_attrs(node)
        yazi_css, miras = _font_css(node, inherited)
        kutu = self._box_style(node, parent_layout, default_w, col_w)
        ic_bosluk = _margin_css(node)
        metin_css, dikey = _para_css(node)

        tur, arayuz = _ui_node(node)
        deger = self.values.get(yeni_som, "") or _initial_value(node, tur)
        secenekler = _items(node)
        kenarlik = _child(node, "border")

        # Etiket. Düğmelerde etiket ayrı bir sütun değil, düğmenin **içidir**;
        # ayrı çizilirse metin düğmenin yanına düşer ve üstüne biner.
        if tur == "button":
            etiket_html, etiket_yon = "", "left"
        else:
            etiket_html, etiket_yon = self._caption(node, miras)

        # Denetim
        denetim = self._control(node, yeni_som, tur, arayuz, deger, secenekler,
                                miras, metin_css, dikey)

        ui_kenarlik = _child(arayuz, "border") if arayuz is not None else None
        # Onay kutusunun çerçevesini denetimin kendisi çizer (yuvarlaksa daire
        # olarak). Hücreye de çizilirse dairenin çevresinde ikinci bir kare
        # beliriyor; Foxit/Adobe tek çerçeve gösterir.
        ui_cerceve = ("" if tur == "check"
                      else f"{_edge_css(ui_kenarlik)};{_fill_css(ui_kenarlik)}")
        katman = _overlay(kenarlik)
        alan_dolgu = _fill_css(kenarlik)
        if alan_dolgu:
            alan_dolgu += ";" + _radius_css(kenarlik)

        yon = {"left": "row", "right": "row-reverse",
               "top": "column", "bottom": "column-reverse"}.get(etiket_yon, "row")

        ipucu = _tooltip(node)
        ipucu_attr = f' title="{esc(ipucu)}"' if ipucu else ""

        salt = ' data-readonly="1"' if (node.get("access") or "") in (
            "readOnly", "protected", "nonInteractive") else ""

        return (
            f'<div class="xf" data-som="{esc(yeni_som)}" data-name="{esc(ad)}"'
            f' data-kind="field" data-type="{tur}" data-presence="{varlik}"{salt}'
            f'{ipucu_attr} style="{kutu};{alan_dolgu};{yazi_css}{gizle}">'
            f'{katman}'
            f'<div class="xf-in" style="flex-direction:{yon};{ic_bosluk}">'
            f'{etiket_html}'
            f'<div class="xw" style="{ui_cerceve};align-items:{dikey}">{denetim}</div>'
            f'</div></div>'
        )

    def _caption(self, node: ET.Element, inherited: dict) -> tuple[str, str]:
        etiket = _child(node, "caption")
        if etiket is None:
            return "", "left"
        yer = (etiket.get("placement") or "left").lower()
        if etiket.get("presence") in ("hidden", "inactive", "invisible"):
            return "", yer
        metin = _text_value(etiket)
        ayrilan = parse_measure(etiket.get("reserve"), 0.0)
        if not metin and not ayrilan:
            return "", yer

        yazi_css, _ = _font_css(etiket, inherited)
        metin_css, dikey = _para_css(etiket)
        olcu = (f"flex:0 0 {_pt(ayrilan)}" if ayrilan else "flex:0 0 auto")
        if yer in ("top", "bottom"):
            olcu = f"flex:0 0 {_pt(ayrilan)}" if ayrilan else "flex:0 0 auto"
        return (
            f'<div class="xcap" style="{olcu};align-items:{dikey};'
            f'{yazi_css};{metin_css}"><span>{esc(metin).replace(chr(10), "<br>")}'
            f'</span></div>',
            yer,
        )

    def _control(self, node: ET.Element, som: str, tur: str,
                 arayuz: ET.Element | None, deger: str,
                 secenekler: list[tuple[str, str]], inherited: dict,
                 metin_css: str, dikey: str) -> str:
        ortak = (f'data-som="{esc(som)}" class="xc" '
                 f'style="{metin_css};font:inherit;color:inherit"')

        if tur == "check":
            yuvarlak = (arayuz is not None
                        and (arayuz.get("shape") or "square").lower() == "round")
            acik = secenekler[0][1] if secenekler else "1"
            isaretli = " checked" if deger and deger == acik else ""
            sinif = "xchk round" if yuvarlak else "xchk"
            return (f'<input type="checkbox" class="{sinif}" data-som="{esc(som)}"'
                    f' data-on="{esc(acik)}"{isaretli}>')

        if tur == "choice":
            coklu = False
            if arayuz is not None:
                coklu = (arayuz.get("open") or "") == "multiSelect"
            satirlar = "".join(
                f'<option value="{esc(k)}"'
                f'{" selected" if deger and k == deger else ""}>{esc(g)}</option>'
                for g, k in secenekler
            )
            bos = '<option value=""></option>'
            return (f'<select {ortak}{" multiple" if coklu else ""}>'
                    f'{bos}{satirlar}</select>')

        if tur == "button":
            etiket = _child(node, "caption")
            metin = _text_value(etiket) if etiket is not None else ""
            gorsel = _image_data(node)
            yazi_css, _ = _font_css(etiket, inherited) if etiket is not None else ("", {})
            ic = (f'<img src="{gorsel}" alt="">' if gorsel else esc(metin))
            return (f'<button type="button" data-som="{esc(som)}" class="xc xbtn"'
                    f' style="{metin_css};{yazi_css}">{ic}</button>')

        if tur in ("image", "signature"):
            gorsel = _image_data(node)
            if gorsel:
                return (f'<img class="ximg" data-som="{esc(som)}" src="{gorsel}"'
                        f' alt="">')
            return f'<div class="xstub" data-som="{esc(som)}"></div>'

        if tur == "barcode":
            return f'<div class="xstub" data-som="{esc(som)}">{esc(deger)}</div>'

        # Metin türevleri
        cok_satir = (arayuz is not None
                     and (arayuz.get("multiLine") or "0") not in ("0", ""))
        en_cok = ""
        deger_dugum = _child(node, "value")
        if deger_dugum is not None:
            metin_dugum = _child(deger_dugum, "text")
            if metin_dugum is not None and metin_dugum.get("maxChars"):
                en_cok = f' maxlength="{esc(metin_dugum.get("maxChars"))}"'

        if cok_satir:
            return (f'<textarea {ortak}{en_cok}>{esc(deger)}</textarea>')

        html_turu = {"number": "text", "date": "date",
                     "password": "password"}.get(tur, "text")
        ek = ""
        if tur == "number":
            ek = ' inputmode="decimal" data-numeric="1"'
        elif tur == "date":
            # Tarayıcının tarih denetimi ISO değer üretir; şablon betikleri de
            # ``rawValue``ı YYYY-MM-DD bekliyor (bkz. RegDate/exit betiği).
            ek = ' data-date="1"'
        return (f'<input type="{html_turu}" {ortak}{en_cok}{ek}'
                f' value="{esc(deger)}">')

    # -- çizim -----------------------------------------------------------
    def _draw(self, node: ET.Element, parent_layout: str, som: str,
              inherited: dict, default_w: float | None,
              col_w: float | None = None) -> str:
        ad = node.get("name") or ""
        yeni_som = f"{som}.{ad}" if ad else som
        varlik, gizle = self._presence_attrs(node)
        yazi_css, _ = _font_css(node, inherited)
        kutu = self._box_style(node, parent_layout, default_w, col_w)
        kenarlik = _child(node, "border")
        dolgu = _fill_css(kenarlik)
        katman = _overlay(kenarlik)
        ic_bosluk = _margin_css(node)
        metin_css, dikey = _para_css(node)

        gorsel = _image_data(node)
        if gorsel:
            ic = f'<img src="{gorsel}" alt="">'
            sinif = "xd ximgbox"
        else:
            gomulu = self._embedded_html(node)
            if gomulu is not None:
                ic = f"<span>{gomulu}</span>"
            else:
                metin = _text_value(node)
                ic = f'<span>{esc(metin).replace(chr(10), "<br>")}</span>'
            sinif = "xd"

        return (
            f'<div class="{sinif}" data-som="{esc(yeni_som)}" data-name="{esc(ad)}"'
            f' data-kind="draw" data-presence="{varlik}"'
            f' style="{kutu};{dolgu};{yazi_css}{gizle}">'
            f'{katman}'
            f'<div class="xd-in" style="{ic_bosluk};align-items:{dikey};'
            f'{metin_css}">{ic}</div></div>'
        )

    def _embedded_html(self, node: ET.Element) -> str | None:
        """``xfa:embed`` başvurularını yerine konabilir aralıklara çevirir.

        Altbilgi ``Page <embed CurrentPage> of <embed PageCount>`` biçiminde
        yazılmıştır; değerler betikle hesaplandığı için çalışma zamanı bu
        aralıkları sayfa numarasıyla doldurur. Çevrilmezse sayfada
        "Page of" yazar.
        """
        deger = _child(node, "value")
        if deger is None:
            return None
        veri = _child(deger, "exData")
        if veri is None:
            return None
        if not any(alt.get(_EMBED_ATTR) for alt in veri.iter()):
            return None

        parcalar: list[str] = []

        def gez(dugum) -> None:
            for alt in dugum:
                kimlik = alt.get(_EMBED_ATTR)
                if kimlik:
                    ad = self.counter_ids.get(kimlik.lstrip("#"), "")
                    parcalar.append(f'<span data-embed="{esc(ad)}"></span>')
                if _local(alt.tag) == "br":
                    parcalar.append("<br>")
                if alt.text:
                    parcalar.append(esc(alt.text))
                gez(alt)
                if alt.tail:
                    parcalar.append(esc(alt.tail))

        if veri.text:
            parcalar.append(esc(veri.text))
        gez(veri)
        return "".join(parcalar).strip()

    # -- sayfa süslemeleri -----------------------------------------------
    def page_furniture(self) -> tuple[str, dict[str, str]]:
        """``pageArea`` çizimleri + sayfa sayacı alanlarının kimlikleri."""
        parcalar: list[str] = []
        for sayfa in self.root.iter():
            if _local(sayfa.tag) != "pageArea":
                continue
            for cocuk in sayfa:
                if _local(cocuk.tag) in ("field", "draw", "subform", "area"):
                    parcalar.append(
                        self.compile_node(cocuk, "position", "page", {}, None)
                    )
            break                       # tek ana sayfa şablonu
        return "".join(parcalar), self.counter_ids


def _initial_value(node: ET.Element, tur: str) -> str:
    """Şablondaki başlangıç değeri.

    Onay kutularında ``<value>`` mevcut durum **değil**, kutu işaretlenince
    kaydedilecek "açık değeri"dir; durum sayılırsa boş form bile bütün
    kutuları işaretli açar.
    """
    if tur == "check":
        return ""
    return _text_value(node)


# ======================================================================
# CSS
# ======================================================================
_CSS = """
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:#f2f3f7;
  font-family:Arial,Helvetica,sans-serif;font-size:__BASE__pt;color:#000}
#doc{padding:16pt 0 24pt;display:flex;flex-direction:column;align-items:center}
#stage{transform-origin:top center}
#pages{position:relative;width:__PW__pt}
#pagebg{position:absolute;inset:0}
.page{position:relative;width:__PW__pt;height:__PH__pt;background:#fff;
  box-shadow:0 1px 6px rgba(0,0,0,.25);margin:0 auto 14pt;overflow:hidden}
.pagebg{position:absolute;inset:0;pointer-events:none}
.pagebg .xf,.pagebg .xd{pointer-events:none}
.clip{position:absolute;left:__CX__pt;top:__CY__pt;
  width:__CW__pt;height:__CH__pt;overflow:hidden}
#flow{position:absolute;left:0;top:0;width:__CW__pt}
.xs,.xg{}
.xd{overflow:hidden}
.xd-in{display:flex;width:100%;height:100%;white-space:pre-wrap;
  line-height:1.18;word-break:break-word}
.xd-in>span{display:block;width:100%}
.ximgbox .xd-in{align-items:flex-start!important;justify-content:center}
.ximgbox img{max-width:100%;max-height:100%;object-fit:contain}
.xf{overflow:visible}
.xf-in{display:flex;width:100%;height:100%;gap:0}
.xcap{display:flex;overflow:hidden;line-height:1.15;word-break:break-word}
.xcap>span{display:block;width:100%}
.xw{display:flex;flex:1 1 auto;min-width:0;position:relative}
.xc{width:100%;border:0;background:transparent;outline:none;padding:0;
  font:inherit;color:inherit;line-height:1.2}
input.xc{height:100%;min-height:1.2em}
textarea.xc{height:100%;resize:none;overflow:auto}
select.xc{height:100%;cursor:pointer;-webkit-appearance:none;appearance:none;
  padding-right:11pt;
  background-image:linear-gradient(45deg,transparent 50%,#5a6070 50%),
    linear-gradient(135deg,#5a6070 50%,transparent 50%);
  background-position:calc(100% - 6pt) calc(50% - 1pt),
    calc(100% - 3pt) calc(50% - 1pt);
  background-size:3pt 3pt,3pt 3pt;background-repeat:no-repeat}
.xc:focus{background:#fffbe6}
.xw:focus-within{outline:1px solid #2f6fd0;outline-offset:0}
/* Kutu ve düğmeler işletim sisteminin kalın denetimleriyle değil, Foxit/Adobe
   gibi ince çerçeve + siyah işaretle çizilir; yerel denetim etiketle arasındaki
   boşluğu yiyor ve satırı şişiriyordu. */
input.xchk{-webkit-appearance:none;appearance:none;flex:0 0 auto;
  align-self:center;width:8.5pt;height:8.5pt;margin:0;cursor:pointer;
  position:relative;border:0.6pt solid #55585f;background:#fff}
input.xchk:checked::after{content:'';position:absolute;left:2.7pt;top:0.5pt;
  width:2.6pt;height:5.4pt;border:solid #111;border-width:0 1.1pt 1.1pt 0;
  transform:rotate(42deg)}
/* ``checkButton shape="round"`` = birbirini dışlayan seçim; kare çizilirse
   kullanıcı birden çok seçenek işaretlenebilir sanır. */
input.xchk.round{border-radius:50%}
input.xchk.round:checked::after{left:1.9pt;top:1.9pt;width:3.9pt;height:3.9pt;
  border:0;border-radius:50%;background:#111;transform:none}
button.xbtn{cursor:pointer;background:transparent;border:0;border-radius:inherit;
  height:100%;width:100%;padding:0 1pt;font:inherit;color:inherit;
  display:flex;align-items:center;white-space:nowrap;overflow:hidden}
.xf:has(> .xf-in > .xw > button.xbtn):hover{filter:brightness(1.08)}
button.xbtn img{max-height:100%;max-width:100%}
input.xc[type=date]{padding:0}
input.xc[type=date]::-webkit-calendar-picker-indicator{padding:0;margin:0;
  opacity:.55;cursor:pointer}
.ximg{max-width:100%;max-height:100%;object-fit:contain}
.xstub{width:100%;height:100%}
.xhl{position:absolute;inset:0;pointer-events:none;z-index:3}
/* Doldurulabilir alan zemini: Foxit/Adobe'deki mavimsi vurgunun karşılığı */
.xw:has(> input.xc),.xw:has(> textarea.xc),.xw:has(> select.xc)
  {background-color:#e8ecf9}
body.nohl .xw:has(> input.xc),body.nohl .xw:has(> textarea.xc),
body.nohl .xw:has(> select.xc){background-color:transparent}
.xreq{outline:1.2pt solid #d33!important}
#toast{position:fixed;left:50%;bottom:18pt;transform:translateX(-50%);
  background:#25272e;color:#fff;padding:7pt 12pt;border-radius:4pt;
  font-size:9pt;opacity:0;transition:opacity .18s;pointer-events:none;z-index:99}
#toast.on{opacity:.96}
/* Yazdırma kipi: sayfa çerçeveleri gölgesiz ve boşluksuz durur; yerleşim
   Chromium'un A4 kutularıyla birebir örtüşsün (bkz. XFA.prepareForPrint). */
body.printing{background:#fff}
body.printing #doc{padding:0}
body.printing .page{box-shadow:none}
body.printing .xc:focus{background:transparent}
/* Sayfa kutusu şablonun ölçüsüyle birebir tanımlanır. Tanımlanmazsa Chromium
   varsayılan sayfaya göre "sığdırmak için" içeriği hafifçe küçültür; her
   sayfada biriken bu kayma altbilgileri sonraki sayfanın tepesine taşır. */
@page{size:__PW__pt __PH__pt;margin:0}
@media print{
  html,body{background:#fff}
  #doc{padding:0}
  .page{box-shadow:none;margin:0}
  .xc:focus{background:transparent}
  *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""


# ======================================================================
# Genel arayüz
# ======================================================================
def compile_template(template: bytes, values: dict[str, str] | None = None,
                     runtime_js: str | None = None,
                     font_css: str = "") -> Compiled:
    """XFA şablonunu tek parça, kendi kendine yeten bir HTML belgesine derler.

    ``font_css``: belgeye gömülü yazı tiplerinin ``@font-face`` kuralları
    (bkz. :func:`app.core.xfa.embedded_font_css`). Verilmezse sayfa sistem
    yazı tiplerine düşer ve metin genişlikleri Foxit/Adobe'den sapar.
    """
    if not template:
        raise ValueError("XFA şablonu boş")
    if runtime_js is None:
        from .xfa_runtime import RUNTIME_JS
        runtime_js = RUNTIME_JS
    kok = ET.fromstring(template)

    derleyici = _Compiler(kok, values or {})
    derleyici.collect_variables()
    (sayfa_g, sayfa_y), (ca_x, ca_y, ca_w, ca_h) = derleyici.page_geometry()

    sayfa_susleri, sayaclar = derleyici.page_furniture()

    kok_sf = next((c for c in kok if _local(c.tag) == "subform"), None)
    if kok_sf is None:
        raise ValueError("XFA şablonunda kök alt form yok")
    kok_ad = kok_sf.get("name") or "form"

    duzen = (kok_sf.get("layout") or "position").lower()
    govde: list[str] = []
    for cocuk in kok_sf:
        if _local(cocuk.tag) in _CONTAINERS + _LEAVES:
            govde.append(derleyici.compile_node(cocuk, duzen, kok_ad, {}, ca_w))
    derleyici.collect_events(kok_sf, kok_ad)

    css = _CSS
    for anahtar, deger in (
        ("__BASE__", f"{DEFAULT_FONT_SIZE:g}"),
        ("__SMALL__", f"{DEFAULT_FONT_SIZE - 2:g}"),
        ("__PW__", f"{sayfa_g:.2f}"), ("__PH__", f"{sayfa_y:.2f}"),
        ("__CX__", f"{ca_x:.2f}"), ("__CY__", f"{ca_y:.2f}"),
        ("__CW__", f"{ca_w:.2f}"), ("__CH__", f"{ca_h:.2f}"),
    ):
        css = css.replace(anahtar, deger)

    yapilandirma = {
        "root": kok_ad,
        "page": {"w": sayfa_g, "h": sayfa_y,
                 "cx": ca_x, "cy": ca_y, "cw": ca_w, "ch": ca_h},
        "counters": sayaclar,
        "scripts": derleyici.scripts,
        "variables": derleyici.variables,
        "values": values or {},
    }

    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>{font_css}{css}</style></head><body>"
        "<div id='doc'><div id='stage'><div id='pages'></div></div></div>"
        "<div id='toast'></div>"
        f"<template id='furniture'>{sayfa_susleri}</template>"
        f"<div id='source' style='display:none'><div class='xs' data-som='{esc(kok_ad)}'"
        f" data-name='{esc(kok_ad)}' data-kind='subform' data-layout='{duzen}'"
        f" data-presence='visible' style='display:block;width:100%'>"
        + "".join(govde) +
        "</div></div>"
        f"<script>window.XFA_CONFIG={json.dumps(yapilandirma)};</script>"
        f"<script>{runtime_js}</script>"
        "</body></html>"
    )

    return Compiled(
        html=html,
        root=kok_ad,
        field_count=derleyici.field_count,
        script_count=len(derleyici.scripts),
        page_size=(sayfa_g, sayfa_y),
        warnings=derleyici.warnings,
    )
