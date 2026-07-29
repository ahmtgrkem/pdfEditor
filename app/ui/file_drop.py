"""Dosya sürükle-bırak desteği için ortak yardımcılar.

Neden ayrı bir modül?
---------------------
``MainWindow`` üzerinde ``setAcceptDrops(True)`` olması tek başına yetmez:
belge alanındaki :class:`~app.ui.page_view.PdfView` bir ``QGraphicsView``,
küçük resim paneli ise bir ``QListWidget``\'tir ve ikisi de sürükleme
olaylarını kendi viewport\'larında **tüketir**. Kullanıcı dosyayı pencerenin
tam ortasına bıraktığında olay ana pencereye hiç ulaşmaz; yalnızca menü
çubuğu gibi boş kenarlara bırakınca çalışır.

Bu yüzden bırakmayı kabul etmesi gereken her alt widget bu karışımı (mixin)
kullanır ve dosyaları :attr:`FileDropMixin.filesDropped` ile yukarı iletir.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Signal

#: Kabul edilen dosya uzantıları
ACCEPTED_SUFFIXES = (".pdf",)


def dropped_files(mime) -> list[str]:
    """Bırakma verisindeki desteklenen yerel dosya yollarını döndürür.

    Desteklenmeyen içerik (iç sürükleme, metin, resim) için boş liste döner;
    çağıran böylece olayı asıl sahibine bırakabilir.

    Yollar işletim sistemi biçimine normalleştirilir: ``toLocalFile``
    Windows'ta da eğik çizgi döndürür ve normalleştirilmezse aynı dosya
    "son kullanılanlar" listesine iki farklı yazımla girer.
    """
    if mime is None or not mime.hasUrls():
        return []
    paths: list[str] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith(ACCEPTED_SUFFIXES):
            paths.append(os.path.normpath(path))
    return paths


class FileDropMixin:
    """Dosya bırakmayı kabul edip :attr:`filesDropped` ile bildirir.

    Dosya içermeyen sürüklemelerde olay ``super()``\'e devredilir; böylece
    küçük resim panelindeki sayfa sıralama sürüklemesi bozulmaz.
    """

    #: Bırakılan desteklenen dosyaların yolları
    filesDropped = Signal(list)

    def _setup_file_drops(self) -> None:
        """Alt sınıfın ``__init__``inde çağrılmalıdır."""
        self.setAcceptDrops(True)
        viewport = getattr(self, "viewport", None)
        if callable(viewport):
            # QAbstractScrollArea'da olayları asıl alan viewport'tur.
            viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        # Bu olay kabul edilmezse imleç "yasak" görünür ve bırakma hiç olmaz.
        if dropped_files(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = dropped_files(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.filesDropped.emit(paths)
            return
        super().dropEvent(event)
