"""XFA form doldurma diyaloğu.

Dinamik XFA formlarının içeriği sayfa akışında bulunmadığı için normal
görüntüleyicide yalnızca "Adobe Reader gerekli" uyarısı görünür. Bu diyalog
alanları gömülü XML şablonundan okuyup düzenlenebilir bir listede sunar;
girilen değerler ``datasets`` paketine yazıldığı için dosya Adobe'de dolu
olarak açılır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.xfa import XfaField, XfaForm
from .. import theme


def _section_of(field: XfaField) -> str:
    """Alanın bölüm başlığı — veri yolunun kök ve alan adı dışındaki kısmı."""
    parcalar = field.path.split(".")
    if len(parcalar) <= 2:
        return "Genel"
    return " › ".join(parcalar[1:-1])


class XfaFormDialog(QDialog):
    """Alanları bölümlere ayırıp düzenlenebilir gösterir."""

    def __init__(self, form: XfaForm, parent=None) -> None:
        super().__init__(parent)
        self.form = form
        self._editors: dict[str, QWidget] = {}

        self.setWindowTitle("XFA formunu doldur")
        self.setModal(True)
        self.resize(760, 640)

        palette = theme.current()

        baslik = QLabel(
            f"<h3 style='margin:0'>Etkileşimli form alanları</h3>", self
        )
        baslik.setTextFormat(Qt.RichText)

        alanlar = form.editable_fields
        bilgi = QLabel(
            f"{len(alanlar)} doldurulabilir alan bulundu "
            f"(toplam {len(form.fields)}). Girdiğiniz değerler belgenin form "
            f"verisine yazılır; dosya Adobe Reader'da dolu olarak açılır.",
            self,
        )
        bilgi.setWordWrap(True)
        bilgi.setStyleSheet(f"color: {palette.text_muted};")

        # Bölümlere ayrılmış kaydırılabilir gövde
        govde = QWidget(self)
        govde_yerlesim = QVBoxLayout(govde)
        govde_yerlesim.setContentsMargins(0, 0, 8, 0)
        govde_yerlesim.setSpacing(12)

        bolumler: dict[str, list[XfaField]] = {}
        for alan in alanlar:
            bolumler.setdefault(_section_of(alan), []).append(alan)

        for bolum, grup in bolumler.items():
            kutu = QGroupBox(bolum, govde)
            form_yerlesim = QFormLayout(kutu)
            form_yerlesim.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            form_yerlesim.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            for alan in grup:
                duzenleyici = self._make_editor(alan, kutu)
                self._editors[alan.path] = duzenleyici
                if alan.type == "check":
                    form_yerlesim.addRow("", duzenleyici)
                else:
                    etiket = QLabel(alan.label, kutu)
                    etiket.setWordWrap(True)
                    form_yerlesim.addRow(etiket, duzenleyici)
            govde_yerlesim.addWidget(kutu)

        govde_yerlesim.addStretch(1)

        kaydirma = QScrollArea(self)
        kaydirma.setWidget(govde)
        kaydirma.setWidgetResizable(True)
        kaydirma.setFrameShape(QFrame.NoFrame)

        dugmeler = QDialogButtonBox(self)
        self.btn_apply = QPushButton("Formu Doldur", self)
        self.btn_apply.setProperty("accent", "true")
        self.btn_apply.setDefault(True)
        dugmeler.addButton(self.btn_apply, QDialogButtonBox.AcceptRole)
        dugmeler.addButton(QPushButton("Vazgeç", self), QDialogButtonBox.RejectRole)
        dugmeler.accepted.connect(self.accept)
        dugmeler.rejected.connect(self.reject)

        yerlesim = QVBoxLayout(self)
        yerlesim.setContentsMargins(18, 16, 18, 14)
        yerlesim.setSpacing(10)
        yerlesim.addWidget(baslik)
        yerlesim.addWidget(bilgi)
        yerlesim.addWidget(kaydirma, 1)
        yerlesim.addWidget(dugmeler)

    def _make_editor(self, field: XfaField, parent) -> QWidget:
        if field.type == "check":
            kutu = QCheckBox(field.label, parent)
            kutu.setChecked(bool(field.value))
            return kutu
        if field.type == "choice" and field.options:
            acilir = QComboBox(parent)
            acilir.addItem("", "")          # boş = doldurulmadı
            for gorunen, kaydedilen in field.options:
                acilir.addItem(gorunen, kaydedilen)
            if field.value:
                indeks = acilir.findData(field.value)
                if indeks >= 0:
                    acilir.setCurrentIndex(indeks)
            return acilir
        satir = QLineEdit(field.value, parent)
        satir.setPlaceholderText(field.name)
        if field.type == "date":
            satir.setPlaceholderText("YYYY-AA-GG")
        return satir

    def values(self) -> dict[str, str]:
        """Doldurulmuş değerler (boş bırakılanlar dâhil edilmez)."""
        sonuc: dict[str, str] = {}
        for alan in self.form.editable_fields:
            duzenleyici = self._editors.get(alan.path)
            if duzenleyici is None:
                continue
            if isinstance(duzenleyici, QCheckBox):
                if duzenleyici.isChecked():
                    # İşaretli kutunun kaydedilen değeri varsa onu kullan.
                    sonuc[alan.path] = (
                        alan.options[0][1] if alan.options else "1"
                    )
            elif isinstance(duzenleyici, QComboBox):
                deger = duzenleyici.currentData()
                if deger:
                    sonuc[alan.path] = str(deger)
            else:
                metin = duzenleyici.text().strip()
                if metin:
                    sonuc[alan.path] = metin
        return sonuc
