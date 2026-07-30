"""Ana uygulama penceresi: menüler, araç çubukları, kenar çubuğu ve tüm akışlar."""
from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QByteArray, QRegularExpression, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .. import __app_name__, __version__
from ..core import exporter, page_ops, xfa, xfa_render
from ..core.document import PasswordRequired, PdfError
from ..services.document_controller import DocumentController
from ..services.settings import AppSettings
from ..services.updater import UpdaterService
from . import icons, theme
from .dialogs import (
    CompressDialog,
    ExportImagesDialog,
    MergeDialog,
    PasswordPrompt,
    PropertiesDialog,
    SecurityDialog,
    SignatureDialog,
    SplitDialog,
    WatermarkDialog,
)
from .dialogs.common import ColorButton
from .file_drop import dropped_files
from .page_view import PdfView, ViewMode, ZoomMode
from .panels import OutlinePanel, SearchPanel, ThumbnailPanel
from .tools import LABELS, Tool, ToolState

IMAGE_FILTER = "Görseller (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)"
PDF_FILTER = "PDF dosyaları (*.pdf)"
#: Açma iletişimi: uzantısı bozuk/farklı dosyalar da seçilebilsin. Uygulama
#: biçimi içeriğe bakarak çözer (bkz. ``app.core.document.open_tolerant``).
OPEN_FILTER = (
    "Belgeler (*.pdf *.xps *.oxps *.epub *.mobi *.fb2 *.cbz *.svg "
    "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;"
    "PDF dosyaları (*.pdf);;Tüm dosyalar (*)"
)

#: Araç çubuğundaki düzenleme araçları: (araç, simge, ipucu)
TOOL_BUTTONS = [
    (Tool.SELECT, "select", "Metin seç / imleç"),
    (Tool.HAND, "hand", "Sayfayı kaydır (Boşluk)"),
    (Tool.HIGHLIGHT, "highlight", "Metni vurgula"),
    (Tool.UNDERLINE, "underline", "Metnin altını çiz"),
    (Tool.STRIKEOUT, "strikethrough", "Metnin üstünü çiz"),
    (Tool.PENCIL, "pencil", "Serbest çizim"),
    (Tool.ERASER, "eraser", "Açıklama sil"),
    (Tool.RECT, "shape_rect", "Dikdörtgen"),
    (Tool.ELLIPSE, "shape_circle", "Daire / elips"),
    (Tool.LINE, "shape_line", "Çizgi"),
    (Tool.ARROW, "shape_arrow", "Ok"),
    (Tool.TEXT, "text", "Metin kutusu ekle"),
    (Tool.IMAGE, "image", "Görsel ekle"),
    (Tool.SIGNATURE, "signature", "İmza ekle"),
]

ZOOM_ITEMS = ["Sayfaya sığdır", "Genişliğe sığdır", "%50", "%75", "%100", "%125",
              "%150", "%200", "%300", "%400"]


class MainWindow(QMainWindow):
    """Uygulamanın tek ana penceresi."""

    def __init__(self, settings: AppSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings or AppSettings()
        self.controller = DocumentController(self)
        self.tools = ToolState(self)
        self._actions: dict[str, QAction] = {}
        self._icon_names: dict[QAction, str] = {}
        self._syncing = False
        #: Güncelleme servisi ilk ihtiyaç duyulduğunda kurulur (bkz. ``updater``)
        self._updater: UpdaterService | None = None
        #: Açık belgedeki XFA formu (yoksa None)
        self._xfa_form = None
        #: Çizilen formun kaynağı: (şablon, değerler). Çizim belgeyi
        #: değiştirdiği için XFA artık açık belgede bulunmaz; alternatif
        #: görünüme (tüm bölümler) geçebilmek için kaynak burada saklanır.
        self._xfa_source: tuple[bytes, dict] | None = None
        self._update_progress = None
        self._quitting_for_update = False

        self.setWindowTitle(__app_name__)
        self.setAcceptDrops(True)
        self.setMinimumSize(940, 640)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks)

        self.view = PdfView(self.controller, self.tools, self)
        # Dinamik XFA formları sayfa akışında bulunmaz; kendi canlı görünümünde
        # açılır (bkz. _open_xfa_live). İki görünüm burada takas edilir.
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.view)
        self.setCentralWidget(self.stack)
        self.xfa_view = None
        # Belge alanı sürükleme olaylarını kendi tükettiği için dosyayı
        # buradan alırız; aksi hâlde pencerenin ortasına bırakmak çalışmaz.
        self.view.filesDropped.connect(self.open_dropped_files)

        self._build_panels()
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()
        self._connect()
        self._restore_state()
        self._update_actions()
        self._update_title()

    # ==================================================================
    # Kurulum
    # ==================================================================
    def _build_panels(self) -> None:
        self.thumbnails = ThumbnailPanel(self.controller, self)
        self.thumbnails.filesDropped.connect(self.open_dropped_files)
        self.outline = OutlinePanel(self.controller, self)
        self.search = SearchPanel(self.controller, self)

        self.sidebar_tabs = QTabWidget(self)
        self.sidebar_tabs.setDocumentMode(True)
        self.sidebar_tabs.setIconSize(QSize(18, 18))
        # Sekme çubuğunun kendi taban çizgisi tema dışı (koyu gri) çiziliyor;
        # etkin sekmeyi zaten vurgu renkli alt çizgi gösteriyor.
        self.sidebar_tabs.tabBar().setDrawBase(False)
        self.sidebar_tabs.addTab(self.thumbnails, icons.icon("thumbnails", size=18), "")
        self.sidebar_tabs.addTab(self.outline, icons.icon("bookmark", size=18), "")
        self.sidebar_tabs.addTab(self.search, icons.icon("search", size=18), "")
        self.sidebar_tabs.setTabToolTip(0, "Sayfa önizlemeleri")
        self.sidebar_tabs.setTabToolTip(1, "İçindekiler")
        self.sidebar_tabs.setTabToolTip(2, "Ara (Ctrl+F)")

        self.dock = QDockWidget("Kenar çubuğu", self)
        self.dock.setObjectName("sidebarDock")
        self.dock.setWidget(self.sidebar_tabs)
        self.dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable
        )
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock)
        self.resizeDocks([self.dock], [300], Qt.Horizontal)

    # ------------------------------------------------------------------
    def _act(
        self,
        key: str,
        text: str,
        icon: str | None = None,
        shortcut=None,
        slot=None,
        checkable: bool = False,
        tip: str | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if icon:
            action.setIcon(icons.icon(icon))
            self._icon_names[action] = icon
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
        if checkable:
            action.setCheckable(True)
        if slot is not None:
            action.triggered.connect(slot)
        hint = tip or text
        if action.shortcut().toString():
            hint = f"{hint}  ({action.shortcut().toString()})"
        action.setToolTip(hint)
        action.setStatusTip(hint)
        self._actions[key] = action
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        A = self._act
        # -- dosya ------------------------------------------------------
        A("new", "Yeni boş belge", "new", QKeySequence.New, self.new_document)
        A("open", "Aç…", "open", QKeySequence.Open, self.open_dialog)
        A("save", "Kaydet", "save", QKeySequence.Save, self.save)
        A("save_as", "Farklı kaydet…", "save_as", "Ctrl+Shift+S", self.save_as)
        A("print", "Yazdır…", "print", QKeySequence.Print, self.print_document)
        A("close", "Belgeyi kapat", "close", "Ctrl+W", self.close_document)
        A("quit", "Çıkış", "exit", "Ctrl+Q", self.close)
        A("properties", "Belge bilgileri…", "properties", "Ctrl+D", self.show_properties)

        # -- düzenle ----------------------------------------------------
        A("undo", "Geri al", "undo", QKeySequence.Undo, self.controller.undo)
        A("redo", "Yinele", "redo", "Ctrl+Y", self.controller.redo)
        A("copy", "Kopyala", "copy", QKeySequence.Copy, self.view.copy_selection)
        A("find", "Bul…", "search", QKeySequence.Find, self.focus_search)
        A("find_next", "Sonraki sonuç", None, "F3", self.search.next_hit)
        A("find_prev", "Önceki sonuç", None, "Shift+F3", self.search.prev_hit)
        A("clear_annots", "Sayfadaki açıklamaları temizle", "eraser", None,
          self.clear_page_annotations)

        # -- görünüm ----------------------------------------------------
        A("zoom_in", "Yakınlaştır", "zoom_in", QKeySequence.ZoomIn, self.zoom_in)
        A("zoom_out", "Uzaklaştır", "zoom_out", QKeySequence.ZoomOut, self.zoom_out)
        A("zoom_actual", "Gerçek boyut", "zoom_actual", "Ctrl+0", self.zoom_actual)
        A("fit_page", "Sayfaya sığdır", "fit_page", "Ctrl+9",
          lambda: self.view.set_zoom_mode(ZoomMode.FIT_PAGE))
        A("fit_width", "Genişliğe sığdır", "fit_width", "Ctrl+8",
          lambda: self.view.set_zoom_mode(ZoomMode.FIT_WIDTH))

        A("view_single", "Tek sayfa", "view_single", "Ctrl+1",
          lambda: self.set_view_mode(ViewMode.SINGLE), checkable=True)
        A("view_continuous", "Sürekli kaydırma", "view_continuous", "Ctrl+2",
          lambda: self.set_view_mode(ViewMode.CONTINUOUS), checkable=True)
        A("view_double", "Çift sayfa", "view_double", "Ctrl+3",
          lambda: self.set_view_mode(ViewMode.DOUBLE), checkable=True)
        self.view_group = QActionGroup(self)
        self.view_group.setExclusive(True)
        for key in ("view_single", "view_continuous", "view_double"):
            self.view_group.addAction(self._actions[key])

        A("sidebar", "Kenar çubuğu", "sidebar", "Ctrl+B", self.toggle_sidebar,
          checkable=True)
        A("fullscreen", "Tam ekran", None, "F11", self.toggle_fullscreen, checkable=True)
        A("theme", "Temayı değiştir", "theme_light", "Ctrl+T", self.toggle_theme)

        # -- gezinme ----------------------------------------------------
        A("first", "İlk sayfa", "first", "Ctrl+Home",
          lambda: self._page_step(first=True))
        A("prev", "Önceki sayfa", "prev", "PgUp", lambda: self._page_step(-1))
        A("next", "Sonraki sayfa", "next", "PgDown", lambda: self._page_step(1))
        A("last", "Son sayfa", "last", "Ctrl+End",
          lambda: self._page_step(last=True))
        A("goto", "Sayfaya git…", None, "Ctrl+G", self.goto_page_dialog)

        # -- sayfa işlemleri --------------------------------------------
        A("rotate_cw", "Sayfayı sağa döndür", "rotate_cw", "Ctrl+R",
          lambda: self.rotate_current(90))
        A("rotate_ccw", "Sayfayı sola döndür", "rotate_ccw", "Ctrl+Shift+R",
          lambda: self.rotate_current(-90))
        A("rotate_all_cw", "Tüm sayfaları sağa döndür", None, None,
          lambda: self.rotate_all(90))
        A("rotate_all_ccw", "Tüm sayfaları sola döndür", None, None,
          lambda: self.rotate_all(-90))
        A("page_add", "Boş sayfa ekle", "page_add", None, self.insert_blank_page)
        A("page_duplicate", "Sayfayı çoğalt", "page_duplicate", None, self.duplicate_current)
        A("page_extract", "Sayfaları dışa aktar…", "page_extract", None,
          self.extract_pages_dialog)
        A("page_delete", "Sayfayı sil", "page_delete", "Ctrl+Delete", self.delete_current)

        # -- araçlar ----------------------------------------------------
        A("merge", "PDF'leri birleştir…", "merge", None, self.merge_dialog)
        A("split", "PDF'i böl…", "split", None, self.split_dialog)
        A("watermark", "Filigran ekle…", "watermark", None, self.watermark_dialog)
        # XFA yalnızca öyle bir form açıldığında etkinleşir (bkz. _check_xfa_form)
        A("xfa_export", "Doldurulmuş formu PDF'e aktar…", "save", None,
          self.export_xfa_pdf).setEnabled(False)
        A("xfa_reload", "Formu baştan yükle", None, None,
          self._open_xfa_live).setEnabled(False)
        A("xfa_render", "Formu görüntüle (XFA)", "text", None,
          self.render_xfa_form).setEnabled(False)
        A("xfa_render_all", "Formu tüm bölümleriyle görüntüle", "text", None,
          self.render_xfa_form_all).setEnabled(False)
        A("xfa_form", "Etkileşimli formu doldur…", "text", None,
          self.xfa_form_dialog).setEnabled(False)
        A("export_images", "Görsele dönüştür…", "export_image", None, self.export_images_dialog)
        A("export_text", "Metin olarak kaydet…", None, None, self.export_text_dialog)
        A("compress", "Sıkıştır / optimize et…", "compress", None, self.compress_dialog)
        A("encrypt", "Parola koy…", "lock", None, self.encrypt_dialog)
        A("decrypt", "Parolayı kaldır…", "unlock", None, self.decrypt_document)
        A("images_to_pdf", "Görsellerden PDF oluştur…", "image", None, self.images_to_pdf_dialog)

        # -- yardım -----------------------------------------------------
        A("shortcuts", "Klavye kısayolları", "help", "F1", self.show_shortcuts)
        A("check_updates", "Güncellemeleri Kontrol Et…", None, None,
          self.check_for_updates)
        A("update_on_startup", "Açılışta güncelleme kontrol et", None, None,
          self.set_update_check_on_startup, checkable=True)
        self._actions["update_on_startup"].setChecked(
            self.settings.update_check_on_startup
        )
        A("about", "Hakkında", None, None, self.show_about)

        # -- araç seçimi ------------------------------------------------
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, icon_name, tip in TOOL_BUTTONS:
            action = QAction(icons.icon(icon_name), LABELS[tool], self)
            action.setCheckable(True)
            action.setToolTip(tip)
            action.setStatusTip(tip)
            action.triggered.connect(lambda _c=False, t=tool: self.tools.set_tool(t))
            self._icon_names[action] = icon_name
            self.tool_group.addAction(action)
            self.tool_actions[tool] = action
        self.tool_actions[Tool.SELECT].setChecked(True)

    # ------------------------------------------------------------------
    def _build_menus(self) -> None:
        a = self._actions
        bar = self.menuBar()

        m_file = bar.addMenu("&Dosya")
        m_file.addAction(a["new"])
        m_file.addAction(a["open"])
        self.menu_recent = QMenu("Son kullanılanlar", self)
        self.menu_recent.setIcon(icons.icon("open"))
        m_file.addMenu(self.menu_recent)
        m_file.addSeparator()
        m_file.addAction(a["save"])
        m_file.addAction(a["save_as"])
        m_file.addSeparator()
        m_file.addAction(a["export_images"])
        m_file.addAction(a["export_text"])
        m_file.addAction(a["page_extract"])
        m_file.addSeparator()
        m_file.addAction(a["print"])
        m_file.addAction(a["properties"])
        m_file.addSeparator()
        m_file.addAction(a["close"])
        m_file.addAction(a["quit"])

        m_edit = bar.addMenu("Dü&zenle")
        m_edit.addAction(a["undo"])
        m_edit.addAction(a["redo"])
        m_edit.addSeparator()
        m_edit.addAction(a["copy"])
        m_edit.addSeparator()
        m_edit.addAction(a["find"])
        m_edit.addAction(a["find_next"])
        m_edit.addAction(a["find_prev"])
        m_edit.addSeparator()
        m_edit.addAction(a["clear_annots"])

        m_view = bar.addMenu("&Görünüm")
        m_view.addAction(a["zoom_in"])
        m_view.addAction(a["zoom_out"])
        m_view.addAction(a["zoom_actual"])
        m_view.addAction(a["fit_page"])
        m_view.addAction(a["fit_width"])
        m_view.addSeparator()
        m_view.addAction(a["view_single"])
        m_view.addAction(a["view_continuous"])
        m_view.addAction(a["view_double"])
        m_view.addSeparator()
        m_view.addAction(a["sidebar"])
        m_view.addAction(a["fullscreen"])
        m_view.addAction(a["theme"])

        m_page = bar.addMenu("&Sayfa")
        m_page.addAction(a["goto"])
        m_page.addAction(a["first"])
        m_page.addAction(a["prev"])
        m_page.addAction(a["next"])
        m_page.addAction(a["last"])
        m_page.addSeparator()
        m_page.addAction(a["rotate_cw"])
        m_page.addAction(a["rotate_ccw"])
        m_page.addAction(a["rotate_all_cw"])
        m_page.addAction(a["rotate_all_ccw"])
        m_page.addSeparator()
        m_page.addAction(a["page_add"])
        m_page.addAction(a["page_duplicate"])
        m_page.addAction(a["page_extract"])
        m_page.addAction(a["page_delete"])

        m_tools = bar.addMenu("&Araçlar")
        for tool, _icon, _tip in TOOL_BUTTONS:
            m_tools.addAction(self.tool_actions[tool])
        m_tools.addSeparator()
        m_tools.addAction(a["watermark"])
        m_tools.addSeparator()
        m_tools.addAction(a["xfa_export"])
        m_tools.addAction(a["xfa_reload"])
        m_tools.addAction(a["xfa_render"])
        m_tools.addAction(a["xfa_render_all"])
        m_tools.addAction(a["xfa_form"])
        m_tools.addSeparator()
        m_tools.addAction(a["merge"])
        m_tools.addAction(a["split"])
        m_tools.addAction(a["images_to_pdf"])
        m_tools.addSeparator()
        m_tools.addAction(a["compress"])
        m_tools.addAction(a["encrypt"])
        m_tools.addAction(a["decrypt"])

        m_help = bar.addMenu("&Yardım")
        m_help.addAction(a["shortcuts"])
        m_help.addSeparator()
        m_help.addAction(a["check_updates"])
        m_help.addAction(a["update_on_startup"])
        m_help.addSeparator()
        m_help.addAction(a["about"])

        self.menu_recent.aboutToShow.connect(self._fill_recent_menu)

    # ------------------------------------------------------------------
    def _build_toolbars(self) -> None:
        a = self._actions

        self.tb_main = QToolBar("Ana araç çubuğu", self)
        self.tb_main.setObjectName("mainToolBar")
        self.tb_main.setIconSize(QSize(22, 22))
        self.tb_main.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.tb_main)

        for key in ("new", "open", "save", "print"):
            self.tb_main.addAction(a[key])
        self.tb_main.addSeparator()
        self.tb_main.addAction(a["undo"])
        self.tb_main.addAction(a["redo"])
        self.tb_main.addSeparator()
        for key in ("first", "prev", "next", "last"):
            self.tb_main.addAction(a[key])
        self.tb_main.addSeparator()
        for key in ("zoom_out", "zoom_in", "fit_width", "fit_page"):
            self.tb_main.addAction(a[key])
        self.tb_main.addSeparator()
        for key in ("view_single", "view_continuous", "view_double"):
            self.tb_main.addAction(a[key])
        self.tb_main.addSeparator()
        for key in ("rotate_ccw", "rotate_cw"):
            self.tb_main.addAction(a[key])
        self.tb_main.addSeparator()
        for key in ("merge", "split", "compress", "export_images"):
            self.tb_main.addAction(a[key])

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        spacer.setStyleSheet("background: transparent; border: none;")
        self.tb_main.addWidget(spacer)
        self.tb_main.addAction(a["find"])
        self.tb_main.addAction(a["sidebar"])
        self.tb_main.addAction(a["theme"])

        # -- düzenleme araçları ----------------------------------------
        self.tb_tools = QToolBar("Düzenleme araçları", self)
        self.tb_tools.setObjectName("toolsToolBar")
        self.tb_tools.setIconSize(QSize(20, 20))
        self.tb_tools.setMovable(False)
        self.addToolBarBreak(Qt.TopToolBarArea)   # kendi satırında dursun
        self.addToolBar(Qt.TopToolBarArea, self.tb_tools)

        for tool, _icon, _tip in TOOL_BUTTONS:
            self.tb_tools.addAction(self.tool_actions[tool])
        self.tb_tools.addSeparator()

        self.tb_tools.addWidget(QLabel(" Çizgi: ", self))
        self.color_stroke = ColorButton(self.tools.defaults.stroke, parent=self)
        self.color_stroke.setToolTip("Çizim rengi")
        self.color_stroke.colorChanged.connect(
            lambda c: self.tools.set_stroke(c or QColor("#e53935"))
        )
        self.tb_tools.addWidget(self.color_stroke)

        self.tb_tools.addWidget(QLabel(" Dolgu: ", self))
        self.color_fill = ColorButton(self.tools.defaults.fill, allow_none=True, parent=self)
        self.color_fill.setToolTip("Şekil dolgu rengi (İptal = dolgusuz)")
        self.color_fill.colorChanged.connect(self.tools.set_fill)
        self.tb_tools.addWidget(self.color_fill)

        self.tb_tools.addWidget(QLabel(" Vurgu: ", self))
        self.color_highlight = ColorButton(self.tools.defaults.highlight, parent=self)
        self.color_highlight.setToolTip("Vurgulama rengi")
        self.color_highlight.colorChanged.connect(
            lambda c: self.tools.set_highlight(c or QColor("#ffeb3b"))
        )
        self.tb_tools.addWidget(self.color_highlight)

        self.tb_tools.addWidget(QLabel(" Kalınlık: ", self))
        self.width_spin = QSpinBox(self)
        self.width_spin.setRange(1, 24)
        self.width_spin.setValue(int(self.tools.defaults.width))
        self.width_spin.setSuffix(" pt")
        self.width_spin.setToolTip("Çizgi kalınlığı")
        self.width_spin.valueChanged.connect(lambda v: self.tools.set_width(float(v)))
        self.tb_tools.addWidget(self.width_spin)

        self.tb_tools.addWidget(QLabel(" Saydamlık: ", self))
        self.opacity_spin = QSpinBox(self)
        self.opacity_spin.setRange(5, 100)
        self.opacity_spin.setValue(int(self.tools.defaults.opacity * 100))
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setToolTip("Açıklama saydamlığı")
        self.opacity_spin.valueChanged.connect(lambda v: self.tools.set_opacity(v / 100.0))
        self.tb_tools.addWidget(self.opacity_spin)

        self.tb_tools.addSeparator()
        self.tb_tools.addAction(a["watermark"])
        self.tb_tools.addAction(a["clear_annots"])

    # ------------------------------------------------------------------
    def _build_statusbar(self) -> None:
        bar = self.statusBar()

        self.page_spin = QSpinBox(self)
        self.page_spin.setRange(0, 0)
        self.page_spin.setPrefix("Sayfa ")
        self.page_spin.setFixedWidth(110)
        self.page_spin.setToolTip("Sayfaya git (Ctrl+G)")
        self.page_spin.valueChanged.connect(self._on_page_spin)

        self.page_total = QLabel("/ 0", self)

        self.zoom_combo = QComboBox(self)
        self.zoom_combo.setObjectName("zoomCombo")
        self.zoom_combo.setEditable(True)
        # Serbest yazım yalnızca yüzde değeri için; harf girişi engellenir.
        self.zoom_combo.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"^\s*%?\s*\d{0,4}\s*%?\s*$"), self)
        )
        self.zoom_combo.setInsertPolicy(QComboBox.NoInsert)
        self.zoom_combo.addItems(ZOOM_ITEMS)
        # En uzun seçenek ("Genişliğe sığdır") kırpılmadan sığmalı.
        self.zoom_combo.setFixedWidth(186)
        self.zoom_combo.setToolTip("Yakınlaştırma")
        self.zoom_combo.activated.connect(self._on_zoom_combo)
        self.zoom_combo.lineEdit().returnPressed.connect(
            lambda: self._on_zoom_text(self.zoom_combo.currentText())
        )

        self.info_label = QLabel("", self)

        bar.addPermanentWidget(self.info_label)
        bar.addPermanentWidget(self.page_spin)
        bar.addPermanentWidget(self.page_total)
        bar.addPermanentWidget(self.zoom_combo)
        bar.showMessage("Hazır")

    # ------------------------------------------------------------------
    def _connect(self) -> None:
        c = self.controller
        c.documentOpened.connect(self._on_document_opened)
        c.documentClosed.connect(self._on_document_closed)
        c.documentReplaced.connect(self._on_document_replaced)
        c.dirtyChanged.connect(lambda _d: self._update_title())
        c.historyChanged.connect(self._update_actions)
        c.message.connect(self.show_message)

        self.view.currentPageChanged.connect(self._on_page_changed)
        self.view.zoomChanged.connect(self._on_zoom_changed)
        self.view.status.connect(self.show_message)
        self.view.requestText.connect(self._on_request_text)
        self.view.requestImage.connect(self._on_request_image)
        self.view.requestSignature.connect(self._on_request_signature)

        self.thumbnails.pageActivated.connect(lambda i: self.view.go_to_page(i))
        self.thumbnails.status.connect(self.show_message)
        self.outline.pageActivated.connect(lambda i: self.view.go_to_page(i))
        self.search.resultsChanged.connect(self.view.set_search_results)
        self.search.activeHitChanged.connect(self._on_active_hit)
        self.search.status.connect(self.show_message)

        self.tools.toolChanged.connect(self._on_tool_changed)
        self.dock.visibilityChanged.connect(self._on_dock_visibility)

    # ------------------------------------------------------------------
    def _restore_state(self) -> None:
        geometry, state = self.settings.restore_window()
        if isinstance(geometry, (QByteArray, bytes)) and len(geometry):
            self.restoreGeometry(geometry)
        else:
            self.resize(1280, 860)
        if isinstance(state, (QByteArray, bytes)) and len(state):
            self.restoreState(state)

        mode = self.settings.view_mode
        try:
            view_mode = ViewMode(mode)
        except ValueError:
            view_mode = ViewMode.CONTINUOUS
        self.view.set_view_mode(view_mode)
        self._actions[f"view_{view_mode.value}"].setChecked(True)

        try:
            zoom_mode = ZoomMode(self.settings.zoom_mode)
        except ValueError:
            zoom_mode = ZoomMode.FIT_WIDTH
        if zoom_mode is not ZoomMode.CUSTOM:
            self.view.set_zoom_mode(zoom_mode)

        visible = self.settings.sidebar_visible
        self.dock.setVisible(visible)
        self._actions["sidebar"].setChecked(visible)

        self.tools.set_stroke(QColor(self.settings.tool_color))
        self.tools.set_highlight(QColor(self.settings.highlight_color))
        self.tools.set_width(self.settings.tool_width)
        self.color_stroke.set_color(self.tools.defaults.stroke)
        self.color_highlight.set_color(self.tools.defaults.highlight)
        self.width_spin.setValue(int(self.tools.defaults.width))
        self._sync_theme_action()

    # ==================================================================
    # Durum güncellemeleri
    # ==================================================================
    def show_message(self, text: str, timeout: int = 6000) -> None:
        if text:
            self.statusBar().showMessage(text, timeout)

    def _update_title(self) -> None:
        if self.controller.is_open:
            name = self.controller.title()
            self.setWindowTitle(f"{__app_name__} - [{name}]")
        else:
            self.setWindowTitle(__app_name__)

    def _update_actions(self) -> None:
        has_doc = self.controller.is_open
        pages = self.controller.page_count
        for key in (
            "save", "save_as", "print", "close", "properties", "copy", "find",
            "find_next", "find_prev", "clear_annots", "zoom_in", "zoom_out",
            "zoom_actual", "fit_page", "fit_width", "first", "prev", "next", "last",
            "goto", "rotate_cw", "rotate_ccw", "rotate_all_cw", "rotate_all_ccw",
            "page_add", "page_duplicate", "page_extract", "page_delete", "watermark",
            "export_images", "export_text", "compress", "encrypt", "decrypt", "split",
        ):
            self._actions[key].setEnabled(has_doc)
        self._actions["page_delete"].setEnabled(has_doc and pages > 1)
        self._actions["undo"].setEnabled(self.controller.can_undo())
        self._actions["redo"].setEnabled(self.controller.can_redo())
        for action in self.tool_actions.values():
            action.setEnabled(has_doc)

        # Canlı XFA görünümünde sayfa/açıklama araçları anlamsızdır: belge
        # akışı yalnızca "Adobe gerekli" uyarı sayfasından ibarettir, düzenleme
        # onu değiştirir, formu değil.
        canli = self.in_xfa_mode
        self._actions["xfa_export"].setEnabled(canli)
        self._actions["xfa_reload"].setEnabled(canli)
        if canli:
            for key in (
                "clear_annots", "rotate_cw", "rotate_ccw", "rotate_all_cw",
                "rotate_all_ccw", "page_add", "page_duplicate", "page_extract",
                "page_delete", "watermark", "export_images", "export_text",
                "compress", "copy", "find", "find_next", "find_prev", "split",
            ):
                self._actions[key].setEnabled(False)
            for action in self.tool_actions.values():
                action.setEnabled(False)

        undo_label = self.controller.history.undo_label
        redo_label = self.controller.history.redo_label
        self._actions["undo"].setText(
            f"Geri al: {undo_label}" if undo_label else "Geri al"
        )
        self._actions["redo"].setText(
            f"Yinele: {redo_label}" if redo_label else "Yinele"
        )

    def _update_page_widgets(self) -> None:
        # Canlı XFA'da sayfa sayısı belgeden değil, formun o anki
        # yerleşiminden gelir (bkz. _on_xfa_pages).
        if self.in_xfa_mode:
            return
        pages = self.controller.page_count
        self._syncing = True
        try:
            self.page_spin.setRange(1 if pages else 0, max(pages, 0))
            self.page_spin.setValue(self.controller.current_page + 1 if pages else 0)
            self.page_total.setText(f"/ {pages}")
        finally:
            self._syncing = False

    # ------------------------------------------------------------------
    def _on_document_opened(self, path: str) -> None:
        if path:
            self.settings.add_recent(path)
            self.settings.last_directory = os.path.dirname(path)
            # Diskten yeni bir dosya açıldı; önceki formun kaynağı geçersiz.
            # (Çizim sonucu adsız açılır, yani ``path`` boştur ve kaynak
            # korunur — böylece diğer görünüme geçilebilir.)
            self._xfa_source = None
        self._update_page_widgets()
        self._update_actions()
        self._update_title()
        self._update_info_label()
        onarildi = self.controller.document.was_repaired
        self.show_message(
            f"{self.controller.document.display_name} açıldı "
            f"({self.controller.page_count} sayfa)."
            + (" Dosya bozuktu ya da PDF değildi; onarılarak açıldı — "
               "değişiklikleri 'Farklı Kaydet' ile saklayın."
               if onarildi else "")
        )
        # XFA kontrolü en sonda: uyarı diyaloğu açılışta gösterilir ve
        # yukarıdaki durum mesajının üstüne yazar.
        self._check_xfa_form()

    def _on_document_closed(self) -> None:
        self._leave_xfa_live()
        self._update_page_widgets()
        self._update_actions()
        self._update_title()
        self.info_label.setText("")
        self._xfa_form = None
        self._xfa_source = None
        self._actions["xfa_form"].setEnabled(False)
        self._actions["xfa_render"].setEnabled(False)
        self._actions["xfa_render_all"].setEnabled(False)
        self.show_message("Belge kapatıldı.")

    def _on_document_replaced(self) -> None:
        self._update_page_widgets()
        self._update_actions()
        self._update_title()
        self._update_info_label()
        self._check_xfa_form()

    # ------------------------------------------------------------------
    # XFA (etkileşimli XML) formları
    # ------------------------------------------------------------------
    def current_xfa_form(self):
        """Açık belgedeki XFA formu; yoksa ``None``.

        Yalnızca "belge yok" durumu yutulur. Geniş bir ``except`` burada
        gerçek hataları gizler: ``_check_xfa_form``ın yanlış sinyale bağlı
        olduğu, tam da bu yüzden fark edilmemişti.
        """
        if not self.controller.is_open:
            return None
        try:
            ham = self.controller.document.raw
        except PdfError:
            return None
        return xfa.load(ham)

    def _check_xfa_form(self) -> None:
        """Dinamik XFA açıldığında formu canlı görünümde açar.

        Kullanıcıyı modal bir kutuyla karşılamak yerine — Foxit/Adobe da öyle
        yapar — form sessizce açılır ve durum çubuğunda bilgilendirilir.
        """
        self._xfa_form = self.current_xfa_form()
        var = self._xfa_form is not None and bool(self._xfa_form.editable_fields)
        self._actions["xfa_form"].setEnabled(var)
        # Statik çizim sonrası açık belgede XFA kalmaz; kaynak saklandığı
        # sürece diğer görünüme geçilebilmelidir.
        cizilebilir = var or self._xfa_source is not None
        self._actions["xfa_render"].setEnabled(cizilebilir)
        self._actions["xfa_render_all"].setEnabled(cizilebilir)
        if not var or not self._xfa_form.dynamic:
            self._leave_xfa_live()
            return

        # Açılış bir sonraki olay döngüsüne bırakılır: belge açma sinyalleri
        # daha akıp bitmeden görünümü değiştirmek panelleri tutarsız bırakır.
        QTimer.singleShot(0, self._open_xfa_live)

    # -- canlı (etkileşimli) görünüm ------------------------------------
    @property
    def in_xfa_mode(self) -> bool:
        return self.xfa_view is not None and self.stack.currentWidget() is self.xfa_view

    def _open_xfa_live(self) -> None:
        """Şablonu derleyip etkileşimli görünümde gösterir."""
        if not self.controller.is_open:
            return
        ham = self.controller.document.raw
        paketler = xfa.read_packets(ham)
        if "template" not in paketler:
            return
        sablon = xfa.packet_data(ham, paketler["template"])
        if not sablon:
            return
        degerler = xfa.read_values(
            xfa.packet_data(ham, paketler["datasets"])
            if "datasets" in paketler else b""
        )
        # Belgeye gömülü yazı tipleri: Foxit/Adobe formu bunlarla çizer.
        # Sistem yazı tipine düşülürse metin genişlikleri sapıyor, etiketler
        # sarıp taşıyor ve tablo başlıkları satırlardan kayıyor.
        yazi_css = xfa.embedded_font_css(ham, xfa.template_typefaces(sablon))

        if self.xfa_view is None:
            try:
                from .xfa_view import XfaFormView
            except ImportError as exc:      # QtWebEngine kurulu değil
                self.show_message(
                    f"Etkileşimli form görünümü kullanılamıyor ({exc}); "
                    "Araçlar ▸ Formu görüntüle ile statik çizime düşebilirsiniz."
                )
                return
            self.xfa_view = XfaFormView(self)
            self.xfa_view.status.connect(self.show_message)
            self.xfa_view.contentChanged.connect(self._on_xfa_edited)
            self.xfa_view.pageCountChanged.connect(self._on_xfa_pages)
            self.xfa_view.formReady.connect(self._on_xfa_ready)
            self.xfa_view.staticRequested.connect(self.render_xfa_form)
            self.xfa_view.host.printRequested.connect(self.export_xfa_pdf)
            self.stack.addWidget(self.xfa_view)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.xfa_view.load_template(sablon, degerler, yazi_css)
        except Exception as exc:  # noqa: BLE001 - olağandışı şablon
            self.show_message(f"Form derlenemedi: {exc}")
            return
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        self._xfa_source = (sablon, degerler)
        self.stack.setCurrentWidget(self.xfa_view)
        self._update_actions()

    def _leave_xfa_live(self) -> None:
        if self.in_xfa_mode:
            self.stack.setCurrentWidget(self.view)
            self._update_actions()

    # -- görünüm komutlarının yönlendirilmesi ---------------------------
    def zoom_in(self) -> None:
        (self.xfa_view if self.in_xfa_mode else self.view).zoom_in()

    def zoom_out(self) -> None:
        (self.xfa_view if self.in_xfa_mode else self.view).zoom_out()

    def zoom_actual(self) -> None:
        (self.xfa_view if self.in_xfa_mode else self.view).zoom_actual()

    def _page_step(self, delta: int = 0, first: bool = False,
                   last: bool = False) -> None:
        if not self.in_xfa_mode:
            if first:
                self.view.first_page()
            elif last:
                self.view.last_page()
            elif delta < 0:
                self.view.prev_page()
            else:
                self.view.next_page()
            return
        toplam = self.xfa_view.page_count
        simdiki = self.page_spin.value() or 1
        hedef = 1 if first else toplam if last else simdiki + delta
        hedef = max(1, min(hedef, toplam))
        self.page_spin.setValue(hedef)
        self.xfa_view.go_to_page(hedef - 1)

    def _on_xfa_ready(self, fields: int, pages: int) -> None:
        self.show_message(
            f"Etkileşimli XFA formu açıldı — {fields} alan, {pages} sayfa. "
            "Seçimlere göre açılan bölümler ve tablo satırları çalışır."
        )
        self._on_xfa_pages(pages)

    def _on_xfa_pages(self, pages: int) -> None:
        self._syncing = True
        try:
            self.page_spin.setRange(1, max(pages, 1))
            self.page_total.setText(f"/ {pages}")
        finally:
            self._syncing = False

    def _on_xfa_edited(self) -> None:
        if not self.controller.document.is_dirty:
            self.controller.document.mark_dirty()
            self._update_title()

    def flush_xfa_values(self) -> bool:
        """Formdaki değerleri belgenin ``datasets`` paketine yazar.

        Kaydetmeden önce çağrılır: XFA'da veri sayfa akışında değil bu pakette
        durur, dolayısıyla dosyayı olduğu gibi kaydetmek yetmez.
        """
        if not self.in_xfa_mode:
            return True
        degerler = self.xfa_view.values_blocking()
        if not degerler:
            return True
        kok = self._xfa_form.root if self._xfa_form else "form"
        if not xfa.write_values(self.controller.document.raw, degerler, kok):
            QMessageBox.warning(
                self, "Form",
                "Form verisi yazılamadı. Belge salt okunur olabilir.")
            return False
        return True

    def export_xfa_pdf(self) -> None:
        """Formun **görünen** hâlini PDF'e aktarır.

        Statik çizimden farkı: betiklerle açılmış bölümler, eklenmiş satırlar
        ve doldurulmuş değerler ekranda ne ise çıktıda da odur.
        """
        if not self.in_xfa_mode:
            return
        baslangic = os.path.join(
            self.settings.last_directory,
            (self.controller.document.display_name or "form").rsplit(".", 1)[0]
            + "_dolu.pdf",
        )
        yol, _ = QFileDialog.getSaveFileName(
            self, "Formu PDF olarak dışa aktar", baslangic, PDF_FILTER)
        if not yol:
            return
        if not yol.lower().endswith(".pdf"):
            yol += ".pdf"

        def bitti(basarili: bool) -> None:
            if basarili:
                self.settings.last_directory = os.path.dirname(yol)
                self.show_message(f"Form PDF olarak kaydedildi: {yol}")
            else:
                QMessageBox.warning(self, "Dışa aktar", "PDF yazılamadı.")

        self.xfa_view.export_pdf(yol, bitti)

    def render_xfa_form_all(self) -> None:
        """Betikle açılan bölümler dâhil, formun tamamını çizer."""
        self.render_xfa_form(show_hidden=True)

    def render_xfa_form(self, show_hidden: bool = False,
                        silent: bool = False) -> bool:
        """XFA şablonunu çizip görüntülenebilir bir belge olarak açar.

        ``show_hidden`` özgün görünümden ayrılır: Adobe/Foxit'te yalnızca
        seçime göre açılan bölümler de çizilir, böylece form tek seferde
        doldurulabilir. ``silent`` otomatik açılış içindir: başarısızlıkta
        uyarı kutusu gösterilmez, ``False`` döner.
        """
        form = self.current_xfa_form()
        if form is not None:
            paketler = xfa.read_packets(self.controller.document.raw)
            if "template" not in paketler:
                return False
            sablon = xfa.packet_data(
                self.controller.document.raw, paketler["template"]
            )
            degerler = form.as_values()
        elif self._xfa_source is not None:
            # Belge zaten çizilmiş; kaynak şablondan diğer görünüm üretilir.
            sablon, degerler = self._xfa_source
        else:
            if not silent:
                QMessageBox.information(
                    self, "Formu görüntüle",
                    "Bu belgede XFA formu bulunamadı.",
                )
            return False

        if self.in_xfa_mode:
            # Canlı görünüme yazılanlar henüz ``datasets`` paketine
            # işlenmemiş olabilir; çizim kullanıcının gördüğü değerlerle
            # yapılmalı, yoksa doldurduğu alanlar boş çıkıyor.
            canli = self.xfa_view.values_blocking()
            if canli:
                degerler = {**degerler, **canli}

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            veri = xfa_render.render_bytes(
                sablon, degerler, show_hidden=show_hidden
            )
        except Exception as exc:  # noqa: BLE001 - olağandışı şablon
            if not silent:
                QMessageBox.warning(
                    self, "Formu görüntüle",
                    f"Form çizilemedi:\n{exc}\n\n"
                    "Alanları yine de Araçlar ▸ Etkileşimli formu doldur… "
                    "ile doldurabilirsiniz.",
                )
            return False
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        kaynak = self.controller.document.display_name
        self._xfa_source = (sablon, degerler)
        self.controller.open_bytes(veri)
        if not silent:
            kapsam = "tüm bölümleriyle " if show_hidden else ""
            self.show_message(
                f"{kaynak} formu {kapsam}görüntülenebilir PDF'e dönüştürüldü. "
                "Alanları doldurup 'Farklı Kaydet' ile kaydedebilirsiniz."
            )
        return True

    def xfa_form_dialog(self) -> None:
        from .dialogs import XfaFormDialog

        form = self.current_xfa_form()
        if form is None or not form.editable_fields:
            QMessageBox.information(
                self, "Etkileşimli form",
                "Bu belgede doldurulabilir XFA form alanı bulunamadı.",
            )
            return

        dialog = XfaFormDialog(form, self)
        if dialog.exec() != QDialog.Accepted:
            return

        degerler = dialog.values()
        if not degerler:
            self.show_message("Form alanı doldurulmadı.")
            return

        if not xfa.write_values(self.controller.document.raw, degerler, form.root):
            QMessageBox.warning(
                self, "Etkileşimli form",
                "Form verisi yazılamadı. Belge salt okunur olabilir.",
            )
            return

        self.controller.document.mark_dirty()
        self._update_title()
        self.show_message(
            f"{len(degerler)} alan dolduruldu. Kalıcı olması için belgeyi kaydedin."
        )

    def _update_info_label(self) -> None:
        if not self.controller.is_open:
            self.info_label.setText("")
            return
        try:
            w, h = self.controller.document.page_size(self.controller.current_page)
            mm = f"{w * 25.4 / 72:.0f}×{h * 25.4 / 72:.0f} mm"
        except Exception:  # noqa: BLE001
            mm = ""
        self.info_label.setText(mm)

    def _on_page_changed(self, index: int) -> None:
        self.controller.set_current_page(index)
        self._update_page_widgets()
        self._update_info_label()
        self.thumbnails.set_current(index)
        self.outline.sync_to_page(index)

    def _on_page_spin(self, value: int) -> None:
        if self._syncing or not self.controller.is_open:
            return
        if self.in_xfa_mode:
            self.xfa_view.go_to_page(value - 1)
            return
        self.view.go_to_page(value - 1)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._syncing = True
        try:
            mode = self.view.zoom_mode
            if mode is ZoomMode.FIT_PAGE:
                self.zoom_combo.setCurrentText("Sayfaya sığdır")
            elif mode is ZoomMode.FIT_WIDTH:
                self.zoom_combo.setCurrentText("Genişliğe sığdır")
            else:
                self.zoom_combo.setCurrentText(f"%{zoom * 100:.0f}")
        finally:
            self._syncing = False

    def _on_zoom_combo(self, index: int) -> None:
        self._on_zoom_text(self.zoom_combo.itemText(index))

    def _on_zoom_text(self, text: str) -> None:
        if self._syncing:
            return
        text = text.strip()
        if text == "Sayfaya sığdır":
            self.view.set_zoom_mode(ZoomMode.FIT_PAGE)
            return
        if text == "Genişliğe sığdır":
            self.view.set_zoom_mode(ZoomMode.FIT_WIDTH)
            return
        digits = text.replace("%", "").replace(",", ".").strip()
        try:
            value = float(digits)
        except ValueError:
            self._on_zoom_changed(self.view.zoom)
            return
        self.view.set_zoom(value / 100.0)

    def _on_active_hit(self, page: int, rect) -> None:
        self.view.set_active_hit(page, rect)
        if page >= 0 and rect is not None:
            self.view.ensure_visible_pt(page, rect)

    def _on_tool_changed(self, tool: Tool) -> None:
        action = self.tool_actions.get(tool)
        if action is not None and not action.isChecked():
            action.setChecked(True)
        hints = {
            Tool.TEXT: "Metin eklemek için sayfada bir alan sürükleyin.",
            Tool.IMAGE: "Görselin yerleşeceği alanı sürükleyin.",
            Tool.SIGNATURE: "İmzanın yerleşeceği alanı sürükleyin.",
            Tool.HIGHLIGHT: "Vurgulanacak metnin üzerinde sürükleyin.",
            Tool.ERASER: "Silinecek açıklamaya tıklayın veya alan sürükleyin.",
        }
        self.show_message(hints.get(tool, f"{LABELS[tool]} aracı etkin."))

    def _on_dock_visibility(self, visible: bool) -> None:
        self._actions["sidebar"].setChecked(visible)
        self.settings.sidebar_visible = visible

    # ==================================================================
    # Dosya işlemleri
    # ==================================================================
    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self.controller.create_empty()
        self.show_message("Yeni boş belge oluşturuldu.")

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Belge aç", self.settings.last_directory, OPEN_FILTER
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        if not os.path.exists(path):
            QMessageBox.warning(self, "Aç", f"Dosya bulunamadı:\n{path}")
            return False
        if not self._confirm_discard():
            return False

        password: str | None = None
        retry = False
        while True:
            try:
                self.controller.open(path, password)
                return True
            except PasswordRequired:
                prompt = PasswordPrompt(os.path.basename(path), retry, self)
                if prompt.exec() != QDialog.Accepted:
                    self.show_message("Parola girilmedi, dosya açılmadı.")
                    return False
                password = prompt.password()
                retry = True
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Aç", f"Dosya açılamadı:\n{exc}")
                return False

    def _fill_recent_menu(self) -> None:
        self.menu_recent.clear()
        recents = self.settings.recent_files()
        if not recents:
            action = self.menu_recent.addAction("(boş)")
            action.setEnabled(False)
            return
        for path in recents:
            action = self.menu_recent.addAction(os.path.basename(path))
            action.setToolTip(path)
            action.triggered.connect(lambda _c=False, p=path: self.open_path(p))
        self.menu_recent.addSeparator()
        self.menu_recent.addAction("Listeyi temizle", self.settings.clear_recent)

    def save(self) -> bool:
        if not self.controller.is_open:
            return False
        if not self.flush_xfa_values():
            return False
        if not self.controller.path:
            return self.save_as()
        try:
            self.controller.save()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Kaydet", f"Kaydedilemedi:\n{exc}")
            return False
        self._update_title()
        return True

    def save_as(self) -> bool:
        if not self.controller.is_open:
            return False
        if not self.flush_xfa_values():
            return False
        start = self.controller.path or os.path.join(
            self.settings.last_directory, "belge.pdf"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Farklı kaydet", start, PDF_FILTER)
        if not path:
            return False
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            self.controller.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Kaydet", f"Kaydedilemedi:\n{exc}")
            return False
        self.settings.add_recent(path)
        self.settings.last_directory = os.path.dirname(path)
        self._update_title()
        return True

    def close_document(self) -> None:
        if not self.controller.is_open:
            return
        if not self._confirm_discard():
            return
        self.controller.close()

    def _confirm_discard(self) -> bool:
        """Kaydedilmemiş değişiklik varsa kullanıcıya sorar."""
        if not (self.controller.is_open and self.controller.is_dirty):
            return True
        answer = QMessageBox.question(
            self,
            "Kaydedilmemiş değişiklikler",
            f"{self.controller.document.display_name} belgesindeki değişiklikler "
            "kaydedilmedi. Ne yapmak istersiniz?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    # ------------------------------------------------------------------
    def print_document(self) -> None:
        if not self.controller.is_open:
            return
        if self.in_xfa_mode:
            # Belge akışı yalnızca "Adobe gerekli" uyarı sayfasıdır; doğrudan
            # yazdırmak formu değil o sayfayı bastırıyordu.
            cevap = QMessageBox.question(
                self, "Yazdır",
                "Etkileşimli form doğrudan yazdırılamıyor. Formun görünen "
                "hâlini PDF'e aktarıp o dosyayı yazdırabilirsiniz.\n\n"
                "Şimdi PDF'e aktarılsın mı?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if cevap == QMessageBox.Yes:
                self.export_xfa_pdf()
            return
        try:
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except ImportError:
            QMessageBox.warning(self, "Yazdır", "Yazdırma desteği bulunamadı.")
            return

        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self.controller.document.display_name)
        printer.setFromTo(1, self.controller.page_count)
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Yazdır")
        if dialog.exec() != QDialog.Accepted:
            return

        first = printer.fromPage() or 1
        last = printer.toPage() or self.controller.page_count
        indices = [i for i in range(first - 1, last) if 0 <= i < self.controller.page_count]
        if not indices:
            return

        try:
            self.paint_pages(printer, indices)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Yazdır", f"Yazdırma başarısız:\n{exc}")
            return
        self.show_message(f"{len(indices)} sayfa yazıcıya gönderildi.")

    def paint_pages(self, printer, indices: list[int]) -> int:
        """Sayfaları verilen yazıcı/çıktı aygıtına çizer (yazdırma çekirdeği)."""
        painter = QPainter()
        if not painter.begin(printer):
            raise RuntimeError("Yazıcı başlatılamadı.")
        dpi = min(300, max(96, printer.resolution()))
        painted = 0
        try:
            for n, index in enumerate(indices):
                if n:
                    printer.newPage()
                rendered = self.controller.document.render_dpi(index, dpi)
                image = QImage(
                    rendered.samples, rendered.width, rendered.height,
                    rendered.stride, QImage.Format_RGB888,
                ).copy()
                target = painter.viewport()
                scaled = image.scaled(
                    target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                x = target.x() + (target.width() - scaled.width()) // 2
                y = target.y() + (target.height() - scaled.height()) // 2
                painter.drawImage(x, y, scaled)
                painted += 1
        finally:
            painter.end()
        return painted

    # ==================================================================
    # Görünüm
    # ==================================================================
    def set_view_mode(self, mode: ViewMode) -> None:
        self.view.set_view_mode(mode)
        self.settings.view_mode = mode.value
        self._actions[f"view_{mode.value}"].setChecked(True)

    def toggle_sidebar(self, checked: bool) -> None:
        self.dock.setVisible(checked)

    def toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def toggle_theme(self) -> None:
        new_name = "light" if theme.current().is_dark else "dark"
        app = QApplication.instance()
        theme.apply(app, new_name)
        self.settings.theme = new_name
        icons.clear_cache()
        for action, icon_name in self._icon_names.items():
            action.setIcon(icons.icon(icon_name))
        self.menu_recent.setIcon(icons.icon("open"))
        self.sidebar_tabs.setTabIcon(0, icons.icon("thumbnails", size=18))
        self.sidebar_tabs.setTabIcon(1, icons.icon("bookmark", size=18))
        self.sidebar_tabs.setTabIcon(2, icons.icon("search", size=18))
        self.search.btn_prev.setIcon(icons.icon("prev", size=18))
        self.search.btn_next.setIcon(icons.icon("next", size=18))
        self.search.count_label.setStyleSheet(f"color: {theme.current().text_muted};")
        self.color_stroke.set_color(self.tools.defaults.stroke)
        self.color_fill.set_color(self.tools.defaults.fill)
        self.color_highlight.set_color(self.tools.defaults.highlight)
        self.view.refresh_theme()
        if self.xfa_view is not None:
            self.xfa_view.refresh_theme()
        self.thumbnails.refresh_theme()
        self.thumbnails.rebuild()
        self._sync_theme_action()
        self.show_message("Tema değiştirildi: " + ("Koyu" if new_name == "dark" else "Açık"))

    def _sync_theme_action(self) -> None:
        dark = theme.current().is_dark
        name = "theme_light" if dark else "theme_dark"
        action = self._actions["theme"]
        action.setIcon(icons.icon(name))
        self._icon_names[action] = name
        action.setText("Açık temaya geç" if dark else "Koyu temaya geç")

    def focus_search(self) -> None:
        self.dock.setVisible(True)
        self._actions["sidebar"].setChecked(True)
        self.sidebar_tabs.setCurrentWidget(self.search)
        self.search.focus_input()

    def goto_page_dialog(self) -> None:
        if not self.controller.is_open:
            return
        value, ok = QInputDialog.getInt(
            self, "Sayfaya git", f"Sayfa numarası (1-{self.controller.page_count}):",
            self.controller.current_page + 1, 1, self.controller.page_count,
        )
        if ok:
            self.view.go_to_page(value - 1)

    # ==================================================================
    # Sayfa işlemleri
    # ==================================================================
    def _selected_pages(self) -> list[int]:
        """Küçük resim panelindeki seçim, yoksa geçerli sayfa."""
        pages = self.thumbnails.selected_pages() if self.dock.isVisible() else []
        return pages or [self.controller.current_page]

    def rotate_current(self, delta: int) -> None:
        if self.controller.is_open:
            self.controller.rotate(self._selected_pages(), delta)

    def rotate_all(self, delta: int) -> None:
        if self.controller.is_open:
            self.controller.rotate(range(self.controller.page_count), delta)

    def insert_blank_page(self) -> None:
        if not self.controller.is_open:
            return
        at = self.controller.current_page + 1
        self.controller.insert_blank(at)
        self.view.go_to_page(min(at, self.controller.page_count - 1))
        self.show_message("Boş sayfa eklendi.")

    def duplicate_current(self) -> None:
        if self.controller.is_open:
            count = self.controller.duplicate_pages(self._selected_pages())
            self.show_message(f"{count} sayfa çoğaltıldı.")

    def delete_current(self) -> None:
        if not self.controller.is_open:
            return
        pages = self._selected_pages()
        if len(pages) >= self.controller.page_count:
            QMessageBox.information(self, "Sayfa sil", "Tüm sayfalar silinemez.")
            return
        answer = QMessageBox.question(
            self, "Sayfa sil", f"{len(pages)} sayfa silinsin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            count = self.controller.delete_pages(pages)
            self.show_message(f"{count} sayfa silindi.")
        except PdfError as exc:
            QMessageBox.warning(self, "Sayfa sil", str(exc))

    def extract_pages_dialog(self) -> None:
        self.extract_pages(self._selected_pages())

    def extract_pages(self, pages: list[int]) -> None:
        """Seçili sayfaları yeni bir PDF'e yazar (küçük resim menüsü de çağırır)."""
        if not self.controller.is_open or not pages:
            return
        base = os.path.splitext(self.controller.path or "belge")[0]
        suggested = f"{base}_secilen.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Seçili sayfaları kaydet", suggested, PDF_FILTER
        )
        if not path:
            return
        try:
            page_ops.extract_pages(self.controller.document, pages, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Dışa aktar", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"{len(pages)} sayfa kaydedildi: {os.path.basename(path)}")
        self._offer_open(path)

    def clear_page_annotations(self) -> None:
        if not self.controller.is_open:
            return
        count = self.controller.clear_annotations(self.controller.current_page)
        self.show_message(
            f"{count} açıklama silindi." if count else "Bu sayfada açıklama yok."
        )

    # ==================================================================
    # Araç istekleri (görüntüleyiciden gelen)
    # ==================================================================
    def _on_request_text(self, page: int, rect) -> None:
        box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        self.view.start_new_inline_text(page, box)

    def _on_request_image(self, page: int, rect) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Görsel seç", self.settings.last_directory, IMAGE_FILTER
        )
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            QMessageBox.warning(self, "Görsel", f"Görsel okunamadı:\n{exc}")
            return
        box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        if self.controller.add_image(page, box, data):
            self.show_message("Görsel eklendi.")
        else:
            QMessageBox.warning(self, "Görsel", "Görsel eklenemedi.")

    def _on_request_signature(self, page: int, rect) -> None:
        last = self.settings.value("tools/last_signature", "")
        dialog = SignatureDialog(self, last or None)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.image_bytes()
        if not data:
            self.show_message("İmza çizilmedi.")
            return
        source = dialog.source_path()
        if source:
            self.settings.set_value("tools/last_signature", source)
        box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        if self.controller.add_image(page, box, data):
            self.show_message("İmza eklendi.")

    # ==================================================================
    # Araçlar menüsü
    # ==================================================================
    def watermark_dialog(self) -> None:
        if not self.controller.is_open:
            return
        dialog = WatermarkDialog(
            self.controller.page_count, self.controller.current_page, self
        )
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            count = self.controller.add_watermark(dialog.options())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Filigran", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(
            f"{count} sayfaya filigran uygulandı." if count else "Filigran uygulanmadı."
        )

    def merge_dialog(self) -> None:
        dialog = MergeDialog(self.controller.path, self)
        if dialog.exec() != QDialog.Accepted:
            return
        sources = dialog.sources()
        try:
            if dialog.save_to_new_file() or not self.controller.is_open:
                out = dialog.output_path()
                if not out:
                    QMessageBox.information(self, "Birleştir", "Çıktı dosyası seçin.")
                    return
                page_ops.merge_documents(sources, out)
                self.show_message(f"Birleştirildi: {os.path.basename(out)}")
                self._offer_open(out)
            else:
                added = self.controller.append_documents(sources)
                self.show_message(f"{added} sayfa belgeye eklendi.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Birleştir", f"İşlem başarısız:\n{exc}")

    def split_dialog(self) -> None:
        if not self.controller.is_open:
            return
        dialog = SplitDialog(self.controller.page_count, self.controller.path, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            written = page_ops.execute_split(
                self.controller.document, dialog.plan(),
                dialog.output_dir(), dialog.file_prefix(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Böl", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"{len(written)} dosya oluşturuldu.")
        self._offer_reveal(dialog.output_dir())

    def export_images_dialog(self) -> None:
        if not self.controller.is_open:
            return
        dialog = ExportImagesDialog(
            self.controller.page_count, self.controller.current_page,
            self.controller.path, self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        options = dialog.options()
        try:
            written = exporter.export_images(self.controller.document, options)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Dışa aktar", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"{len(written)} görsel kaydedildi.")
        self._offer_reveal(options.out_dir)

    def export_text_dialog(self) -> None:
        if not self.controller.is_open:
            return
        base = os.path.splitext(self.controller.path or "belge")[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Metin olarak kaydet", f"{base}.txt", "Metin dosyası (*.txt)"
        )
        if not path:
            return
        try:
            exporter.export_text(self.controller.document, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Dışa aktar", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"Metin kaydedildi: {os.path.basename(path)}")

    def compress_dialog(self) -> None:
        if not self.controller.is_open:
            return
        size = 0
        if self.controller.path and os.path.exists(self.controller.path):
            size = os.path.getsize(self.controller.path)
        dialog = CompressDialog(self.controller.path, size, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            result = exporter.compress(
                self.controller.document, dialog.output_path(), dialog.options()
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Sıkıştır", f"İşlem başarısız:\n{exc}")
            return
        QMessageBox.information(
            self, "Sıkıştırma tamamlandı",
            f"Önce: {result.before / 1024 / 1024:.2f} MB\n"
            f"Sonra: {result.after / 1024 / 1024:.2f} MB\n"
            f"Kazanç: %{result.saved_ratio * 100:.1f}",
        )
        self._offer_open(result.out_path)

    def encrypt_dialog(self) -> None:
        if not self.controller.is_open:
            return
        dialog = SecurityDialog(self.controller.path, self)
        if dialog.exec() != QDialog.Accepted:
            return
        try:
            out = exporter.encrypt(
                self.controller.document, dialog.output_path(), dialog.options()
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Parola", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"Şifreli kopya oluşturuldu: {os.path.basename(out)}")
        self._offer_open(out)

    def decrypt_document(self) -> None:
        if not self.controller.is_open:
            return
        base = os.path.splitext(self.controller.path or "belge")[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Parolasız kopyayı kaydet", f"{base}_parolasiz.pdf", PDF_FILTER
        )
        if not path:
            return
        try:
            exporter.decrypt(self.controller.document, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Parola", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"Parolasız kopya kaydedildi: {os.path.basename(path)}")
        self._offer_open(path)

    def images_to_pdf_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Görselleri seç", self.settings.last_directory, IMAGE_FILTER
        )
        if not paths:
            return
        suggested = os.path.join(os.path.dirname(paths[0]), "gorseller.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "PDF olarak kaydet", suggested, PDF_FILTER)
        if not out:
            return
        try:
            exporter.images_to_pdf(paths, out)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Görselden PDF", f"İşlem başarısız:\n{exc}")
            return
        self.show_message(f"{len(paths)} görselden PDF oluşturuldu.")
        self._offer_open(out)

    def show_properties(self) -> None:
        if not self.controller.is_open:
            return
        doc = self.controller.document
        meta = doc.metadata()
        info: dict[str, str] = {}
        if doc.path:
            info["Dosya"] = doc.path
            if os.path.exists(doc.path):
                info["Boyut"] = f"{os.path.getsize(doc.path) / 1024 / 1024:.2f} MB"
        info["Sayfa sayısı"] = str(doc.page_count)
        try:
            w, h = doc.page_size(self.controller.current_page)
            info["Sayfa boyutu"] = f"{w:.0f} × {h:.0f} pt ({w * 25.4 / 72:.0f} × {h * 25.4 / 72:.0f} mm)"
        except Exception:  # noqa: BLE001
            pass
        # PyMuPDF, parola doğrulandıktan sonra is_encrypted değerini False yapar;
        # belgenin gerçekten korumalı olup olmadığı kullanılan paroladan anlaşılır.
        protected = bool(doc.password) or bool(doc.raw.needs_pass) or doc.raw.is_encrypted
        info["Şifreli"] = "Evet (parola ile açıldı)" if protected else "Hayır"
        for key, value in exporter.describe_permissions(doc).items():
            info[f"İzin · {key}"] = "Evet" if value else "Hayır"

        dialog = PropertiesDialog(meta, info, self)
        if dialog.exec() != QDialog.Accepted:
            return
        updated = dict(meta)
        updated.update(dialog.metadata())
        self.controller.set_metadata(updated)
        self.show_message("Belge bilgileri güncellendi.")

    # ==================================================================
    # Yardım
    # ==================================================================
    def show_shortcuts(self) -> None:
        rows = [
            ("Ctrl+O", "PDF aç"), ("Ctrl+S", "Kaydet"), ("Ctrl+Shift+S", "Farklı kaydet"),
            ("Ctrl+P", "Yazdır"), ("Ctrl+W", "Belgeyi kapat"), ("Ctrl+Q", "Çıkış"),
            ("Ctrl+Z / Ctrl+Y", "Geri al / Yinele"), ("Ctrl+C", "Seçili metni kopyala"),
            ("Ctrl+F", "Ara"), ("F3 / Shift+F3", "Sonraki / önceki sonuç"),
            ("Ctrl++ / Ctrl+-", "Yakınlaştır / uzaklaştır"), ("Ctrl+0", "Gerçek boyut"),
            ("Ctrl+8 / Ctrl+9", "Genişliğe / sayfaya sığdır"),
            ("Ctrl+1 / 2 / 3", "Tek sayfa / sürekli / çift sayfa"),
            ("Ctrl+B", "Kenar çubuğu"), ("Ctrl+T", "Tema değiştir"), ("F11", "Tam ekran"),
            ("Ctrl+G", "Sayfaya git"), ("Ctrl+R / Ctrl+Shift+R", "Sayfayı döndür"),
            ("Ctrl+Delete", "Sayfayı sil"),
            ("Ctrl + Fare tekerleği", "Yakınlaştırma"),
            ("Boşluk + sürükle", "Sayfayı kaydır"), ("Esc", "Çizimi iptal et"),
        ]
        body = "".join(
            f"<tr><td style='padding:3px 16px 3px 0'><b>{k}</b></td>"
            f"<td style='padding:3px 0'>{v}</td></tr>"
            for k, v in rows
        )
        QMessageBox.information(
            self, "Klavye kısayolları", f"<table>{body}</table>"
        )

    # ------------------------------------------------------------------
    # Otomatik güncelleme
    # ------------------------------------------------------------------
    @property
    def updater(self) -> UpdaterService:
        """Güncelleme servisi — ilk kullanımda oluşturulur (lazy)."""
        if self._updater is None:
            self._updater = UpdaterService(
                feed_url=self.settings.update_feed_url,
                current_version=__version__,
                parent=self,
            )
            self._updater.updateAvailable.connect(self._on_update_available)
            self._updater.upToDate.connect(self._on_up_to_date)
            self._updater.checkFailed.connect(self._on_update_check_failed)
        return self._updater

    def set_update_check_on_startup(self, enabled: bool) -> None:
        self.settings.update_check_on_startup = bool(enabled)
        self.show_message(
            "Açılışta güncelleme kontrolü açık." if enabled
            else "Açılışta güncelleme kontrolü kapalı."
        )

    def check_for_updates(self, silent: bool = False) -> None:
        """Yardım menüsünden veya açılışta çağrılır.

        ``silent=True`` açılış kontrolüdür: sonuç olumsuzsa kullanıcı
        rahatsız edilmez, yalnızca durum çubuğuna yazılır.
        """
        if self.updater.busy:
            self.show_message("Güncelleme kontrolü zaten sürüyor…")
            return
        if not silent:
            self.show_message("Güncellemeler kontrol ediliyor…")
        self.updater.check_for_updates(silent=silent)

    def check_for_updates_on_startup(self) -> None:
        """Açılışta, pencere göründükten sonra sessiz kontrol yapar."""
        if self.settings.update_check_on_startup:
            self.check_for_updates(silent=True)

    def _on_update_available(self, info) -> None:
        from .dialogs import UpdateAvailableDialog

        self.settings.update_last_check = datetime.now().isoformat(timespec="seconds")
        # Kullanıcı bu sürümü atlamışsa sessiz kontrolde rahatsız etme.
        if (
            self.updater.silent
            and not info.mandatory
            and info.version == self.settings.update_skipped_version
        ):
            return

        dialog = UpdateAvailableDialog(info, self)
        accepted = dialog.exec() == QDialog.Accepted
        if not accepted:
            if dialog.skip_requested:
                self.settings.update_skipped_version = info.version
                self.show_message(f"{info.version} sürümü atlandı.")
            else:
                self.show_message("Güncelleme ertelendi.")
            return

        self.settings.update_skipped_version = ""
        self._start_update_download(info)

    def _start_update_download(self, info) -> None:
        from .dialogs import UpdateProgressDialog

        progress = UpdateProgressDialog(info, self)
        self._update_progress = progress
        updater = self.updater

        updater.downloadProgress.connect(progress.update_progress)
        progress.cancelled.connect(updater.cancel_download)

        def finished(path: str) -> None:
            cleanup()
            progress.set_installing()
            self._install_update(path)

        def failed(message: str) -> None:
            cleanup()
            progress.close()
            QMessageBox.warning(self, "Güncelleme", message)
            self.show_message(message)

        def cleanup() -> None:
            for signal, slot in (
                (updater.downloadProgress, progress.update_progress),
                (updater.downloadFinished, finished),
                (updater.downloadFailed, failed),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass

        updater.downloadFinished.connect(finished)
        updater.downloadFailed.connect(failed)

        if not updater.download(info):
            cleanup()
            return
        progress.show()

    def _install_update(self, installer_path: str) -> None:
        """Kurulumu başlatır ve uygulamayı güvenli şekilde kapatır."""
        if not self._confirm_discard():
            self.show_message(
                "Güncelleme kurulmadı; kurulum dosyası indirildi: " + installer_path
            )
            if self._update_progress is not None:
                self._update_progress.close()
            return

        if not self.updater.install(installer_path):
            QMessageBox.warning(
                self, "Güncelleme",
                "Kurulum başlatılamadı. Dosyayı elle çalıştırabilirsiniz:\n"
                f"{installer_path}",
            )
            return

        self.show_message("Kurulum başlatıldı, uygulama kapanıyor…")
        # Kurulum süreci ayrı başlatıldı; çıkış bir sonraki olay döngüsünde.
        self._quitting_for_update = True
        QTimer.singleShot(400, QApplication.quit)

    def _on_up_to_date(self, version: str) -> None:
        self.settings.update_last_check = datetime.now().isoformat(timespec="seconds")
        if self.updater.silent:
            self.show_message(f"Uygulama güncel (v{version}).")
            return
        QMessageBox.information(
            self, "Güncelleme",
            f"<h3>Uygulamanız güncel</h3><p>Yüklü sürüm: <b>v{version}</b></p>",
        )

    def _on_update_check_failed(self, message: str) -> None:
        if self.updater.silent:
            self.show_message(f"Güncelleme kontrolü yapılamadı: {message}")
            return
        QMessageBox.warning(
            self, "Güncelleme",
            f"Güncellemeler kontrol edilemedi.\n\n{message}",
        )

    def show_about(self) -> None:
        QMessageBox.about(
            self, f"{__app_name__} Hakkında",
            f"<h3>{__app_name__} v{__version__}</h3>"
            "<p><b>Developed by Ahmet Görkem Yavuz</b></p>"
            "<p>AGY Software © 2026</p>"
            "<p>Modern PDF görüntüleme ve düzenleme uygulaması.</p>"
            "<p>Python · PySide6 · PyMuPDF ile geliştirilmiştir.</p>",
        )

    # ==================================================================
    # Yardımcılar
    # ==================================================================
    def _offer_open(self, path: str) -> None:
        answer = QMessageBox.question(
            self, "Dosya hazır",
            f"{os.path.basename(path)} oluşturuldu. Şimdi açılsın mı?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.open_path(path)

    def _offer_reveal(self, directory: str) -> None:
        if not directory or not os.path.isdir(directory):
            return
        answer = QMessageBox.question(
            self, "Tamamlandı", "Hedef klasör açılsın mı?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            QDesktopServices.openUrl(QUrl.fromLocalFile(directory))

    # ==================================================================
    # Sürükle-bırak & kapanış
    # ==================================================================
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = dropped_files(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.open_dropped_files(paths)

    def open_dropped_files(self, paths: list[str]) -> None:
        """Bırakılan ilk dosyayı açar.

        Açma işi kuyruğa alınır: bırakma olayı sürerken modal diyalog
        (parola sorma, kaydetme onayı) açmak sürükleme işlemini kilitler.
        """
        if not paths:
            return
        QTimer.singleShot(0, lambda p=paths[0]: self.open_path(p))

    def closeEvent(self, event) -> None:  # noqa: N802
        # Güncelleme için kapanıyorsak kaydetme onayı zaten alındı.
        if not self._quitting_for_update and not self._confirm_discard():
            event.ignore()
            return
        if self._updater is not None:
            self._updater.shutdown()
        self.settings.save_window(self.saveGeometry(), self.saveState())
        self.settings.tool_color = self.tools.defaults.stroke.name()
        self.settings.highlight_color = self.tools.defaults.highlight.name()
        self.settings.tool_width = self.tools.defaults.width
        self.settings.zoom_mode = self.view.zoom_mode.value
        self.settings.view_mode = self.view.view_mode.value
        self.settings.sync()
        self.controller.shutdown()
        event.accept()
