"""Kalıcı kullanıcı ayarları (QSettings üzerinden)."""
from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QSettings

from .. import __app_name__, __org_name__, __update_feed__

MAX_RECENT = 12


class AppSettings:
    def __init__(self) -> None:
        # DİKKAT: ``QSettings(org, app)`` iki argümanlı kurucusu biçimi her
        # zaman NativeFormat kabul eder ve ``setDefaultFormat`` çağrısını yok
        # sayar. Testler ayarları izole etmek için ``setDefaultFormat`` +
        # ``setPath`` kullandığından, o kurucuyla testler kullanıcının gerçek
        # kayıt defterine yazıyordu (güncelleme adresi test değerinde kalıp
        # kurulu uygulamayı bozdu). Biçimi açıkça vererek izolasyon çalışır;
        # üretimde varsayılan yine NativeFormat olduğu için davranış değişmez.
        self._s = QSettings(
            QSettings.defaultFormat(), QSettings.UserScope, __org_name__, __app_name__
        )

    # -- genel ---------------------------------------------------------
    def value(self, key: str, default: Any = None, type_: type | None = None) -> Any:
        if type_ is not None:
            return self._s.value(key, default, type=type_)
        return self._s.value(key, default)

    def set_value(self, key: str, value: Any) -> None:
        self._s.setValue(key, value)

    def sync(self) -> None:
        self._s.sync()

    # -- tema ----------------------------------------------------------
    @property
    def theme(self) -> str:
        return str(self._s.value("ui/theme", "dark"))

    @theme.setter
    def theme(self, name: str) -> None:
        self._s.setValue("ui/theme", name)

    # -- görünüm -------------------------------------------------------
    @property
    def view_mode(self) -> str:
        return str(self._s.value("view/mode", "continuous"))

    @view_mode.setter
    def view_mode(self, mode: str) -> None:
        self._s.setValue("view/mode", mode)

    @property
    def zoom_mode(self) -> str:
        return str(self._s.value("view/zoom_mode", "fit_width"))

    @zoom_mode.setter
    def zoom_mode(self, mode: str) -> None:
        self._s.setValue("view/zoom_mode", mode)

    @property
    def sidebar_visible(self) -> bool:
        return self._s.value("view/sidebar", True, type=bool)

    @sidebar_visible.setter
    def sidebar_visible(self, visible: bool) -> None:
        self._s.setValue("view/sidebar", visible)

    # -- pencere -------------------------------------------------------
    def save_window(self, geometry: bytes, state: bytes) -> None:
        self._s.setValue("window/geometry", geometry)
        self._s.setValue("window/state", state)

    def restore_window(self) -> tuple[bytes | None, bytes | None]:
        return self._s.value("window/geometry"), self._s.value("window/state")

    # -- son dosyalar --------------------------------------------------
    def recent_files(self) -> list[str]:
        raw = self._s.value("files/recent", [])
        if isinstance(raw, str):
            raw = [raw]
        return [p for p in (raw or []) if p and os.path.exists(p)]

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        items = [p for p in self.recent_files() if os.path.abspath(p) != path]
        items.insert(0, path)
        self._s.setValue("files/recent", items[:MAX_RECENT])

    def clear_recent(self) -> None:
        self._s.setValue("files/recent", [])

    @property
    def last_directory(self) -> str:
        return str(self._s.value("files/last_dir", os.path.expanduser("~")))

    @last_directory.setter
    def last_directory(self, path: str) -> None:
        if path:
            self._s.setValue("files/last_dir", path)

    # -- araç varsayılanları -------------------------------------------
    @property
    def tool_color(self) -> str:
        return str(self._s.value("tools/color", "#e53935"))

    @tool_color.setter
    def tool_color(self, value: str) -> None:
        self._s.setValue("tools/color", value)

    @property
    def tool_width(self) -> float:
        return float(self._s.value("tools/width", 2.0))

    @tool_width.setter
    def tool_width(self, value: float) -> None:
        self._s.setValue("tools/width", float(value))

    @property
    def highlight_color(self) -> str:
        return str(self._s.value("tools/highlight_color", "#ffeb3b"))

    @highlight_color.setter
    def highlight_color(self, value: str) -> None:
        self._s.setValue("tools/highlight_color", value)

    # -- otomatik güncelleme -------------------------------------------
    @property
    def update_check_on_startup(self) -> bool:
        """Uygulama açılışında arka planda sessiz sürüm kontrolü yapılsın mı?"""
        return self._s.value("update/check_on_startup", True, type=bool)

    @update_check_on_startup.setter
    def update_check_on_startup(self, enabled: bool) -> None:
        self._s.setValue("update/check_on_startup", bool(enabled))

    @property
    def update_feed_url(self) -> str:
        """``version.json`` adresi; boşsa uygulama varsayılanı kullanılır."""
        return str(self._s.value("update/feed_url", __update_feed__))

    @update_feed_url.setter
    def update_feed_url(self, url: str) -> None:
        self._s.setValue("update/feed_url", url or __update_feed__)

    @property
    def update_skipped_version(self) -> str:
        """Kullanıcının "bu sürümü atla" dediği sürüm."""
        return str(self._s.value("update/skipped_version", "") or "")

    @update_skipped_version.setter
    def update_skipped_version(self, version: str) -> None:
        self._s.setValue("update/skipped_version", version or "")

    @property
    def update_last_check(self) -> str:
        """Son başarılı kontrolün ISO 8601 zaman damgası."""
        return str(self._s.value("update/last_check", "") or "")

    @update_last_check.setter
    def update_last_check(self, stamp: str) -> None:
        self._s.setValue("update/last_check", stamp or "")
