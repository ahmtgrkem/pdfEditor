"""XFA (XML Forms Architecture) form desteği.

Sorun
-----
Bazı kurumsal PDF formları içeriği sayfa akışında değil, gömülü bir XML
şablonunda taşır (``/AcroForm/XFA``). Katalogda ``/NeedsRendering true``
işaretlidir ve sayfa akışında yalnızca "bu belgeyi görüntülemek için Adobe
Reader 8 gerekli" yazan bir uyarı sayfası bulunur. MuPDF dâhil hemen hiçbir
görüntüleyici bu şablonu çizemez; kullanıcı dosyayı açar ama boş bir uyarı
görür.

Bu modül ne yapar
-----------------
Şablonu çizmeye çalışmaz — XFA tam bir yerleşim motoru ve betik dili
gerektirir. Bunun yerine **formu kullanılabilir kılar**: alanları,
etiketlerini ve seçeneklerini XML'den çıkarır, mevcut değerleri okur ve
doldurulan değerleri ``datasets`` paketine geri yazar. Adobe verileri zaten
oradan okuduğu için, burada doldurulan form Adobe'de doğru açılır.

Terimler: ``template`` alan tanımlarını, ``datasets`` ise girilen verileri
tutan XML paketidir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from xml.etree import ElementTree as ET

#: XFA paket dizisindeki ``(ad) xref 0 R`` çiftleri. Üretici araçlar araya
#: boşluk koymayabildiği için ayraç isteğe bağlıdır.
_PACKET_RE = re.compile(r"\((\w+)\)\s*(\d+)\s+0\s+R")

_DATA_NS = "http://www.xfa.org/schema/xfa-data/1.0/"

#: XFA arayüz düğümü -> bu modülün alan türü
_UI_TYPES = {
    "textEdit": "text",
    "numericEdit": "number",
    "dateTimeEdit": "date",
    "checkButton": "check",
    "choiceList": "choice",
    "passwordEdit": "password",
    "signature": "signature",
    "imageEdit": "image",
    "barcode": "barcode",
    "button": "button",
}

#: Kullanıcının dolduramayacağı alan türleri
READONLY_TYPES = frozenset({"button", "barcode", "signature", "image"})


def _local(tag: str) -> str:
    """``{ad-alani}etiket`` -> ``etiket``."""
    return tag.rsplit("}", 1)[-1]


# ======================================================================
# Belge düzeyi
# ======================================================================
def acroform_xref(doc) -> int:
    """``/AcroForm`` sözlüğünün xref'i; yoksa 0."""
    try:
        tur, deger = doc.xref_get_key(doc.pdf_catalog(), "AcroForm")
    except Exception:  # noqa: BLE001 - kapalı/bozuk belge
        return 0
    if tur != "xref":
        return 0
    try:
        return int(deger.split()[0])
    except (ValueError, IndexError):
        return 0


def read_packets(doc) -> dict[str, int]:
    """XFA paket adlarını xref numaralarına eşler (``{}`` = XFA yok)."""
    acro = acroform_xref(doc)
    if not acro:
        return {}
    try:
        tur, deger = doc.xref_get_key(acro, "XFA")
    except Exception:  # noqa: BLE001
        return {}
    if tur == "null":
        return {}
    return {ad: int(xref) for ad, xref in _PACKET_RE.findall(deger)}


def packet_data(doc, xref: int) -> bytes:
    try:
        return doc.xref_stream(xref) or b""
    except Exception:  # noqa: BLE001
        return b""


def is_xfa(doc) -> bool:
    """Belge XFA formu mu?"""
    return bool(read_packets(doc))


def is_dynamic(doc) -> bool:
    """Dinamik (yalnızca XFA) form mu?

    ``/NeedsRendering true`` dinamik formu işaret eder. Bu belgelerde sayfa
    akışı yalnızca uyarı sayfasıdır; klasik AcroForm alanları yoktur.
    """
    try:
        tur, deger = doc.xref_get_key(doc.pdf_catalog(), "NeedsRendering")
    except Exception:  # noqa: BLE001
        return False
    return tur == "bool" and deger == "true"


# ======================================================================
# Gömülü yazı tipleri
# ======================================================================
#: ``/FontName``daki alt küme öneki (``ABCDEF+``) ve PostScript son ekleri.
_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
#: ``TimesNewRomanPSMT`` -> ``TimesNewRoman``. ``Std``/``Pro`` ailenin parçası
#: olduğu için burada yok; onları CamelCase ayırıcı sözcüğe böler.
_PS_SUFFIX_RE = re.compile(r"(?:PSMT|MT|PS)$")
#: ``MyriadPro-Bold`` -> ``Myriad Pro`` için sözcük sınırı.
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")

#: Yazı tipi programının sihirli baytları -> CSS ``format()`` adı.
#: Bare CFF (Type1C) ve Type1 tarayıcıda kullanılamaz; listede yoktur.
_FONT_FORMAT = {
    b"OTTO": "opentype",
    b"\x00\x01\x00\x00": "truetype",
    b"true": "truetype",
    b"ttcf": "truetype",
    b"wOFF": "woff",
    b"wOF2": "woff2",
}

_FONT_DESC_RE = re.compile(
    r"/FontName\s*/([^\s/>\]]+)|/(FontFile[23]?)\s+(\d+)\s+0\s+R"
)


def _repack_sfnt(veri: bytes) -> bytes:
    """sfnt tablolarını 4 bayta hizalayıp ``DSIG``i atarak yeniden paketler.

    PDF'e gömülen yazı tipleri tabloları hizalamadan yan yana dizebiliyor.
    Tarayıcının doğrulayıcısı (OTS) bunu ``CFF : misaligned table`` diye
    reddediyor ve ``@font-face`` sessizce düşüyordu. İmza tablosu da yeniden
    yerleşimden sonra geçersiz kalacağı için çıkarılır.

    Bozuk/anlaşılmayan veride girdi olduğu gibi döner; çağıran zaten
    tarayıcının kabul etmemesine karşı sistem yazı tipine düşüyor.
    """
    import struct

    try:
        sayi = struct.unpack(">H", veri[4:6])[0]
        if len(veri) < 12 + sayi * 16:
            return veri
        tablolar = []
        for i in range(sayi):
            etiket, saglama, konum, boy = struct.unpack(
                ">4sIII", veri[12 + i * 16:28 + i * 16]
            )
            if etiket == b"DSIG":
                continue
            govde = veri[konum:konum + boy]
            if len(govde) != boy:
                return veri
            tablolar.append((etiket, saglama, govde))
        if not tablolar:
            return veri
    except (struct.error, IndexError):
        return veri

    tablolar.sort(key=lambda t: t[0])
    n = len(tablolar)
    ustu = max(0, n.bit_length() - 1)            # log2(n) tabanı
    parca = 16 * (1 << ustu)
    basliklar = [veri[:4], struct.pack(">HHHH", n, parca, ustu,
                                       n * 16 - parca)]
    konum = 12 + n * 16
    dizin, govdeler = [], []
    for etiket, saglama, govde in tablolar:
        dizin.append(struct.pack(">4sIII", etiket, saglama, konum, len(govde)))
        dolgu = (-len(govde)) % 4
        govdeler.append(govde + b"\0" * dolgu)
        konum += len(govde) + dolgu
    return b"".join(basliklar + dizin + govdeler)


def _css_font_name(ps_adi: str) -> tuple[str, int, str]:
    """PostScript adı -> ``(aile, kalınlık, stil)``.

    ``MyriadPro-Bold`` -> ``("Myriad Pro", 700, "normal")``.
    Şablondaki ``typeface="Myriad Pro"`` ile eşleşmesi gerekir; eşleşmezse
    gömülü yazı tipi hiç kullanılmaz ve metin genişlikleri kayar.
    """
    ad = _SUBSET_RE.sub("", ps_adi)
    taban, _, stil = ad.partition("-")
    stil = stil.lower()
    kalinlik = 700 if "bold" in stil or "black" in stil else 400
    egik = "italic" if ("italic" in stil or "oblique" in stil or "it" == stil) else "normal"
    return _CAMEL_RE.sub(" ", _PS_SUFFIX_RE.sub("", taban)).strip(), kalinlik, egik


_TYPEFACE_RE = re.compile(rb'typeface="([^"]+)"')

#: Gömülü yazı tiplerinin toplam üst sınırı (base64'e çevrilmiş hâliyle).
#: ``QWebEngineView.setHtml`` 2 MB'tan büyük içeriği hiç göstermez; formun
#: kendi HTML'ine de yer kalmalı. Bütçeye sığmayan yazı tipi atlanır ve
#: sistemdeki karşılığına düşülür — Courier New gibi her Windows'ta bulunan
#: aileler için görünür bir kayıp yok.
FONT_BUDGET = 700_000


def template_typefaces(template: bytes) -> set[str]:
    """Şablonun kullandığı yazı tipi adları (küçük harfe indirgenmiş)."""
    return {a.decode("utf-8", "replace").strip().lower()
            for a in _TYPEFACE_RE.findall(template or b"")}


def embedded_font_css(doc, typefaces: set[str] | None = None) -> str:
    """Belgeye gömülü yazı tiplerini ``@font-face`` kuralları olarak döndürür.

    Foxit/Adobe formu **gömülü** yazı tipiyle çizer; biz Arial'e düşünce her
    satır ~%6 genişliyor, etiketler kayıyor ve sarıp taşıyordu. Aynı dosyanın
    farklı görünmesinin asıl nedeni buydu.

    ``typefaces`` verilirse yalnızca şablonun gerçekten kullandığı aileler
    gömülür (bkz. :data:`FONT_BUDGET`).
    """
    import base64

    kurallar: list[str] = []
    gorulen: set[tuple[str, int, str]] = set()
    butce = FONT_BUDGET
    for xref in range(1, doc.xref_length()):
        try:
            nesne = doc.xref_object(xref, compressed=True)
        except Exception:  # noqa: BLE001
            continue
        if "/Type/FontDescriptor" not in nesne.replace(" ", ""):
            continue

        ps_adi, dosya_xref = "", 0
        for eslesme in _FONT_DESC_RE.finditer(nesne):
            if eslesme.group(1):
                ps_adi = eslesme.group(1)
            else:
                dosya_xref = int(eslesme.group(3))
        if not ps_adi or not dosya_xref:
            continue

        aile, kalinlik, egik = _css_font_name(ps_adi)
        if (aile, kalinlik, egik) in gorulen:
            continue
        if typefaces is not None and aile.lower() not in typefaces:
            continue

        veri = packet_data(doc, dosya_xref)
        bicim = _FONT_FORMAT.get(veri[:4])
        if not bicim:                       # Type1/bare CFF: tarayıcı açamaz
            continue
        if bicim in ("opentype", "truetype"):
            veri = _repack_sfnt(veri)

        b64 = base64.b64encode(veri).decode("ascii")
        if len(b64) > butce:
            continue
        butce -= len(b64)

        gorulen.add((aile, kalinlik, egik))
        kurallar.append(
            f"@font-face{{font-family:'{aile}';font-weight:{kalinlik};"
            f"font-style:{egik};font-display:block;"
            f"src:url(data:font/{bicim};base64,{b64}) format('{bicim}')}}"
        )
    return "".join(kurallar)


# ======================================================================
# Alanlar
# ======================================================================
@dataclass
class XfaField:
    """Şablondan çıkarılmış tek bir form alanı."""

    name: str
    #: Kök altformdan itibaren nokta ile ayrılmış veri yolu
    path: str
    caption: str = ""
    type: str = "text"
    value: str = ""
    options: list[tuple[str, str]] = dataclass_field(default_factory=list)

    @property
    def editable(self) -> bool:
        return self.type not in READONLY_TYPES

    @property
    def label(self) -> str:
        """Arayüzde gösterilecek ad — etiket yoksa alan adına düşülür."""
        return self.caption.strip() or self.name


def _text_of(node) -> str:
    """``<value><text>...</text></value>`` içindeki düz metni toplar."""
    if node is None:
        return ""
    parcalar: list[str] = []
    for alt in node.iter():
        if _local(alt.tag) in ("text", "exData") and alt.text:
            parcalar.append(alt.text.strip())
    return " ".join(p for p in parcalar if p).strip()


def _caption_of(alan) -> str:
    for cocuk in alan:
        if _local(cocuk.tag) == "caption":
            return _text_of(cocuk)
    return ""


def _ui_type_of(alan) -> str:
    for cocuk in alan:
        if _local(cocuk.tag) != "ui":
            continue
        for torun in cocuk:
            tur = _UI_TYPES.get(_local(torun.tag))
            if tur:
                return tur
    return "text"


def _options_of(alan) -> list[tuple[str, str]]:
    """``<items>`` düğümlerinden (gösterilen, kaydedilen) çiftleri üretir.

    XFA'da iki ``items`` bloğu olabilir: biri kullanıcıya gösterilen metin,
    diğeri ``save="1"`` ile kaydedilen değer.
    """
    gorunen: list[str] = []
    kaydedilen: list[str] = []
    for cocuk in alan:
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


def extract_fields(template: bytes) -> list[XfaField]:
    """``template`` paketinden doldurulabilir alanları çıkarır.

    Yerleşim (x/y/w/h) yok sayılır; amaç formu çizmek değil, alanlarını
    kullanılabilir kılmak.
    """
    if not template:
        return []
    try:
        kok = ET.fromstring(template)
    except ET.ParseError:
        return []

    alanlar: list[XfaField] = []

    def gez(dugum, yol: list[str]) -> None:
        for cocuk in dugum:
            etiket = _local(cocuk.tag)
            ad = cocuk.get("name")
            if etiket == "field":
                if not ad:
                    continue
                tur = _ui_type_of(cocuk)
                # Onay kutularında şablondaki ``<value>`` mevcut durum DEĞİL,
                # kutu işaretlenince kaydedilecek "açık değeri"dir (radyo
                # gruplarında grubun alacağı değer). Durum sayılırsa boş bir
                # form bile bütün kutuları işaretli açar.
                ilk_deger = "" if tur == "check" else _text_of(
                    next((v for v in cocuk if _local(v.tag) == "value"), None)
                )
                alanlar.append(
                    XfaField(
                        name=ad,
                        path=".".join(yol + [ad]),
                        caption=_caption_of(cocuk),
                        type=tur,
                        value=ilk_deger,
                        options=_options_of(cocuk),
                    )
                )
            elif etiket in ("subform", "subformSet", "area", "exclGroup"):
                gez(cocuk, yol + [ad] if ad else yol)
            elif etiket in ("pageSet", "pageArea"):
                continue        # sayfa süslemeleri; doldurulabilir alan yok

    gez(kok, [])
    return alanlar


# ======================================================================
# Veri (datasets)
# ======================================================================
def read_values(datasets: bytes) -> dict[str, str]:
    """``datasets`` paketindeki dolu değerleri ``{yol: değer}`` olarak verir."""
    if not datasets:
        return {}
    try:
        kok = ET.fromstring(datasets)
    except ET.ParseError:
        return {}

    veri = next((c for c in kok.iter() if _local(c.tag) == "data"), None)
    if veri is None:
        return {}

    degerler: dict[str, str] = {}

    def gez(dugum, yol: list[str]) -> None:
        # Aynı adlı kardeşler yinelenen satırlardır; dizinlenmezse hepsi aynı
        # yola yazılır ve yalnızca sonuncusu kalır.
        sayim: dict[str, int] = {}
        for cocuk in dugum:
            sayim[_local(cocuk.tag)] = sayim.get(_local(cocuk.tag), 0) + 1
        gorulen: dict[str, int] = {}

        for cocuk in dugum:
            ad = _local(cocuk.tag)
            if sayim[ad] > 1:
                sira = gorulen.get(ad, 0)
                gorulen[ad] = sira + 1
                adim = f"{ad}[{sira}]"
            else:
                adim = ad
            yeni = yol + [adim]
            cocuklu = len(list(cocuk)) > 0
            if not cocuklu and (cocuk.text or "").strip():
                degerler[".".join(yeni)] = cocuk.text.strip()
            elif cocuklu:
                gez(cocuk, yeni)

    for kokveri in veri:
        gez(kokveri, [_local(kokveri.tag)])
    return degerler


#: ``ad[3]`` biçimindeki yol adımı — yinelenen alt formların örnek dizini
_STEP_RE = re.compile(r"^(.*?)\[(\d+)\]$")


def _parse_step(step: str) -> tuple[str, int]:
    """``"row[2]"`` -> ``("row", 2)``; dizin yoksa 0."""
    eslesme = _STEP_RE.match(step)
    if eslesme:
        return eslesme.group(1), int(eslesme.group(2))
    return step, 0


def _step_into(node: ET.Element, name: str, index: int) -> ET.Element:
    """``node`` altındaki ``index``inci ``name`` düğümü; yoksa oluşturur.

    Yinelenen satırlar (tablo satırları, mali yıllar) veri ağacında aynı adlı
    kardeş düğümler olarak durur; dizin bu kardeşler arasında seçer.
    """
    esler = [c for c in node if c.tag == name]
    while len(esler) <= index:
        esler.append(ET.SubElement(node, name))
    return esler[index]


def build_datasets(values: dict[str, str], root_name: str = "form") -> bytes:
    """Doldurulan değerlerden ``datasets`` paketini üretir.

    Yollar (``form.contact.name``) iç içe düğümlere çevrilir; Adobe veriyi
    bu ağaçtan okur.
    """
    ET.register_namespace("xfa", _DATA_NS)
    kok = ET.Element(f"{{{_DATA_NS}}}datasets")
    veri = ET.SubElement(kok, f"{{{_DATA_NS}}}data")

    kokler: dict[str, ET.Element] = {}
    for yol, deger in values.items():
        if not str(deger).strip():
            continue
        parcalar = [_parse_step(p) for p in yol.split(".") if p]
        if not parcalar:
            continue
        # Şablon yolları kök altformla başlar; datasets ağacı da öyle olmalı.
        kok_ad = parcalar[0][0]
        if kok_ad not in kokler:
            kokler[kok_ad] = ET.SubElement(veri, kok_ad)
        dugum = kokler[kok_ad]
        for ad, dizin in parcalar[1:]:
            dugum = _step_into(dugum, ad, dizin)
        dugum.text = str(deger)

    if not len(veri):
        veri.set(f"{{{_DATA_NS}}}dataNode", "dataGroup")
    return ET.tostring(kok, encoding="utf-8", xml_declaration=False)


def write_values(doc, values: dict[str, str], root_name: str = "form") -> bool:
    """Değerleri belgenin ``datasets`` paketine yazar.

    ``True`` döndürürse belge değişmiştir ve kaydedilmelidir.
    """
    paketler = read_packets(doc)
    xref = paketler.get("datasets")
    if not xref:
        return False
    try:
        doc.update_stream(xref, build_datasets(values, root_name))
    except Exception:  # noqa: BLE001 - salt okunur/bozuk belge
        return False
    return True


def root_subform_name(template: bytes) -> str:
    """Kök altformun adı (veri ağacının kökü). Bulunamazsa ``"form"``."""
    if not template:
        return "form"
    try:
        kok = ET.fromstring(template)
    except ET.ParseError:
        return "form"
    for cocuk in kok:
        if _local(cocuk.tag) == "subform" and cocuk.get("name"):
            return cocuk.get("name")
    return "form"


# ======================================================================
# Üst düzey yardımcı
# ======================================================================
@dataclass
class XfaForm:
    """Bir belgedeki XFA formunun okunmuş hâli."""

    fields: list[XfaField]
    root: str = "form"
    dynamic: bool = False

    @property
    def editable_fields(self) -> list[XfaField]:
        return [a for a in self.fields if a.editable]

    def as_values(self) -> dict[str, str]:
        return {a.path: a.value for a in self.fields if a.value}


def load(doc) -> XfaForm | None:
    """Belgedeki XFA formunu okur; XFA yoksa ``None``."""
    paketler = read_packets(doc)
    if not paketler:
        return None
    sablon = packet_data(doc, paketler["template"]) if "template" in paketler else b""
    alanlar = extract_fields(sablon)
    mevcut = read_values(
        packet_data(doc, paketler["datasets"]) if "datasets" in paketler else b""
    )
    for alan in alanlar:
        if alan.path in mevcut:
            alan.value = mevcut[alan.path]
    return XfaForm(
        fields=alanlar,
        root=root_subform_name(sablon),
        dynamic=is_dynamic(doc),
    )
