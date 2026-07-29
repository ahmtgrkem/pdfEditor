"""Parola koruma ve belge bilgileri diyalogları."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...core.exporter import SecurityOptions
from .common import BaseDialog, PathPicker


class PasswordPrompt(BaseDialog):
    """Şifreli belge açılırken parola sorar."""

    def __init__(self, file_name: str, retry: bool = False, parent=None) -> None:
        super().__init__("Parola gerekli", parent, ok_text="Aç")
        self.setMinimumWidth(400)
        self.field = QLineEdit(self)
        self.field.setEchoMode(QLineEdit.Password)
        self.field.returnPressed.connect(self.accept)

        message = QLabel(f"<b>{file_name}</b> parola korumalı.", self)
        message.setWordWrap(True)
        self.content.addWidget(message)
        self.content.addWidget(self.field)
        if retry:
            warn = QLabel("Parola hatalı, tekrar deneyin.", self)
            warn.setStyleSheet("color: #ef5350;")
            self.content.addWidget(warn)
        self.field.setFocus()

    def password(self) -> str:
        return self.field.text()


class SecurityDialog(BaseDialog):
    """Parola koyma ve izin ayarları."""

    def __init__(self, source_path: str | None, parent=None) -> None:
        super().__init__("Parola koy", parent, ok_text="Şifrele ve kaydet")
        self.setMinimumWidth(520)

        self.user_pw = QLineEdit(self)
        self.user_pw.setEchoMode(QLineEdit.Password)
        self.user_pw.setPlaceholderText("Belgeyi açmak için gereken parola")

        self.user_pw2 = QLineEdit(self)
        self.user_pw2.setEchoMode(QLineEdit.Password)
        self.user_pw2.setPlaceholderText("Parolayı tekrar girin")

        self.owner_pw = QLineEdit(self)
        self.owner_pw.setEchoMode(QLineEdit.Password)
        self.owner_pw.setPlaceholderText("İzinleri değiştirmek için (isteğe bağlı)")

        self.allow_print = QCheckBox("Yazdırmaya izin ver", self)
        self.allow_print.setChecked(True)
        self.allow_copy = QCheckBox("Metin kopyalamaya izin ver", self)
        self.allow_copy.setChecked(True)
        self.allow_annotate = QCheckBox("Açıklama eklemeye izin ver", self)
        self.allow_annotate.setChecked(True)
        self.allow_modify = QCheckBox("Belgeyi değiştirmeye izin ver", self)

        default = source_path or os.path.expanduser("~/belge.pdf")
        base, ext = os.path.splitext(default)
        self.output = PathPicker("save", "PDF (*.pdf)", parent=self)
        self.output.set_path(f"{base}_korumali{ext or '.pdf'}")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        form.addRow("Açma parolası", self.user_pw)
        form.addRow("Parola (tekrar)", self.user_pw2)
        form.addRow("Sahip parolası", self.owner_pw)
        form.addRow("", self.allow_print)
        form.addRow("", self.allow_copy)
        form.addRow("", self.allow_annotate)
        form.addRow("", self.allow_modify)
        form.addRow("Çıktı dosyası", self.output)

        self.content.addLayout(form)
        self.add_hint(
            "AES-256 ile şifrelenir. Sahip parolası boş bırakılırsa açma parolası "
            "sahip parolası olarak da kullanılır ve izin kısıtları uygulanmaz."
        )
        self.user_pw.setFocus()

    def options(self) -> SecurityOptions:
        return SecurityOptions(
            user_password=self.user_pw.text(),
            owner_password=self.owner_pw.text(),
            allow_print=self.allow_print.isChecked(),
            allow_copy=self.allow_copy.isChecked(),
            allow_modify=self.allow_modify.isChecked(),
            allow_annotate=self.allow_annotate.isChecked(),
        )

    def output_path(self) -> str:
        return self.output.path()

    def accept(self) -> None:  # noqa: D102
        if not self.user_pw.text() and not self.owner_pw.text():
            QMessageBox.information(self, "Parola", "En az bir parola girin.")
            return
        if self.user_pw.text() != self.user_pw2.text():
            QMessageBox.warning(self, "Parola", "Parolalar eşleşmiyor.")
            return
        if not self.output_path():
            QMessageBox.information(self, "Parola", "Çıktı dosyası seçin.")
            return
        super().accept()


class PropertiesDialog(BaseDialog):
    """Belge bilgileri (metadata) görüntüleme ve düzenleme."""

    FIELDS = [
        ("title", "Başlık"),
        ("author", "Yazar"),
        ("subject", "Konu"),
        ("keywords", "Anahtar kelimeler"),
        ("creator", "Oluşturan"),
        ("producer", "Üretici"),
    ]

    def __init__(self, meta: dict, info: dict, parent=None) -> None:
        super().__init__("Belge bilgileri", parent, ok_text="Kaydet")
        self.setMinimumWidth(540)
        self._fields: dict[str, QLineEdit] = {}

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setSpacing(9)
        for key, label in self.FIELDS:
            edit = QLineEdit(str(meta.get(key) or ""), self)
            if key == "producer":
                edit.setReadOnly(True)
            self._fields[key] = edit
            form.addRow(label, edit)

        summary = QPlainTextEdit(self)
        summary.setReadOnly(True)
        summary.setMaximumHeight(190)
        summary.setPlainText("\n".join(f"{k}: {v}" for k, v in info.items()))

        self.content.addLayout(form)
        self.content.addWidget(QLabel("Dosya ve güvenlik bilgileri", self))
        self.content.addWidget(summary)

    def metadata(self) -> dict:
        return {key: edit.text() for key, edit in self._fields.items() if not edit.isReadOnly()}
