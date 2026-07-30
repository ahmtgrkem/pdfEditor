"""PDF'i düzenlenebilir bir Word (.docx) belgesine dönüştürür.

Neden elle üretiliyor: ``.docx`` bir ZIP içinde birkaç XML parçasıdır. Bunu
``zipfile`` ile yazmak, ``python-docx`` + ``lxml`` bağımlılığını (ve kurulum
paketine eklenecek megabaytları) getirmekten hem küçük hem de tam denetimli.

Dönüşümün kapsamı bilinçlidir:

* Metin blokları sayfadaki **konumlarına** yerleştirilir (``w:framePr``,
  sayfa kenarına göre mutlak). Akışa dizmek sayfayı soldan alt alta bir
  liste hâline getiriyor, form belgeleri tanınmaz oluyordu.
* Blok içindeki satırlar birleştirilir; sarma genişliği bloğun kendi
  genişliğidir, yani satır bölümleri özgününe yakın kalır.
* Punto, kalın/yatık ve renk korunur; yazı tipi adı da taşınır.
* Çizgiler ve dolu/çerçeveli dikdörtgenler (form alan kutuları, tablo
  çizgileri) VML şekilleri olarak metnin **altına** çizilir.
* **Metni olmayan sayfa** (taranmış belge) boş geçilmez: sayfa görüntüsü
  gömülür, böylece hiçbir içerik kaybolmaz.
* Eğri/karmaşık vektör çizimler ve gerçek tablo yapısı taşınmaz; metin
  yine de düzenlenebilir kutular hâlindedir.
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
#: Metin kutusuna verilen pay: Word'ün satır sarması PDF'inkiyle birebir
#: değil, blok genişliği kılı kılına verilirse son kelime alta düşüyor.
BOX_SLACK_PT = 4.0
#: Bundan ince çizimler saç teli gibi çizilir; Word'ün en ince kalemi
HAIRLINE_PT = 0.4

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
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


def _paragraph(runs: str, box: tuple[float, float, float, float] | None = None) -> str:
    """``box`` verilirse paragraf sayfada o konuma sabitlenir (punto)."""
    if box is None:
        return f"<w:p>{runs}</w:p>"
    x0, y0, x1, y1 = box
    cerceve = (
        '<w:framePr w:hAnchor="page" w:vAnchor="page" w:wrap="none" '
        f'w:x="{int(max(x0, 0) * TWIPS_PER_PT)}" '
        f'w:y="{int(max(y0, 0) * TWIPS_PER_PT)}" '
        f'w:w="{int(max(x1 - x0 + BOX_SLACK_PT, 1) * TWIPS_PER_PT)}" '
        f'w:h="{int(max(y1 - y0, 1) * TWIPS_PER_PT)}" w:hRule="auto"/>'
    )
    # Word'ün varsayılan paragraf boşluğu kutuları aşağı kaydırır; sıfırlanır.
    aralik = '<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/>'
    return f"<w:p><w:pPr>{cerceve}{aralik}</w:pPr>{runs}</w:p>"


def _shape_style(x0: float, y0: float, w: float, h: float) -> str:
    return (
        f"position:absolute;left:{x0:.1f}pt;top:{y0:.1f}pt;"
        f"width:{max(w, 0):.1f}pt;height:{max(h, 0):.1f}pt;z-index:-1;"
        "mso-position-horizontal-relative:page;"
        "mso-position-vertical-relative:page"
    )


def _hex(color) -> str | None:
    """PyMuPDF rengi (0-1 üçlüsü) -> ``#rrggbb``; renk yoksa ``None``."""
    if not color:
        return None
    try:
        r, g, b = (max(0, min(255, int(round(c * 255)))) for c in color[:3])
    except (TypeError, ValueError):
        return None
    return f"#{r:02X}{g:02X}{b:02X}"


def _drawing_shapes(page) -> str:
    """Sayfadaki çizgi ve dikdörtgenleri VML şekillerine çevirir.

    Form belgelerinde alan kutuları ve tablo çizgileri metnin değil çizim
    katmanının parçasıdır; aktarılmazsa Word'de yalnızca havada duran
    etiketler kalıyor.
    """
    parcalar: list[str] = []
    try:
        cizimler = page.get_drawings()
    except Exception:  # noqa: BLE001 - bozuk içerik akışı
        return ""
    for cizim in cizimler:
        kontur = _hex(cizim.get("color"))
        dolgu = _hex(cizim.get("fill"))
        if not kontur and not dolgu:
            continue
        kalinlik = max(float(cizim.get("width") or 0) or HAIRLINE_PT, HAIRLINE_PT)
        ozellik = (
            (f'fillcolor="{dolgu}" ' if dolgu else 'filled="f" ')
            + (f'strokecolor="{kontur}" strokeweight="{kalinlik:.2f}pt" '
               if kontur else 'stroked="f" ')
        )
        for oge in cizim.get("items", []):
            if oge[0] == "re":
                r = oge[1]
                parcalar.append(
                    f'<v:rect style="{_shape_style(r.x0, r.y0, r.width, r.height)}"'
                    f" {ozellik}/>"
                )
            elif oge[0] == "l" and kontur:
                p1, p2 = oge[1], oge[2]
                x0, y0 = min(p1.x, p2.x), min(p1.y, p2.y)
                parcalar.append(
                    f'<v:line style="{_shape_style(x0, y0, abs(p2.x - p1.x), abs(p2.y - p1.y))}"'
                    f' from="{p1.x:.1f}pt,{p1.y:.1f}pt" to="{p2.x:.1f}pt,{p2.y:.1f}pt"'
                    f' strokecolor="{kontur}" strokeweight="{kalinlik:.2f}pt"/>'
                )
    if not parcalar:
        return ""
    return f"<w:p><w:r><w:pict>{''.join(parcalar)}</w:pict></w:r></w:p>"


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


def _block_paragraph(block: dict, page_width: float = 0.0) -> str:
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
    kutu = block.get("bbox", None)
    return _paragraph(
        _run(
            metin,
            float(ilk.get("size", 11.0)),
            bool(bayraklar & 16),
            bool(bayraklar & 2),
            int(ilk.get("color", 0)),
            str(ilk.get("font", "")).split("+")[-1].split("-")[0],
        ),
        box=tuple(float(v) for v in kutu) if kutu else None,
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
                # Şekiller önce: z-index negatif olsa da Word'de akışta
                # önde gelen kutu, sonrakileri aşağı itmesin diye başta durur.
                sekiller = _drawing_shapes(sayfa)
                if sekiller:
                    govde.append(sekiller)
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
