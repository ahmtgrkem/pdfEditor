"""Otomatik güncelleme servisi.

Akış
----
1. :class:`UpdaterService.check_for_updates` uzaktaki ``version.json``ı
   arka plan iş parçacığında indirir (GUI donmaz).
2. Sürüm, çalışan sürümden yeniyse ``updateAvailable`` yayınlanır.
3. :meth:`UpdaterService.download` kurulum dosyasını ``%TEMP%`` altına
   parça parça indirir; ilerleme ve hız ``downloadProgress`` ile bildirilir.
4. :meth:`UpdaterService.install` Inno Setup kurulumunu sessiz parametrelerle
   ayrı bir süreç olarak başlatır ve uygulamadan çıkılmasını ister.

``version.json`` şeması::

    {
      "version": "1.2.0",                       (zorunlu)
      "download_url": "https://.../Setup.exe",  (zorunlu)
      "mandatory": false,                       (varsayılan: false)
      "release_notes": "- Yenilik\n- Düzeltme",
      "release_date": "2026-07-28",
      "size": 48123904,                         (byte, bilgi amaçlı)
      "sha256": "ab12…"                         (verilirse doğrulanır)
    }

Güvenlik: indirilen dosya çalıştırılacağı için varsayılan olarak yalnızca
``https`` adreslerine izin verilir ve ``sha256`` verilmişse doğrulanır.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from .. import __app_name__, __version__

#: Ağ isteklerinin zaman aşımı (saniye)
NETWORK_TIMEOUT = 15
#: İndirme parça boyutu
CHUNK_SIZE = 64 * 1024
#: İlerleme sinyalinin en sık yayınlanma aralığı (saniye)
PROGRESS_INTERVAL = 0.15
#: Inno Setup sessiz kurulum parametreleri.
#:
#: ``/RESTARTAPPLICATIONS`` **kullanılmaz**: Restart Manager yalnızca
#: ``RegisterApplicationRestart`` ile kaydolmuş uygulamaları geri açar, Qt
#: uygulaması bunu yapmadığı için kurulum sonrası uygulama kapalı kalıyordu
#: (kurulum günlüğü "Attempting to restart applications" yazıp sessizce
#: başarısız oluyor). Bunun yerine kurulum betiğindeki ``[Run]`` girdisi
#: ``/RESTARTAPP`` görünce uygulamayı kendisi başlatır.
SILENT_INSTALL_ARGS = ("/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART", "/RESTARTAPP")
#: İndirilen kurulumların saklandığı geçici alt dizin
DOWNLOAD_DIRNAME = "AGYPDFEditorUpdate"

USER_AGENT = f"{__app_name__.replace(' ', '')}/{__version__}"


# ======================================================================
# Sürüm karşılaştırma
# ======================================================================
_VERSION_RE = re.compile(r"\d+")


def parse_version(value: str) -> tuple[int, ...]:
    """``"1.2.3"`` -> ``(1, 2, 3)``. Sayı olmayan ekler yok sayılır."""
    if not value:
        return (0,)
    parts = tuple(int(p) for p in _VERSION_RE.findall(str(value))[:4])
    return parts or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    """``candidate`` sürümü ``current``tan yeni mi?

    Farklı uzunluktaki sürümler sıfırla tamamlanır: ``1.2`` == ``1.2.0``.
    """
    a, b = parse_version(candidate), parse_version(current)
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


# ======================================================================
# Veri modeli
# ======================================================================
@dataclass
class UpdateInfo:
    """Uzaktaki ``version.json`` içeriğinin çözümlenmiş hâli."""

    version: str
    download_url: str
    mandatory: bool = False
    release_notes: str = ""
    release_date: str = ""
    size: int = 0
    sha256: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpdateInfo:
        if not isinstance(data, dict):
            raise ValueError("version.json bir JSON nesnesi olmalı.")
        version = str(data.get("version", "")).strip()
        url = str(data.get("download_url", "")).strip()
        if not version:
            raise ValueError("version.json içinde 'version' alanı yok.")
        if not url:
            raise ValueError("version.json içinde 'download_url' alanı yok.")
        return cls(
            version=version,
            download_url=url,
            mandatory=bool(data.get("mandatory", False)),
            release_notes=str(data.get("release_notes", "") or ""),
            release_date=str(data.get("release_date", "") or ""),
            size=int(data.get("size", 0) or 0),
            sha256=str(data.get("sha256", "") or "").lower(),
            raw=dict(data),
        )

    @property
    def is_newer_than_current(self) -> bool:
        return is_newer(self.version)

    def filename(self) -> str:
        base = os.path.basename(self.download_url.split("?", 1)[0]) or "setup.exe"
        if not base.lower().endswith(".exe"):
            base += ".exe"
        return base


# ======================================================================
# Ağ yardımcıları (test edilebilir olması için sınıf dışında)
# ======================================================================
def open_url(url: str, timeout: int = NETWORK_TIMEOUT):
    """``urlopen`` sarmalayıcısı — testlerde tek noktadan taklit edilir."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310


def fetch_manifest(url: str, timeout: int = NETWORK_TIMEOUT) -> UpdateInfo:
    """``version.json``ı indirir ve :class:`UpdateInfo` üretir."""
    with open_url(url, timeout) as response:
        payload = response.read()
    if isinstance(payload, bytes):
        # utf-8-sig: Windows araçlarının (PowerShell ``Out-File -Encoding utf8``)
        # ürettiği BOM'u yutar. Düz utf-8 ile çözülürse BOM metnin başında
        # U+FEFF olarak kalır ve ``json.loads`` ilk karakterde hata verir.
        payload = payload.decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Sürüm dosyası okunamadı: {exc}") from exc
    return UpdateInfo.from_dict(data)


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num_bytes) < 1024.0 or unit == "GB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} GB"


def human_speed(bytes_per_second: float) -> str:
    if bytes_per_second <= 0:
        return "—"
    return f"{human_size(bytes_per_second)}/s"


# ======================================================================
# Arka plan iş parçacıkları
# ======================================================================
class _CheckWorker(QThread):
    """``version.json``ı arka planda indirir."""

    succeeded = Signal(object)   # UpdateInfo
    failed = Signal(str)

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:  # pragma: no cover - iş parçacığı gövdesi
        try:
            info = fetch_manifest(self.url)
        except urllib.error.URLError as exc:
            self.failed.emit(f"Sunucuya ulaşılamadı: {exc.reason}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(info)


class _DownloadWorker(QThread):
    """Kurulum dosyasını parça parça indirir; iptal edilebilir."""

    progress = Signal(int, int, float)   # alınan, toplam, bayt/saniye
    succeeded = Signal(str)              # indirilen dosyanın yolu
    failed = Signal(str)

    def __init__(self, info: UpdateInfo, target_path: str,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.target_path = target_path
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:  # pragma: no cover - iş parçacığı gövdesi
        try:
            path = download_to(
                self.info,
                self.target_path,
                on_progress=self.progress.emit,
                is_cancelled=lambda: self._cancelled,
            )
        except _Cancelled:
            self.failed.emit("İndirme iptal edildi.")
        except urllib.error.URLError as exc:
            self.failed.emit(f"İndirme başarısız: {exc.reason}")
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(path)


class _Cancelled(Exception):
    """İndirme kullanıcı tarafından iptal edildi."""


def download_to(
    info: UpdateInfo,
    target_path: str,
    on_progress: Callable[[int, int, float], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout: int = NETWORK_TIMEOUT,
) -> str:
    """Kurulum dosyasını indirir, doğrular ve nihai yola taşır.

    Yarım kalan indirmenin kurulum sanılmaması için önce ``.part`` uzantısıyla
    yazılır, yalnızca doğrulama başarılıysa asıl ada taşınır.
    """
    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
    temp_path = target_path + ".part"
    digest = hashlib.sha256()
    received = 0
    started = last_emit = time.monotonic()

    with open_url(info.download_url, timeout) as response:
        total = int(response.headers.get("Content-Length") or info.size or 0)
        with open(temp_path, "wb") as handle:
            while True:
                if is_cancelled is not None and is_cancelled():
                    raise _Cancelled
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                now = time.monotonic()
                if on_progress is not None and (
                    now - last_emit >= PROGRESS_INTERVAL or received == total
                ):
                    elapsed = max(now - started, 1e-6)
                    on_progress(received, total, received / elapsed)
                    last_emit = now

    if info.sha256 and digest.hexdigest() != info.sha256:
        os.remove(temp_path)
        raise ValueError("İndirilen dosyanın sha256 özeti eşleşmedi; kurulum iptal edildi.")

    if on_progress is not None:
        elapsed = max(time.monotonic() - started, 1e-6)
        on_progress(received, total or received, received / elapsed)

    os.replace(temp_path, target_path)
    return target_path


# ======================================================================
# Kurulum
# ======================================================================
def download_directory() -> str:
    """İndirilen kurulumların saklandığı ``%TEMP%`` alt dizini."""
    return os.path.join(tempfile.gettempdir(), DOWNLOAD_DIRNAME)


def launch_installer(installer_path: str, silent: bool = True) -> subprocess.Popen:
    """Inno Setup kurulumunu ayrı (detached) bir süreç olarak başlatır.

    Uygulama hemen ardından kapanacağı için süreç, ebeveyninden bağımsız
    başlatılır; aksi hâlde uygulama kapanınca kurulum da sonlanır.
    """
    if not os.path.isfile(installer_path):
        raise FileNotFoundError(installer_path)

    command = [installer_path]
    if silent:
        command.extend(SILENT_INSTALL_ARGS)
        command.append(f'/LOG={os.path.join(download_directory(), "install.log")}')

    kwargs: dict[str, Any] = {"close_fds": True, "cwd": download_directory()}
    if sys.platform == "win32":  # pragma: no cover - platforma bağlı
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # noqa: S603


# ======================================================================
# Servis
# ======================================================================
class UpdaterService(QObject):
    """Sürüm kontrolü, indirme ve kurulum akışını yöneten cephe (facade)."""

    checkStarted = Signal()
    #: Yeni sürüm bulundu
    updateAvailable = Signal(object)     # UpdateInfo
    #: Kontrol başarılı ama güncel sürüm kullanılıyor
    upToDate = Signal(str)               # mevcut sürüm
    checkFailed = Signal(str)

    downloadStarted = Signal(object)     # UpdateInfo
    downloadProgress = Signal(int, int, float)
    downloadFinished = Signal(str)       # dosya yolu
    downloadFailed = Signal(str)

    #: Kurulum başlatıldı; uygulamanın kapanması gerekiyor
    installStarted = Signal(str)
    installFailed = Signal(str)

    def __init__(
        self,
        feed_url: str,
        current_version: str = __version__,
        parent: QObject | None = None,
        require_https: bool = True,
        require_checksum: bool = True,
    ) -> None:
        super().__init__(parent)
        self.feed_url = feed_url
        self.current_version = current_version
        self.require_https = require_https
        self.require_checksum = require_checksum
        self._check_worker: _CheckWorker | None = None
        self._download_worker: _DownloadWorker | None = None
        self._silent = False
        # Sinyal yayınlandıktan sonra iş parçacığı hâlâ sonlanma aşamasındadır.
        # Çalışan bir QThread yok edilirse Qt süreci sonlandırır; bu yüzden
        # gerçekten bitene (``finished``) kadar burada tutulur.
        self._workers: list[QThread] = []

    def _track(self, worker: QThread) -> None:
        self._workers.append(worker)
        # DİKKAT: lambda'ya bağlanmaz. Alıcısı QObject olmayan bağlantılar
        # *doğrudan* yayınlayan iş parçacığında çalışır; iş parçacığı kendi
        # içinden silinmeye çalışılır ve Qt süreci sonlandırır. Bağlı metot
        # kullanılınca çağrı ana iş parçacığına kuyruklanır.
        worker.finished.connect(self._on_worker_finished)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker is None:
            return
        worker.wait()          # iş parçacığı tamamen sonlanmadan silinmemeli
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    # -- durum ---------------------------------------------------------
    @property
    def busy(self) -> bool:
        return self.checking or self.downloading

    @property
    def checking(self) -> bool:
        return self._check_worker is not None and self._check_worker.isRunning()

    @property
    def downloading(self) -> bool:
        return self._download_worker is not None and self._download_worker.isRunning()

    @property
    def silent(self) -> bool:
        """Açılıştaki sessiz kontrol mü? (hata mesajı gösterilmez)"""
        return self._silent

    # -- 1) sürüm kontrolü ---------------------------------------------
    def check_for_updates(self, silent: bool = False) -> bool:
        """Arka planda sürüm kontrolü başlatır.

        ``silent`` açılış kontrolü içindir: sonuç olumsuzsa kullanıcı
        rahatsız edilmez. Zaten çalışan bir kontrol varsa ``False`` döner.
        """
        if self.checking:
            return False
        if not self.feed_url:
            self.checkFailed.emit("Güncelleme adresi tanımlı değil.")
            return False

        self._silent = silent
        self.checkStarted.emit()
        worker = _CheckWorker(self.feed_url, self)
        worker.succeeded.connect(self._on_manifest)
        worker.failed.connect(self._on_check_failed)
        self._check_worker = worker
        self._track(worker)
        worker.start()
        return True

    def _on_manifest(self, info: UpdateInfo) -> None:
        self._check_worker = None
        try:
            self._validate_manifest(info)
        except ValueError as exc:
            self.checkFailed.emit(str(exc))
            return
        if is_newer(info.version, self.current_version):
            self.updateAvailable.emit(info)
        else:
            self.upToDate.emit(self.current_version)

    def _on_check_failed(self, message: str) -> None:
        self._check_worker = None
        self.checkFailed.emit(message)

    def _validate_url(self, url: str) -> None:
        if self.require_https and not url.lower().startswith("https://"):
            raise ValueError(
                "Güvenlik nedeniyle kurulum dosyası yalnızca https adresinden indirilir."
            )

    def _validate_manifest(self, info: UpdateInfo) -> None:
        """Manifesti kabul etmeden önce güvenlik alanlarını doğrular.

        ``sha256`` boşsa :func:`download_to` bütünlük kontrolünü tamamen
        atlar ve doğrulanmamış bir kurulum dosyası çalıştırılır. Bayat
        önbellek ya da yarım yayın böyle bir manifest üretebildiği için
        eksik özet, sessizce geçilmek yerine hata sayılır.
        """
        self._validate_url(info.download_url)
        if self.require_checksum and len(info.sha256) != 64:
            raise ValueError(
                "Sürüm dosyasında geçerli bir sha256 özeti yok; indirilen kurulum "
                "doğrulanamayacağı için güncelleme iptal edildi."
            )

    # -- 2) indirme ----------------------------------------------------
    def download(self, info: UpdateInfo) -> bool:
        """Kurulum dosyasını ``%TEMP%`` altına indirmeye başlar."""
        if self.downloading:
            return False
        try:
            self._validate_manifest(info)
        except ValueError as exc:
            self.downloadFailed.emit(str(exc))
            return False

        target = os.path.join(download_directory(), info.filename())
        worker = _DownloadWorker(info, target, self)
        worker.progress.connect(self.downloadProgress)
        worker.succeeded.connect(self._on_download_finished)
        worker.failed.connect(self._on_download_failed)
        self._download_worker = worker
        self._track(worker)
        self.downloadStarted.emit(info)
        worker.start()
        return True

    def cancel_download(self) -> None:
        if self._download_worker is not None:
            self._download_worker.cancel()

    def _on_download_finished(self, path: str) -> None:
        self._download_worker = None
        self.downloadFinished.emit(path)

    def _on_download_failed(self, message: str) -> None:
        self._download_worker = None
        self.downloadFailed.emit(message)

    # -- 3) kurulum ----------------------------------------------------
    def install(self, installer_path: str, silent: bool = True) -> bool:
        """Kurulumu başlatır. Başarılıysa uygulama kapatılmalıdır."""
        try:
            launch_installer(installer_path, silent=silent)
        except Exception as exc:  # noqa: BLE001
            self.installFailed.emit(f"Kurulum başlatılamadı: {exc}")
            return False
        self.installStarted.emit(installer_path)
        return True

    # -- temizlik ------------------------------------------------------
    def shutdown(self, wait_ms: int = 5000) -> None:
        """Açık iş parçacıklarını nazikçe sonlandırır.

        Uygulama kapanırken **mutlaka** çağrılmalıdır: çalışan bir ``QThread``
        yok edilirse Qt süreci ``abort`` ile sonlandırır.
        """
        if self._download_worker is not None:
            try:
                self._download_worker.cancel()
            except RuntimeError:      # C++ tarafı zaten silinmiş
                pass
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(wait_ms)
            except RuntimeError:
                pass
            if worker in self._workers:
                self._workers.remove(worker)
        self._check_worker = None
        self._download_worker = None

    @staticmethod
    def cleanup_downloads(keep: str | None = None) -> int:
        """Eski kurulum dosyalarını siler; silinen dosya sayısını döndürür."""
        directory = download_directory()
        if not os.path.isdir(directory):
            return 0
        removed = 0
        keep_name = os.path.basename(keep) if keep else None
        for name in os.listdir(directory):
            if name == keep_name:
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
        return removed
