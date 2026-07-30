"""PDF'i düzenlenebilir bir Word (.docx) belgesine dönüştürür.

Neden elle üretiliyor: ``.docx`` bir ZIP içinde birkaç XML parçasıdır. Bunu
``zipfile`` ile yazmak, ``python-docx`` + ``lxml`` bağımlılığını (ve kurulum
paketine eklenecek megabaytları) getirmekten hem küçük hem de tam denetimli.

Dönüşümün kapsamı bilinçlidir:

* Metin blokları paragraf olur; blok içindeki satırlar birleştirilir ki Word
  metni kendi genişliğine göre yeniden sarabilsin (satır satır aktarmak
  düzenlemeyi imkânsız hâle getiriyor).
* Punto, kalın/yatık ve renk korunur; yazı tipi adı da taşınır.
* Ortalanmış görünen bloklar ortalanır — başlıkların düzeni bozulmasın.
* **Metni olmayan sayfa** (taranmış belge) boş geçilmez: sayfa görüntüsü
  gömülür, böylece hiçbir içerik kaybolmaz.
* Sütun/tablo yapısı ve tam sayfa yerleşimi korunmaz; amaç birebir kopya
  değil, üzerinde çalışılabilir bir Word belgesidir.
"""
from __future__ import annotations

import os
import zipfile
from typing import Sequence

from .document import PdfDocument, normalize_text
from .pdf_backend import Matrix

#: Word ölçü birimleri
TWIPS_PER_PT = 20                 # 1 punto = 20 twip
EMU_PER_PT = 12700                # 1 punto = 12700 EMU
#: Taranmış sayfa görüntüsünün çözünürlüğü
IMAGE_DPI = 150
#: Bir blok, sayfanın ortasına bu kadar yakınsa ve bu orandan darsa ortalanır
CENTER_TOLERANCE = 0.06
CENTER_MAX_WIDTH = 0.75

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)


def _esc(text: str) -> str:
    """XML'de güvenli metin; Word'ün kabul etmediği denetim karakterleri atılır."""
    out = []
    for ch in text:
        if ch in "\t\n":
            out.append(" ")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            continue
        elif ch == "&":
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        else:
            out.append(ch)
    return "".join(out)


def _run(text: str, size: float, bold: bool, italic: bool,
         color: int, font: str) -> str:
    if not text:
        return ""
    ozellikler = [f'<w:rFonts w:ascii="{_esc(font)}" w:hAnsi="{_esc(font)}"/>'] if font else []
    if bold:
        ozellikler.append("<w:b/>")
    if italic:
        ozellikler.append("<w:i/>")
    if color:
        ozellikler.append(f'<w:color w:val="{color & 0xFFFFFF:06X}"/>')
    yarim_punto = max(2, int(round(size * 2)))
    ozellikler.append(f'<w:sz w:val="{yarim_punto}"/><w:szCs w:val="{yarim_punto}"/>')
    return (
        f"<w:r><w:rPr>{''.join(ozellikler)}</w:rPr>"
        f'<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'
    )


def _paragraph(runs: str, center: bool = False) -> str:
    hiza = '<w:pPr><w:jc w:val="center"/></w:pPr>' if center else ""
    return f"<w:p>{hiza}{runs}</w:p>"


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _image_paragraph(index: int, width_pt: float, height_pt: float) -> str:
    cx = int(width_pt * EMU_PER_PT)
    cy = int(height_pt * EMU_PER_PT)
    return (
        "<w:p><w:r><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{index}" name="Sayfa {index}"/>'
        "<a:graphic><a:graphicData "
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic><pic:nvPicPr>"
        f'<pic:cNvPr id="{index}" name="image{index}.png"/><pic:cNvPicPr/>'
        "</pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="rIdImg{index}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline>"
        "</w:drawing></w:r></w:p>"
    )


def _block_paragraph(block: dict, page_width: float) -> str:
    """Bir metin bloğunu tek paragrafa çevirir."""
    parcalar: list[str] = []
    for satir_no, satir in enumerate(block.get("lines", [])):
        for span in satir.get("spans", []):
            metin = normalize_text(span.get("text", ""))
            if not metin:
                continue
            if parcalar and satir_no and not metin.startswith(" "):
                # Satırlar birleştirilirken kelimeler yapışmasın; tireyle
                # bölünmüş kelime varsa tire korunur, boşluk eklenmez.
                if not parcalar[-1].endswith(("- ", "-")):
                    parcalar.append(" ")
            parcalar.append(metin)
    metin = "".join(parcalar).strip()
    if not metin:
        return ""

    ilk = None
    for satir in block.get("lines", []):
        for span in satir.get("spans", []):
            if span.get("text", "").strip():
                ilk = span
                break
        if ilk:
            break
    if ilk is None:
        return ""

    bayraklar = int(ilk.get("flags", 0))
    kutu = block.get("bbox", (0, 0, 0, 0))
    genislik = kutu[2] - kutu[0]
    merkez = (kutu[0] + kutu[2]) / 2
    ortali = (
        page_width > 0
        and genislik < page_width * CENTER_MAX_WIDTH
        and abs(merkez - page_width / 2) < page_width * CENTER_TOLERANCE
    )
    return _paragraph(
        _run(
            metin,
            float(ilk.get("size", 11.0)),
            bool(bayraklar & 16),
            bool(bayraklar & 2),
            int(ilk.get("color", 0)),
            str(ilk.get("font", "")).split("+")[-1].split("-")[0],
        ),
        center=ortali,
    )


def export_docx(doc: PdfDocument, out_path: str,
                pages: Sequence[int] | None = None) -> str:
    """Belgeyi ``.docx`` olarak yazar ve yolunu döndürür."""
    govde: list[str] = []
    gorseller: list[bytes] = []

    with doc.lock:
        toplam = doc.raw.page_count
        hedefler = [i for i in (pages if pages is not None else range(toplam))
                    if 0 <= i < toplam]
        if not hedefler:
            raise ValueError("Dışa aktarılacak sayfa yok.")

        ilk_sayfa = doc.raw.load_page(hedefler[0]).rect
        sayfa_g, sayfa_y = float(ilk_sayfa.width), float(ilk_sayfa.height)

        for sira, indeks in enumerate(hedefler):
            if sira:
                govde.append(_page_break())
            sayfa = doc.raw.load_page(indeks)
            genislik = float(sayfa.rect.width)
            paragraflar = [
                p for p in (
                    _block_paragraph(blok, genislik)
                    for blok in sayfa.get_text("dict").get("blocks", [])
                    if blok.get("type") == 0
                ) if p
            ]
            if paragraflar:
                govde.extend(paragraflar)
                continue
            # Metin yok (taranmış sayfa): görüntüsü gömülür.
            olcek = IMAGE_DPI / 72.0
            pix = sayfa.get_pixmap(matrix=Matrix(olcek, olcek), alpha=False)
            gorseller.append(pix.tobytes("png"))
            govde.append(_image_paragraph(
                len(gorseller), genislik, float(sayfa.rect.height)
            ))

    kenar = 40 * TWIPS_PER_PT
    sect = (
        "<w:sectPr>"
        f'<w:pgSz w:w="{int(sayfa_g * TWIPS_PER_PT)}" '
        f'w:h="{int(sayfa_y * TWIPS_PER_PT)}"/>'
        f'<w:pgMar w:top="{kenar}" w:right="{kenar}" w:bottom="{kenar}" '
        f'w:left="{kenar}" w:header="0" w:footer="0" w:gutter="0"/>'
        "</w:sectPr>"
    )
    belge = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<w:document {_NS}><w:body>{''.join(govde)}{sect}</w:body></w:document>"
    )

    iliskiler = "".join(
        f'<Relationship Id="rIdImg{i + 1}" Type="{_IMAGE_REL_TYPE}" '
        f'Target="media/image{i + 1}.png"/>'
        for i in range(len(gorseller))
    )
    document_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{iliskiler}</Relationships>"
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as paket:
        paket.writestr("[Content_Types].xml", _CONTENT_TYPES)
        paket.writestr("_rels/.rels", _ROOT_RELS)
        paket.writestr("word/document.xml", belge)
        paket.writestr("word/_rels/document.xml.rels", document_rels)
        for sira, veri in enumerate(gorseller, start=1):
            paket.writestr(f"word/media/image{sira}.png", veri)
    return out_path


def page_has_text(doc: PdfDocument, index: int) -> bool:
    """Sayfada aktarılabilir metin var mı (uyarı gösterebilmek için)."""
    with doc.lock:
        if not (0 <= index < doc.raw.page_count):
            return False
        return bool(doc.raw.load_page(index).get_text("text").strip())
