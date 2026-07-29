"""PDF bölme diyaloğu."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QSpinBox,
)

from ...core import page_ops
from .common import BaseDialog, PathPicker


class SplitDialog(BaseDialog):
    """Belgeyi aralıklara, sabit adıma veya tek sayfalara böler."""

    def __init__(self, page_count: int, source_path: str | None, parent=None) -> None:
        super().__init__("PDF'i böl", parent, ok_text="Böl")
        self.setMinimumWidth(560)
        self.page_count = page_count

        self.mode_ranges = QRadioButton("Belirli aralıklara böl", self)
        self.mode_every = QRadioButton("Her N sayfada bir böl", self)
        self.mode_single = QRadioButton("Her sayfayı ayrı dosyaya çıkar", self)
        self.mode_ranges.setChecked(True)

        self.ranges = QLineEdit("1-{0}".format(max(1, page_count // 2)), self)
        self.ranges.setPlaceholderText("örn. 1-3 | 4-6 | 7-")
        self.every = QSpinBox(self)
        self.every.setRange(1, max(1, page_count))
        self.every.setValue(1)
        self.every.setSuffix(" sayfa")

        default_dir = os.path.dirname(source_path) if source_path else os.path.expanduser("~")
        self.out_dir = PathPicker("dir", parent=self)
        self.out_dir.set_path(os.path.join(default_dir, "bolunmus"))

        base = os.path.splitext(os.path.basename(source_path))[0] if source_path else "belge"
        self.prefix = QLineEdit(base, self)

        self.summary = QLabel("", self)
        self.summary.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow(self.mode_ranges)
        form.addRow("Aralıklar", self.ranges)
        form.addRow(self.mode_every)
        form.addRow("Adım", self.every)
        form.addRow(self.mode_single)
        form.addRow("Hedef klasör", self.out_dir)
        form.addRow("Dosya ön eki", self.prefix)

        self.content.addLayout(form)
        self.content.addWidget(self.summary)
        self.add_hint(
            "Aralıkları '|' ile ayırın. Her parça ayrı bir PDF dosyası olarak kaydedilir."
        )

        for w in (self.mode_ranges, self.mode_every, self.mode_single):
            w.toggled.connect(self._sync)
        self.ranges.textChanged.connect(self._sync)
        self.every.valueChanged.connect(self._sync)
        self._sync()

    # ------------------------------------------------------------------
    def _sync(self) -> None:
        self.ranges.setEnabled(self.mode_ranges.isChecked())
        self.every.setEnabled(self.mode_every.isChecked())
        try:
            parts = self.plan()
        except Exception as exc:  # noqa: BLE001
            self.summary.setText(f"⚠ {exc}")
            self.summary.setStyleSheet("color: #ef5350;")
            return
        self.summary.setStyleSheet("")
        preview = ", ".join(
            f"{p.name} ({page_ops.format_ranges(p.indices)})" for p in parts[:4]
        )
        more = "…" if len(parts) > 4 else ""
        self.summary.setText(f"{len(parts)} dosya oluşacak → {preview}{more}")

    def plan(self) -> list[page_ops.SplitPart]:
        if self.mode_ranges.isChecked():
            return page_ops.plan_split_by_ranges(self.page_count, self.ranges.text())
        if self.mode_every.isChecked():
            return page_ops.plan_split_every(self.page_count, self.every.value())
        return page_ops.plan_split_single(self.page_count)

    def output_dir(self) -> str:
        return self.out_dir.path()

    def file_prefix(self) -> str:
        return self.prefix.text().strip() or "belge"

    def accept(self) -> None:  # noqa: D102
        if not self.output_dir():
            QMessageBox.information(self, "Böl", "Hedef klasör seçin.")
            return
        try:
            self.plan()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Böl", str(exc))
            return
        super().accept()
