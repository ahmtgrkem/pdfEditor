"""Uygulama giriş noktası."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __app_name__, __org_name__, __version__
from .services.settings import AppSettings
from .ui import theme
from .ui.main_window import MainWindow


def resource_path(*parts: str) -> str:
    """PyInstaller paketinde de çalışan kaynak yolu üretir."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_icon() -> QIcon:
    for name in ("app_icon.ico", "app.ico", "app.png"):
        path = resource_path("assets", name)
        if os.path.exists(path):
            return QIcon(path)
    from .ui import icons

    return icons.icon("new", size=64)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)

    # Windows Görev Çubuğu Simgesi (AppUserModelID)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AGY.AGYPDFEditor.1.0")
        except Exception:  # noqa: BLE001
            pass

    QApplication.setApplicationName(__app_name__)
    QApplication.setOrganizationName(__org_name__)
    QApplication.setApplicationVersion(__version__)

    app = QApplication(argv)
    app.setWindowIcon(app_icon())

    settings = AppSettings()
    theme.apply(app, settings.theme)

    window = MainWindow(settings)
    window.show()

    # Komut satırından gelen PDF'i aç
    files = [a for a in argv[1:] if a.lower().endswith(".pdf") and os.path.exists(a)]
    if files:
        QTimer.singleShot(60, lambda: window.open_path(files[0]))

    # Açılışta sessiz güncelleme kontrolü (ayarlardan kapatılabilir).
    # Pencere çizildikten sonra çalışır ki başlangıç gecikmesi hissedilmesin.
    if "--no-update-check" not in argv:
        QTimer.singleShot(2500, window.check_for_updates_on_startup)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
