"""PDF birleştirme diyaloğu."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ...core import page_ops, xfa
from ...core.pdf_backend import fitz
from .. import icons
from .common import BaseDialog

COL_NAME, COL_PAGES, COL_RANGE = range(3)


class MergeDialog(BaseDialog):
    """Birden çok PDF'i sırayla birleştirir."""

    def __init__(self, current_path: str | None = None, parent=None) -> None:
        super().__init__("PDF'leri birleştir", parent, ok_text="Birleştir")
        self.setMinimumSize(680, 460)
        self._rows: list[dict] = []

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Dosya", "Sayfa", "Aralık"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        # Dosya adı sütunu boşluğu doldursun: sabit genişlikte kalınca tablonun
        # sağında boş bir şerit oluşuyordu.
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_PAGES, QHeaderView.Fixed)
        header.setSectionResizeMode(COL_RANGE, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_PAGES, 70)
        self.table.setColumnWidth(COL_RANGE, 150)

        btn_add = QPushButton(icons.icon("open", size=18), "Dosya ekle…", self)
        btn_remove = QPushButton(icons.icon("close", size=18), "Kaldır", self)
        btn_up = QPushButton("▲ Yukarı", self)
        btn_down = QPushButton("▼ Aşağı", self)
        btn_add.clicked.connect(self.add_files)
        btn_remove.clicked.connect(self._remove_selected)
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down.clicked.connect(lambda: self._move(1))

        tools = QHBoxLayout()
        tools.setSpacing(6)
        tools.addWidget(btn_add)
        tools.addWidget(btn_remove)
        tools.addStretch(1)
        tools.addWidget(btn_up)
        tools.addWidget(btn_down)

        self.append_current = QCheckBox("Sonucu yeni dosyaya kaydet (kapalıysa açık belgeye eklenir)", self)
        self.append_current.setChecked(True)

        self.output = QLineEdit(self)
        self.output.setPlaceholderText("Çıktı dosyası…")
        btn_out = QPushButton("Farklı kaydet…", self)
        btn_out.clicked.connect(self._choose_output)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output, 1)
        out_row.addWidget(btn_out)

        self.content.addWidget(QLabel("Birleştirilecek dosyalar (sıra önemlidir):", self))
        self.content.addWidget(self.table, 1)
        self.content.addLayout(tools)
        self.content.addWidget(self.append_current)
        self.content.addLayout(out_row)
        self.add_hint("Aralık sütununa 1-3, 5 gibi ifadeler yazarak yalnızca istediğiniz sayfaları alabilirsiniz.")

        self.append_current.toggled.connect(self._sync_output)
        self._sync_output()

        if current_path and os.path.exists(current_path):
            self._add_path(current_path)
            self.output.setText(self._suggest_output(current_path))

    # ------------------------------------------------------------------
    def _sync_output(self) -> None:
        enabled = self.append_current.isChecked()
        self.output.setEnabled(enabled)

    @staticmethod
    def _suggest_output(path: str) -> str:
        base, _ = os.path.splitext(path)
        return f"{base}_birlesik.pdf"

    def add_files(self) -> None:
        start = os.path.dirname(self.output.text()) or os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(self, "PDF seç", start, "PDF dosyaları (*.pdf)")
        for path in paths:
            self._add_path(path)
        if paths and not self.output.text():
            self.output.setText(self._suggest_output(paths[0]))

    def _add_path(self, path: str) -> None:
        password = None
        dynamic_form = False
        try:
            doc = fitz.open(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Birleştir", f"{os.path.basename(path)} açılamadı:\n{exc}")
            return
        try:
            if doc.needs_pass:
                pwd, ok = QInputDialog.getText(
                    self, "Parola", f"{os.path.basename(path)} için parola:", QLineEdit.Password
                )
                if not ok or not doc.authenticate(pwd):
                    QMessageBox.warning(self, "Birleştir", "Parola doğrulanamadı, dosya atlandı.")
                    return
                password = pwd
            count = doc.page_count
            dynamic_form = xfa.is_dynamic(doc)
        finally:
            doc.close()

        # Dinamik XFA formu birleştirmede statik sayfalara çizilir; listede de
        # çizim sonrası gerçek sayfa sayısı görünmeli (bkz. page_ops.open_source).
        if dynamic_form:
            try:
                src = page_ops.open_source(path, password)
                try:
                    count = src.page_count
                finally:
                    src.close()
            except Exception:  # noqa: BLE001 - çizilemezse özgün sayfa sayısı kalır
                dynamic_form = False

        row = self.table.rowCount()
        self.table.insertRow(row)
        name_item = QTableWidgetItem(os.path.basename(path))
        name_item.setToolTip(path)
        if dynamic_form:
            name_item.setToolTip(
                f"{path}\n\nEtkileşimli (XFA) form: birleştirmede formun kendisi "
                "çizilir, 'Adobe Reader gerekli' uyarı sayfası eklenmez."
            )
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        pages_item = QTableWidgetItem(str(count))
        pages_item.setFlags(pages_item.flags() & ~Qt.ItemIsEditable)
        pages_item.setTextAlignment(Qt.AlignCenter)
        range_item = QTableWidgetItem("")
        range_item.setToolTip("Boş = tüm sayfalar")
        self.table.setItem(row, COL_NAME, name_item)
        self.table.setItem(row, COL_PAGES, pages_item)
        self.table.setItem(row, COL_RANGE, range_item)
        self._rows.append({"path": path, "password": password, "count": count})

    def _remove_selected(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(index)
            del self._rows[index]

    def _move(self, delta: int) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=delta > 0)
        for row in rows:
            target = row + delta
            if not (0 <= target < self.table.rowCount()):
                continue
            self._rows[row], self._rows[target] = self._rows[target], self._rows[row]
            for col in range(3):
                a = self.table.takeItem(row, col)
                b = self.table.takeItem(target, col)
                self.table.setItem(row, col, b)
                self.table.setItem(target, col, a)
            self.table.selectRow(target)

    # ------------------------------------------------------------------
    def _choose_output(self) -> None:
        start = self.output.text() or os.path.expanduser("~/birlesik.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Birleştirilmiş PDF", start, "PDF (*.pdf)")
        if path:
            self.output.setText(path)

    def sources(self) -> list[tuple[str, str | None, str]]:
        result = []
        for row, data in enumerate(self._rows):
            item = self.table.item(row, COL_RANGE)
            result.append((data["path"], data["password"], item.text() if item else ""))
        return result

    def output_path(self) -> str:
        return self.output.text().strip()

    def save_to_new_file(self) -> bool:
        return self.append_current.isChecked()

    def accept(self) -> None:  # noqa: D102
        if not self._rows:
            QMessageBox.information(self, "Birleştir", "En az bir dosya ekleyin.")
            return
        if self.save_to_new_file() and not self.output_path():
            QMessageBox.information(self, "Birleştir", "Çıktı dosyası seçin.")
            return
        super().accept()
