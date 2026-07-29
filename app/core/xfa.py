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
from typing import Any
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
    tooltip: str = ""

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
                alanlar.append(
                    XfaField(
                        name=ad,
                        path=".".join(yol + [ad]),
                        caption=_caption_of(cocuk),
                        type=_ui_type_of(cocuk),
                        value=_text_of(
                            next((v for v in cocuk if _local(v.tag) == "value"), None)
                        ),
                        options=_options_of(cocuk),
                        tooltip=cocuk.get("hAlign", ""),
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
        for cocuk in dugum:
            ad = _local(cocuk.tag)
            yeni = yol + [ad]
            cocuklu = len(list(cocuk)) > 0
            if not cocuklu and (cocuk.text or "").strip():
                degerler[".".join(yeni)] = cocuk.text.strip()
            elif cocuklu:
                gez(cocuk, yeni)

    for kokveri in veri:
        gez(kokveri, [_local(kokveri.tag)])
    return degerler


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
        parcalar = [p for p in yol.split(".") if p]
        if not parcalar:
            continue
        # Şablon yolları kök altformla başlar; datasets ağacı da öyle olmalı.
        if parcalar[0] not in kokler:
            kokler[parcalar[0]] = ET.SubElement(veri, parcalar[0])
        dugum = kokler[parcalar[0]]
        for parca in parcalar[1:-1]:
            sonraki = dugum.find(parca)
            if sonraki is None:
                sonraki = ET.SubElement(dugum, parca)
            dugum = sonraki
        yaprak = dugum.find(parcalar[-1]) if len(parcalar) > 1 else None
        if yaprak is None:
            yaprak = ET.SubElement(dugum, parcalar[-1])
        yaprak.text = str(deger)

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
