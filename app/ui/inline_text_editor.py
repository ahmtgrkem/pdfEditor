"""Canlı Sayfa Üzeri Metin Düzenleyici (Inline Canvas Text Widget).

Hizalama sözleşmesi (0 piksel kayma)
------------------------------------
Bu bileşenin tek kritik garantisi şudur::

    QTextEdit içindeki ilk karakterin sol-üst köşesi
        ==  tuval üzerindeki PDF koordinatı (x0, y0)

Bunu sağlamak için:

* Kök widget'ta **layout yoktur**; araç çubuğu, tutamaklar ve çerçeve elle
  konumlandırılır. Böylece hiçbiri metin alanını kaydıramaz.
* ``QTextEdit`` tüm iç marjinlerinden arındırılır (``setDocumentMargin(0)``,
  ``NoFrame``, ``setViewportMargins(0,0,0,0)``, CSS ``padding/margin: 0``).
* :meth:`InlineCanvasTextWidget.text_origin` araç çubuğu + tutamak ofsetini
  *dinamik* olarak döndürür; ``PageView`` widget'ı
  ``ekran(x0, y0) - text_origin()`` noktasına yerleştirir.

Punto eşleme (WYSIWYG)
----------------------
PyMuPDF 72 DPI tabanlıdır: ``fontsize`` pt değeri, ``zoom`` katsayısıyla
render edilen sayfada birebir ``fontsize * zoom`` piksele karşılık gelir.
Qt ise ``pointSize``ı ekran DPI'ıyla (Windows'ta 96) çarpar; bu yüzden
``setFontPointSize(size)`` metni %33 büyük gösterir. Bu modül bu nedenle
font boyutunu **daima piksel cinsinden** (``QFont.setPixelSize``) ayarlar.

Taban çizgisi (baseline)
------------------------
Metin alanının üstü PDF ``y0``ına denk geldiğine göre, ilk satırın taban
çizgisi Qt'nin kendi yerleşiminden okunur ve PDF uzayına çevrilir::

    origin_y = y0 + line.ascent() / zoom

Böylece PyMuPDF'e "taban çizgisini tam olarak buraya koy" denir ve ekrandaki
önizleme ile PDF çıktısı üst üste oturur.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QWidget,
)

from ..core.annotations import TextStyle
from .dialogs.common import ColorButton

MIN_FONT_SIZE = 6.0
MAX_FONT_SIZE = 72.0
FONT_SIZE_STEP = 2.0


@dataclass
class InlineTextResult:
    """Onaylanan metin kutusunun PDF'e yazılması için gereken her şey."""

    page_index: int
    #: Görsel (sayfa pt) koordinatlarda metin kutusu
    rect: tuple[float, float, float, float]
    text: str
    style: TextStyle
    #: İlk satırın taban çizgisi — ``insert_text`` origin noktası
    origin: tuple[float, float]
    #: Satırlar arası taban çizgisi mesafesi (pt)
    line_height: float


class FloatingMiniToolbar(QFrame):
    """Metin kutusunun üstünde yüzen küçük araç çubuğu."""

    fontSizeChanged = Signal(float)
    colorChanged = Signal(QColor)
    boldToggled = Signal(bool)
    italicToggled = Signal(bool)
    deleteRequested = Signal()

    def __init__(self, style: TextStyle, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("floatingToolbar")
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("""
            QFrame#floatingToolbar {
                background-color: #1E1E2E;
                border: 1px solid #45475A;
                border-radius: 8px;
            }
            QPushButton {
                background: transparent;
                color: #CDD6F4;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
                min-width: 24px;
                min-height: 24px;
            }
            QPushButton:hover { background-color: #45475A; }
            QPushButton:checked { background-color: #89B4FA; color: #11111B; }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)

        self.btn_dec_size = QPushButton("A_", self)
        self.btn_dec_size.setToolTip("Font boyutunu küçült")
        self.btn_dec_size.setFocusPolicy(Qt.NoFocus)
        self.btn_dec_size.clicked.connect(self._decrease_size)

        self.lbl_size = QLabel(f"{int(style.size)}pt", self)
        self.lbl_size.setStyleSheet("color: #BAC2DE; font-size: 11px; padding: 0 4px;")

        self.btn_inc_size = QPushButton("A^", self)
        self.btn_inc_size.setToolTip("Font boyutunu büyüt")
        self.btn_inc_size.setFocusPolicy(Qt.NoFocus)
        self.btn_inc_size.clicked.connect(self._increase_size)

        self.btn_bold = QPushButton("B", self)
        self.btn_bold.setCheckable(True)
        self.btn_bold.setChecked(style.bold)
        self.btn_bold.setToolTip("Koyu (Bold)")
        self.btn_bold.setFocusPolicy(Qt.NoFocus)
        self.btn_bold.toggled.connect(self.boldToggled.emit)

        self.btn_italic = QPushButton("I", self)
        self.btn_italic.setCheckable(True)
        self.btn_italic.setChecked(style.italic)
        self.btn_italic.setStyleSheet("font-style: italic;")
        self.btn_italic.setToolTip("Yatık (Italic)")
        self.btn_italic.setFocusPolicy(Qt.NoFocus)
        self.btn_italic.toggled.connect(self.italicToggled.emit)

        self.color_btn = ColorButton(QColor.fromRgbF(*style.color), parent=self)
        self.color_btn.setToolTip("Metin rengi")
        self.color_btn.setFocusPolicy(Qt.NoFocus)
        self.color_btn.colorChanged.connect(
            lambda c: self.colorChanged.emit(c or QColor("#000000"))
        )

        self.btn_delete = QPushButton("\U0001F5D1", self)
        self.btn_delete.setToolTip("Kutuyu sil (Esc)")
        self.btn_delete.setFocusPolicy(Qt.NoFocus)
        self.btn_delete.setStyleSheet(
            "QPushButton:hover { background-color: #F38BA8; color: #11111B; }"
        )
        self.btn_delete.clicked.connect(self.deleteRequested.emit)

        for widget in (
            self.btn_dec_size, self.lbl_size, self.btn_inc_size,
            self.btn_bold, self.btn_italic, self.color_btn, self.btn_delete,
        ):
            layout.addWidget(widget)

        self.current_size = style.size

    def update_size_label(self, size: float) -> None:
        self.current_size = size
        self.lbl_size.setText(f"{int(size)}pt")

    def _increase_size(self) -> None:
        new_size = min(MAX_FONT_SIZE, self.current_size + FONT_SIZE_STEP)
        self.update_size_label(new_size)
        self.fontSizeChanged.emit(new_size)

    def _decrease_size(self) -> None:
        new_size = max(MIN_FONT_SIZE, self.current_size - FONT_SIZE_STEP)
        self.update_size_label(new_size)
        self.fontSizeChanged.emit(new_size)


class CustomTextEdit(QTextEdit):
    """Marjinsiz, kaydırma çubuksuz metin alanı."""

    cancelRequested = Signal()
    commitRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptRichText(False)
        # --- 0 piksel hizalama: tüm iç boşlukları sıfırla ---
        self.setFrameShape(QFrame.NoFrame)
        self.setFrameShadow(QFrame.Plain)
        self.setLineWidth(0)
        self.setMidLineWidth(0)
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(0, 0, 0, 0)
        self.document().setDocumentMargin(0)
        self.document().setIndentWidth(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setTabChangesFocus(False)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelRequested.emit()
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
            event.modifiers() & (Qt.ControlModifier | Qt.KeypadModifier | Qt.ShiftModifier)
            == Qt.ControlModifier
        ):
            self.commitRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _HandleLabel(QLabel):
    """Sürüklenebilir tutamakların ortak davranışı."""

    def __init__(self, glyph: str, owner: InlineCanvasTextWidget, left: bool) -> None:
        super().__init__(glyph, owner)
        self.owner = owner
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.NoFocus)
        radius = "border-top-left-radius: 4px; border-bottom-left-radius: 4px;" if left else \
                 "border-top-right-radius: 4px; border-bottom-right-radius: 4px;"
        self.setStyleSheet(f"""
            QLabel {{
                background: #1976D2;
                color: #FFFFFF;
                {radius}
                font-weight: bold;
                font-size: 12px;
            }}
            QLabel:hover {{ background: #1565C0; }}
        """)
        self._press_pos = None
        self._start_rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._start_width = 0

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition()
            self._start_rect = self.owner.pdf_rect
            self._start_width = self.owner.text_width_px()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_pos = None
        event.accept()

    def _delta(self, event) -> tuple[int, int] | None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return None
        delta = event.globalPosition() - self._press_pos
        return int(round(delta.x())), int(round(delta.y()))


class DragHandleLabel(_HandleLabel):
    """Sol taşıma tutamağı (``⋮⋮``)."""

    def __init__(self, owner: InlineCanvasTextWidget) -> None:
        super().__init__("⋮⋮", owner, left=True)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Taşımak için basılı tutup sürükleyin")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        moved = self._delta(event)
        if moved is None:
            return
        dx, dy = moved
        # Piksel deltası tam sayıya yuvarlanır; böylece widget konumu ile
        # pdf_rect arasında yuvarlama kayması birikmez.
        self.owner.move_by_pixels(dx, dy, self._start_rect)
        event.accept()


class ResizeHandleLabel(_HandleLabel):
    """Sağ genişlik ayarlama tutamağı (``⇹``)."""

    def __init__(self, owner: InlineCanvasTextWidget) -> None:
        super().__init__("⇹", owner, left=False)
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip("Genişliği ayarlamak için sürükleyin")

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        moved = self._delta(event)
        if moved is None:
            return
        self.owner.set_text_width_px(self._start_width + moved[0])
        event.accept()


class InlineCanvasTextWidget(QWidget):
    """Tuval üzerinde taşınabilir, boyutlandırılabilir canlı metin girdisi."""

    #: Kesikli seçim çerçevesi — metin alanının **dışına** çizilir
    BORDER = 2
    #: Tutamak genişliği (px)
    HANDLE_W = 16
    #: Araç çubuğu ile metin kutusu arası boşluk (px)
    TOOLBAR_GAP = 6
    #: En dar metin alanı (px)
    MIN_TEXT_W = 48
    #: Stil kuralının tema tarafından ezilmemesi için kullanılan objectName
    EDITOR_OBJECT_NAME = "inlineTextEditor"

    commitRequested = Signal(object)   # InlineTextResult
    cancelRequested = Signal()
    #: pdf_rect konumu değişti — görünümün widget'ı yeniden yerleştirmesi gerekir
    rectChanged = Signal()

    def __init__(
        self,
        page_index: int,
        pdf_rect: tuple[float, float, float, float],
        zoom: float,
        default_style: TextStyle,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self.page_index = page_index
        self.pdf_rect = tuple(float(v) for v in pdf_rect)
        self.zoom = max(0.05, float(zoom))
        self.style = TextStyle(
            family=default_style.family,
            size=default_style.size,
            color=default_style.color,
            bold=default_style.bold,
            italic=default_style.italic,
            align=0,
        )
        self._toolbar_below = False
        self._box_rect = QRect()

        self.toolbar = FloatingMiniToolbar(self.style, self)
        self.toolbar.fontSizeChanged.connect(self._on_font_size_changed)
        self.toolbar.colorChanged.connect(self._on_color_changed)
        self.toolbar.boldToggled.connect(self._on_bold_toggled)
        self.toolbar.italicToggled.connect(self._on_italic_toggled)
        self.toolbar.deleteRequested.connect(self.cancelRequested.emit)

        self.editor = CustomTextEdit(self)
        self.editor.setObjectName(self.EDITOR_OBJECT_NAME)
        self.editor.cancelRequested.connect(self.cancelRequested.emit)
        self.editor.commitRequested.connect(self.commit)
        self.editor.textChanged.connect(self._relayout)

        self.drag_handle = DragHandleLabel(self)
        self.resize_handle = ResizeHandleLabel(self)

        width_pt = max(0.0, self.pdf_rect[2] - self.pdf_rect[0])
        self._text_w = max(self.MIN_TEXT_W, int(round(width_pt * self.zoom)))

        self._apply_style()
        self.setFocusProxy(self.editor)

    # ==================================================================
    # Ölçüler — 0 piksel hizalamanın kalbi
    # ==================================================================
    def toolbar_height(self) -> int:
        return int(self.toolbar.sizeHint().height())

    def text_origin_y(self, toolbar_below: bool | None = None) -> int:
        """Metin alanının widget üstüne göre dikey ofseti."""
        below = self._toolbar_below if toolbar_below is None else toolbar_below
        if below:
            return self.BORDER
        return self.toolbar_height() + self.TOOLBAR_GAP + self.BORDER

    def text_origin(self) -> QPoint:
        """İlk karakterin sol-üst köşesinin widget içindeki konumu.

        ``PageView`` widget'ı ``ekran(x0, y0) - text_origin()`` noktasına
        koyduğunda ilk karakter tam olarak PDF ``(x0, y0)`` noktasına oturur.
        """
        return QPoint(self.HANDLE_W + self.BORDER, self.text_origin_y())

    def text_width_px(self) -> int:
        return int(self._text_w)

    @property
    def toolbar_below(self) -> bool:
        return self._toolbar_below

    def set_toolbar_below(self, below: bool) -> None:
        """Araç çubuğunu kutunun altına alır (üstte yer kalmadığında).

        Hizalama asla feda edilmez; sadece araç çubuğu taşınır.
        """
        if below == self._toolbar_below:
            return
        self._toolbar_below = below
        self._relayout()

    # ==================================================================
    # Font / stil
    # ==================================================================
    def font_pixel_size(self) -> int:
        """PDF puntosunun ekrandaki birebir piksel karşılığı."""
        return max(1, int(round(self.style.size * self.zoom)))

    def editor_font(self) -> QFont:
        """Metin alanının olması gereken fontu (punto piksele çevrilmiş)."""
        font = QFont(self.style.family)
        # DİKKAT: setPointSizeF kullanılmaz. Qt pt->px dönüşümünü ekran
        # DPI'ıyla (96) yapar ve metin PDF'tekinden %33 büyük görünür.
        font.setPixelSize(self.font_pixel_size())
        font.setBold(self.style.bold)
        font.setItalic(self.style.italic)
        return font

    def _apply_style(self) -> None:
        px = self.font_pixel_size()
        color = QColor.fromRgbF(*self.style.color)
        font = self.editor_font()

        # Seçici objectName ile yazılır: uygulama temasının genel
        # ``QWidget { font-size: 13px }`` kuralı aksi halde puntoyu ezer.
        self.editor.setStyleSheet(f"""
            QTextEdit#{self.EDITOR_OBJECT_NAME} {{
                border: none;
                background: transparent;
                color: {color.name()};
                font-family: '{self.style.family}';
                font-size: {px}px;
                font-weight: {'bold' if self.style.bold else 'normal'};
                font-style: {'italic' if self.style.italic else 'normal'};
                padding: 0px;
                margin: 0px;
                selection-background-color: #89B4FA;
            }}
        """)
        self.editor.setFont(font)
        self.editor.document().setDefaultFont(font)

        fmt = QTextCharFormat()
        # setFont(), piksel boyutunu koruyarak aktarır; setFontPointSize()
        # ise DPI ölçeklemesi yüzünden kaymaya yol açar.
        fmt.setFont(font)
        fmt.setForeground(color)
        self._apply_char_format(fmt)
        self._relayout()

    def _apply_char_format(self, fmt: QTextCharFormat) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
            self.editor.setTextCursor(cursor)
        else:
            position = cursor.position()
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(fmt)
            cursor.clearSelection()
            cursor.setPosition(min(position, self.editor.document().characterCount() - 1))
            self.editor.setTextCursor(cursor)
        self.editor.setCurrentCharFormat(fmt)

    def _on_font_size_changed(self, size: float) -> None:
        self.style.size = float(size)
        self._apply_style()

    def _on_color_changed(self, color: QColor) -> None:
        self.style.color = (color.redF(), color.greenF(), color.blueF())
        self._apply_style()

    def _on_bold_toggled(self, checked: bool) -> None:
        self.style.bold = bool(checked)
        self._apply_style()

    def _on_italic_toggled(self, checked: bool) -> None:
        self.style.italic = bool(checked)
        self._apply_style()

    # ==================================================================
    # Yerleşim
    # ==================================================================
    def _text_height_px(self) -> int:
        doc = self.editor.document()
        doc.setTextWidth(float(self._text_w))
        height = doc.size().height()
        return max(int(round(height)), self.line_advance_px(), 1)

    def _relayout(self) -> None:
        origin = self.text_origin()
        text_w = int(self._text_w)
        text_h = self._text_height_px()
        border = self.BORDER

        self.editor.setGeometry(origin.x(), origin.y(), text_w, text_h)

        box = QRect(
            self.HANDLE_W,
            origin.y() - border,
            text_w + 2 * border,
            text_h + 2 * border,
        )
        self._box_rect = box
        self.drag_handle.setGeometry(0, box.y(), self.HANDLE_W, box.height())
        self.resize_handle.setGeometry(box.right() + 1, box.y(), self.HANDLE_W, box.height())

        tb_size = self.toolbar.sizeHint()
        tb_y = box.bottom() + 1 + self.TOOLBAR_GAP if self._toolbar_below else 0
        self.toolbar.setGeometry(self.HANDLE_W, tb_y, tb_size.width(), tb_size.height())

        width = max(box.right() + 1 + self.HANDLE_W, self.HANDLE_W + tb_size.width())
        height = (tb_y + tb_size.height()) if self._toolbar_below else (box.bottom() + 1)
        # resize() sol-üst köşeyi sabit tutar -> metin başlangıcı kaymaz.
        self.resize(width, height)

        # Kutu yüksekliği metne göre büyüdü; pdf_rect'i güncel tut.
        x0, y0, x1, _ = self.pdf_rect
        self.pdf_rect = (x0, y0, x1, y0 + text_h / self.zoom)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        """Yalnızca metin kutusunun zeminini ve kesikli çerçevesini çizer.

        Çerçeve metin alanının *dışına* çizilir; layout'a girmediği için
        ilk karakterin konumunu etkilemez.
        """
        if self._box_rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        inner = self._box_rect.adjusted(
            self.BORDER // 2, self.BORDER // 2, -self.BORDER // 2, -self.BORDER // 2
        )
        painter.setPen(QPen(QColor("#1976D2"), self.BORDER, Qt.DashLine))
        painter.setBrush(QColor(255, 255, 255, 245))
        painter.drawRoundedRect(inner, 3, 3)
        painter.end()

    # ==================================================================
    # Etkileşim (taşıma / boyutlandırma / zoom)
    # ==================================================================
    def move_by_pixels(
        self, dx: int, dy: int, base_rect: tuple[float, float, float, float]
    ) -> None:
        z = self.zoom
        self.pdf_rect = (
            base_rect[0] + dx / z,
            base_rect[1] + dy / z,
            base_rect[2] + dx / z,
            base_rect[3] + dy / z,
        )
        self.rectChanged.emit()

    def align_baseline_to(self, baseline_pt: float) -> None:
        """Kutuyu, ilk satırın taban çizgisi ``baseline_pt`` olacak şekilde kaydırır.

        Var olan bir metin düzenlenirken kullanılır: kutu üstü, düzenleyicinin
        *kendi* metriklerinden geriye hesaplandığı için onay anında üretilen
        origin değeri hedef taban çizgisiyle birebir aynı olur.
        """
        x0, y0, x1, y1 = self.pdf_rect
        new_y0 = float(baseline_pt) - self.baseline_offset_pt()
        self.pdf_rect = (x0, new_y0, x1, new_y0 + (y1 - y0))
        self.rectChanged.emit()

    def set_text_width_px(self, width_px: int) -> None:
        width_px = max(self.MIN_TEXT_W, int(width_px))
        if width_px == self._text_w:
            return
        self._text_w = width_px
        x0, y0, _, y1 = self.pdf_rect
        self.pdf_rect = (x0, y0, x0 + width_px / self.zoom, y1)
        self._relayout()

    def set_zoom(self, zoom: float) -> None:
        zoom = max(0.05, float(zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        self.zoom = zoom
        width_pt = max(1.0, self.pdf_rect[2] - self.pdf_rect[0])
        self._text_w = max(self.MIN_TEXT_W, int(round(width_pt * zoom)))
        self._apply_style()

    # ==================================================================
    # Taban çizgisi ölçümü
    # ==================================================================
    def _first_line(self):
        block = self.editor.document().firstBlock()
        layout = block.layout() if block.isValid() else None
        if layout is not None and layout.lineCount() > 0:
            return layout.lineAt(0)
        return None

    def first_baseline_px(self) -> float:
        """Metin alanının üstünden ilk satırın taban çizgisine olan mesafe."""
        line = self._first_line()
        if line is not None:
            return float(line.y() + line.ascent())
        return QFontMetricsF(self.editor_font()).ascent()

    def line_advance_px(self) -> int:
        """İki taban çizgisi arası mesafe (px)."""
        line = self._first_line()
        if line is not None and line.height() > 0:
            return int(round(line.height()))
        return int(round(QFontMetricsF(self.editor_font()).lineSpacing()))

    def _pixel_rounding_scale(self) -> float:
        """``QFont.setPixelSize`` tam sayı istediği için oluşan sapmanın düzeltmesi.

        Ekranda font ``round(size * zoom)`` pikselle çizilir; PDF ise tam
        ``size`` puntoyla yazılır. Qt'den okunan metrikler bu yüzden en fazla
        yarım piksellik bir hata taşır. PDF uzayına çevirirken oranla düzeltilir.
        """
        rounded = float(self.font_pixel_size())
        exact = self.style.size * self.zoom
        if rounded <= 0 or exact <= 0:
            return 1.0
        return exact / rounded

    def baseline_offset_pt(self) -> float:
        """Kutu üstünden ilk taban çizgisine olan mesafe — PDF punto cinsinden."""
        return self.first_baseline_px() * self._pixel_rounding_scale() / self.zoom

    def line_height_pt(self) -> float:
        """Satırlar arası taban çizgisi mesafesi — PDF punto cinsinden."""
        return self.line_advance_px() * self._pixel_rounding_scale() / self.zoom

    # ==================================================================
    # Onay / iptal
    # ==================================================================
    def result(self) -> InlineTextResult | None:
        text = self.editor.toPlainText().rstrip()
        if not text.strip():
            return None
        x0, y0 = self.pdf_rect[0], self.pdf_rect[1]
        return InlineTextResult(
            page_index=self.page_index,
            rect=self.pdf_rect,
            text=text,
            style=TextStyle(
                family=self.style.family,
                size=self.style.size,
                color=self.style.color,
                bold=self.style.bold,
                italic=self.style.italic,
                align=0,
            ),
            origin=(x0, y0 + self.baseline_offset_pt()),
            line_height=self.line_height_pt(),
        )

    def commit(self) -> None:
        payload = self.result()
        if payload is None:
            self.cancelRequested.emit()
            return
        self.commitRequested.emit(payload)
