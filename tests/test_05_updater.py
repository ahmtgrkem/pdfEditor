"""5. Otomatik güncelleme servisi: sürüm karşılaştırma, indirme, kurulum, UI."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import urllib.error

import pytest
from PySide6.QtWidgets import QDialog

from app import __version__
from app.services import updater as up
from app.services.updater import (
    UpdateInfo,
    UpdaterService,
    download_to,
    fetch_manifest,
    human_size,
    human_speed,
    is_newer,
    launch_installer,
    parse_version,
)
from conftest import pump

MANIFEST = {
    "version": "2.5.0",
    "download_url": "https://example.com/AGY_PDF_Editor_v2.5_Setup.exe",
    "mandatory": False,
    "release_notes": "- Canlı metin düzenleyici\n- Hata düzeltmeleri",
    "release_date": "2026-08-01",
    "size": 1024,
    # Gerçek yayınlarda bu alan her zaman doludur; servis eksik özeti
    # reddettiği için fikstür de gerçeğe uygun olmalı.
    "sha256": "ab" * 32,
}


def manifest_icin(veri: bytes, **degisiklikler) -> dict:
    """``veri`` indirilecekmiş gibi doğru sha256 taşıyan manifest üretir.

    Servis sha256'sız manifesti reddettiği için indirme testlerinin de
    gerçek yayınlardaki gibi tutarlı bir özet taşıması gerekir.
    """
    return {**MANIFEST, "sha256": hashlib.sha256(veri).hexdigest(), **degisiklikler}


class FakeResponse(io.BytesIO):
    """``urlopen`` yerine geçen, context manager destekli sahte yanıt."""

    def __init__(self, payload: bytes, headers: dict | None = None) -> None:
        super().__init__(payload)
        self.headers = headers or {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        self.close()
        return False


@pytest.fixture
def fake_network(monkeypatch):
    """``open_url``u taklit eder; istenen URL'ler kayda alınır."""
    state: dict = {"urls": [], "payload": json.dumps(MANIFEST).encode(), "headers": None,
                   "error": None}

    def fake_open(url, timeout=None):
        state["urls"].append(url)
        if state["error"] is not None:
            raise state["error"]
        return FakeResponse(state["payload"], state["headers"])

    monkeypatch.setattr(up, "open_url", fake_open)
    return state


@pytest.fixture
def temp_downloads(monkeypatch, tmp_path):
    """İndirmeleri gerçek %TEMP% yerine test dizinine yönlendirir."""
    target = tmp_path / "updates"
    monkeypatch.setattr(up, "download_directory", lambda: str(target))
    return target


@pytest.fixture
def make_service(qapp):
    """Servis üretir ve test sonunda iş parçacıklarını kapatır.

    Çalışan bir ``QThread``ı yok etmek Qt'de süreci sonlandırdığı için
    her servis mutlaka ``shutdown`` edilmelidir.
    """
    created: list[UpdaterService] = []

    def _factory(*args, **kwargs) -> UpdaterService:
        service = UpdaterService(*args, **kwargs)
        created.append(service)
        return service

    yield _factory

    for service in created:
        service.shutdown()
    qapp.processEvents()


# ======================================================================
# 5.1 Sürüm karşılaştırma
# ======================================================================
class TestSurumKarsilastirma:
    @pytest.mark.parametrize("value,beklenen", [
        ("1.0.0", (1, 0, 0)),
        ("2.15.3", (2, 15, 3)),
        ("1.2", (1, 2)),
        ("v3.0.1", (3, 0, 1)),
        ("1.0.0-beta2", (1, 0, 0, 2)),
        ("", (0,)),
    ])
    def test_surum_ayristirma(self, value, beklenen):
        assert parse_version(value) == beklenen

    @pytest.mark.parametrize("yeni,mevcut,sonuc", [
        ("1.0.1", "1.0.0", True),
        ("1.1.0", "1.0.9", True),
        ("2.0.0", "1.9.9", True),
        ("1.0.0", "1.0.0", False),
        ("0.9.9", "1.0.0", False),
        ("1.0", "1.0.0", False),      # eksik hane sıfır sayılır
        ("1.0.1", "1.0", True),
        ("10.0.0", "9.0.0", True),    # sayısal karşılaştırma, metin değil
    ])
    def test_yeni_surum_tespiti(self, yeni, mevcut, sonuc):
        assert is_newer(yeni, mevcut) is sonuc

    def test_varsayilan_mevcut_surum_uygulamanindir(self):
        assert is_newer(__version__, __version__) is False
        assert is_newer("999.0.0") is True


# ======================================================================
# 5.2 version.json çözümleme
# ======================================================================
class TestManifestCozumleme:
    def test_gecerli_manifest_okunur(self, fake_network):
        info = fetch_manifest("https://example.com/version.json")
        assert info.version == "2.5.0"
        assert info.download_url.endswith(".exe")
        assert info.mandatory is False
        assert "Canlı metin" in info.release_notes
        assert info.is_newer_than_current is True
        assert fake_network["urls"] == ["https://example.com/version.json"]

    def test_zorunlu_bayragi_okunur(self, fake_network):
        fake_network["payload"] = json.dumps({**MANIFEST, "mandatory": True}).encode()
        assert fetch_manifest("https://x/version.json").mandatory is True

    @pytest.mark.parametrize("eksik", ["version", "download_url"])
    def test_zorunlu_alan_eksikse_hata(self, fake_network, eksik):
        bozuk = {k: v for k, v in MANIFEST.items() if k != eksik}
        fake_network["payload"] = json.dumps(bozuk).encode()
        with pytest.raises(ValueError, match=eksik):
            fetch_manifest("https://x/version.json")

    def test_bom_ile_baslayan_manifest_okunur(self, fake_network):
        # PowerShell'in "Out-File -Encoding utf8" çıktısı BOM'la başlar; düz
        # utf-8 çözümlemede BOM metinde kalır ve json.loads ilk karakterde patlar.
        fake_network["payload"] = b"\xef\xbb\xbf" + json.dumps(MANIFEST).encode()
        assert fetch_manifest("https://x/version.json").version == "2.5.0"

    def test_bozuk_json_anlamli_hata_verir(self, fake_network):
        fake_network["payload"] = b"{ bu json degil"
        with pytest.raises(ValueError, match="okunamadı"):
            fetch_manifest("https://x/version.json")

    def test_dosya_adi_urlden_turetilir(self):
        info = UpdateInfo.from_dict(MANIFEST)
        assert info.filename() == "AGY_PDF_Editor_v2.5_Setup.exe"
        sorgulu = UpdateInfo.from_dict(
            {**MANIFEST, "download_url": "https://x/setup.exe?token=abc"}
        )
        assert sorgulu.filename() == "setup.exe"


# ======================================================================
# 5.3 İndirme
# ======================================================================
class TestIndirme:
    def test_ayni_dosya_varsa_yeniden_indirilmez(self, qapp, fake_network,
                                                 temp_downloads, make_service):
        """Kurulum yarıda kaldıysa 128 MB'ı tekrar indirmek gerekmez."""
        veri = b"MZ" + b"onceden-indirildi"
        bilgi = UpdateInfo.from_dict(manifest_icin(veri))
        temp_downloads.mkdir(parents=True, exist_ok=True)
        hedef = temp_downloads / bilgi.filename()
        hedef.write_bytes(veri)

        servis = make_service("https://example.com/version.json")
        bitenler: list = []
        servis.downloadFinished.connect(bitenler.append)

        assert servis.download(bilgi) is True
        pump(qapp)
        assert bitenler == [str(hedef)], "Var olan dosya doğrudan kullanılmalı"
        assert fake_network["urls"] == [], "Ağa hiç gidilmemeli"

    def test_ozet_uyusmuyorsa_yeniden_indirilir(self, qapp, fake_network,
                                                temp_downloads, make_service):
        veri = b"MZ" + b"dogru-icerik"
        bilgi = UpdateInfo.from_dict(manifest_icin(veri))
        fake_network["payload"] = veri
        temp_downloads.mkdir(parents=True, exist_ok=True)
        (temp_downloads / bilgi.filename()).write_bytes(b"bozuk")

        from PySide6.QtCore import QDeadlineTimer

        servis = make_service("https://example.com/version.json")
        assert servis.download(bilgi) is True
        son = QDeadlineTimer(5000)
        while not son.hasExpired() and not fake_network["urls"]:
            pump(qapp)
        assert fake_network["urls"], "Bozuk dosya için indirme başlamalı"

    def test_eski_kurulumlar_temizlenir_gunluk_kalir(self, temp_downloads):
        temp_downloads.mkdir(parents=True, exist_ok=True)
        (temp_downloads / "eski_v1_Setup.exe").write_bytes(b"MZ")
        (temp_downloads / "yeni_v2_Setup.exe").write_bytes(b"MZ")
        (temp_downloads / "install.log").write_text("kurulum kaydi", encoding="utf-8")

        silinen = UpdaterService.cleanup_downloads(
            keep=str(temp_downloads / "yeni_v2_Setup.exe")
        )
        assert silinen == 1
        assert (temp_downloads / "yeni_v2_Setup.exe").exists()
        assert not (temp_downloads / "eski_v1_Setup.exe").exists()
        assert (temp_downloads / "install.log").exists(), "Günlük teşhis için kalmalı"

    def test_dosya_indirilir_ve_ilerleme_bildirilir(self, fake_network, tmp_path):
        veri = b"MZ" + b"x" * 5000
        fake_network["payload"] = veri
        info = UpdateInfo.from_dict(manifest_icin(veri))
        hedef = str(tmp_path / "setup.exe")

        olaylar: list[tuple] = []
        yol = download_to(info, hedef, on_progress=lambda *a: olaylar.append(a))

        assert yol == hedef
        assert os.path.isfile(hedef)
        assert open(hedef, "rb").read() == veri
        assert olaylar, "En az bir ilerleme bildirimi olmalı"
        alinan, toplam, hiz = olaylar[-1]
        assert alinan == len(veri)
        assert toplam == len(veri)
        assert hiz > 0

    def test_yarim_kalan_dosya_birakilmaz(self, fake_network, tmp_path):
        fake_network["payload"] = b"veri"
        info = UpdateInfo.from_dict(manifest_icin(b"veri"))
        hedef = str(tmp_path / "setup.exe")
        download_to(info, hedef)
        assert not os.path.exists(hedef + ".part"), ".part dosyası temizlenmeli"

    def test_sha256_dogrulanir(self, fake_network, tmp_path):
        veri = b"kurulum verisi"
        fake_network["payload"] = veri
        ozet = hashlib.sha256(veri).hexdigest()

        dogru = UpdateInfo.from_dict({**MANIFEST, "sha256": ozet})
        assert download_to(dogru, str(tmp_path / "ok.exe"))

        yanlis = UpdateInfo.from_dict({**MANIFEST, "sha256": "00" * 32})
        with pytest.raises(ValueError, match="sha256"):
            download_to(yanlis, str(tmp_path / "kotu.exe"))
        assert not os.path.exists(str(tmp_path / "kotu.exe"))
        assert not os.path.exists(str(tmp_path / "kotu.exe.part"))

    def test_iptal_edilebilir(self, fake_network, tmp_path):
        fake_network["payload"] = b"y" * (up.CHUNK_SIZE * 4)
        info = UpdateInfo.from_dict(MANIFEST)
        with pytest.raises(up._Cancelled):
            download_to(info, str(tmp_path / "iptal.exe"), is_cancelled=lambda: True)

    def test_boyut_bildirilmezse_cokmez(self, fake_network, tmp_path):
        fake_network["payload"] = b"veri"
        fake_network["headers"] = {}
        info = UpdateInfo.from_dict(manifest_icin(b"veri", size=0))
        olaylar: list[tuple] = []
        download_to(info, str(tmp_path / "s.exe"), on_progress=lambda *a: olaylar.append(a))
        assert olaylar[-1][1] >= 0


# ======================================================================
# 5.3b Ayar izolasyonu
# ======================================================================
class TestAyarIzolasyonu:
    """Testler kullanıcının gerçek ayarlarına asla yazmamalı.

    Bu bir kez kırıldı ve fark edilmesi zor oldu: testler kullanıcının
    kayıt defterindeki ``update/feed_url`` değerini ``https://ornek.test/...``
    yapınca kurulu uygulama güncelleme sunucusuna hiç ulaşamaz hale geldi
    ("getaddrinfo failed"). Sebep ``QSettings(org, app)`` kurucusunun
    ``setDefaultFormat`` çağrısını yok sayıp NativeFormat kullanmasıydı.
    """

    def test_ayarlar_kayit_defterine_yazmaz(self, qapp, settings_dir):
        from app.services.settings import AppSettings

        dosya = AppSettings()._s.fileName()
        assert "HKEY" not in dosya.upper(), (
            f"Ayarlar kullanıcının kayıt defterine yazıyor: {dosya}"
        )
        assert str(settings_dir) in dosya.replace("/", os.sep), (
            f"Ayarlar izole dizinde değil: {dosya}"
        )

    def test_feed_url_degisikligi_izole_kalir(self, qapp, settings_dir):
        from app.services.settings import AppSettings

        ayarlar = AppSettings()
        ayarlar.update_feed_url = "https://ornek.test/version.json"
        ayarlar.sync()

        assert "HKEY" not in ayarlar._s.fileName().upper()
        assert os.path.isfile(ayarlar._s.fileName()), "Değer ini dosyasına yazılmalı"


# ======================================================================
# 5.4 Servis akışı (sinyaller)
# ======================================================================
class TestUpdaterService:
    def _bekle(self, qapp, kosul, sure_ms: int = 5000) -> bool:
        from PySide6.QtCore import QDeadlineTimer

        son = QDeadlineTimer(sure_ms)
        while not son.hasExpired() and not kosul():
            qapp.processEvents()
        return kosul()

    def test_yeni_surum_bulununca_sinyal_yayinlanir(self, qapp, fake_network, make_service):
        servis = make_service("https://x/version.json", current_version="1.0.0")
        bulunan: list = []
        servis.updateAvailable.connect(bulunan.append)

        assert servis.check_for_updates() is True
        assert self._bekle(qapp, lambda: bool(bulunan)), "updateAvailable gelmeli"
        assert bulunan[0].version == "2.5.0"

    def test_guncel_surumde_uptodate_yayinlanir(self, qapp, fake_network, make_service):
        servis = make_service("https://x/version.json", current_version="9.9.9")
        sonuc: list = []
        servis.upToDate.connect(sonuc.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(sonuc))
        assert sonuc[0] == "9.9.9"

    def test_sha256siz_manifest_reddedilir(self, qapp, fake_network, make_service):
        """Bayat önbellek ya da yarım yayın sha256'sız manifest üretebilir.

        Böyle bir manifest kabul edilirse ``download_to`` bütünlük kontrolünü
        atlar ve doğrulanmamış bir kurulum dosyası çalıştırılır.
        """
        fake_network["payload"] = json.dumps({**MANIFEST, "sha256": ""}).encode()
        servis = make_service("https://x/version.json", current_version="1.0.0")
        hatalar: list = []
        bulunan: list = []
        servis.checkFailed.connect(hatalar.append)
        servis.updateAvailable.connect(bulunan.append)

        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(hatalar)), "checkFailed gelmeli"
        assert "sha256" in hatalar[0]
        assert not bulunan, "sha256'sız manifest güncelleme olarak sunulmamalı"

    def test_bozuk_uzunlukta_sha256_reddedilir(self, qapp, fake_network, make_service):
        fake_network["payload"] = json.dumps({**MANIFEST, "sha256": "abc123"}).encode()
        servis = make_service("https://x/version.json", current_version="1.0.0")
        hatalar: list = []
        servis.checkFailed.connect(hatalar.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(hatalar))
        assert "sha256" in hatalar[0]

    def test_checksum_zorunlulugu_kapatilabilir(self, qapp, fake_network, make_service):
        fake_network["payload"] = json.dumps({**MANIFEST, "sha256": ""}).encode()
        servis = make_service(
            "https://x/version.json", current_version="1.0.0", require_checksum=False
        )
        bulunan: list = []
        servis.updateAvailable.connect(bulunan.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(bulunan))
        assert bulunan[0].version == "2.5.0"

    def test_sha256siz_manifest_indirilemez(self, qapp, fake_network, make_service):
        """Kontrolü aşsa bile indirme aşaması ikinci kez doğrular."""
        servis = make_service("https://x/version.json", current_version="1.0.0")
        hatalar: list = []
        servis.downloadFailed.connect(hatalar.append)

        bilgi = UpdateInfo.from_dict({**MANIFEST, "sha256": ""})
        assert servis.download(bilgi) is False
        assert hatalar and "sha256" in hatalar[0]

    def test_ag_hatasi_gui_yi_cokertmez(self, qapp, fake_network, make_service):
        fake_network["error"] = urllib.error.URLError("ağ yok")
        servis = make_service("https://x/version.json")
        hatalar: list = []
        servis.checkFailed.connect(hatalar.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(hatalar))
        assert "ulaşılamadı" in hatalar[0]

    def test_https_disi_adres_reddedilir(self, qapp, fake_network, make_service):
        fake_network["payload"] = json.dumps(
            {**MANIFEST, "download_url": "http://example.com/setup.exe"}
        ).encode()
        servis = make_service("https://x/version.json", current_version="1.0.0")
        hatalar: list = []
        servis.checkFailed.connect(hatalar.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(hatalar))
        assert "https" in hatalar[0]

    def test_https_zorunlulugu_kapatilabilir(self, qapp, fake_network, make_service):
        fake_network["payload"] = json.dumps(
            {**MANIFEST, "download_url": "http://example.com/setup.exe"}
        ).encode()
        servis = make_service("https://x/version.json", current_version="1.0.0",
                                require_https=False)
        bulunan: list = []
        servis.updateAvailable.connect(bulunan.append)
        servis.check_for_updates()
        assert self._bekle(qapp, lambda: bool(bulunan))

    def test_indirme_ucdan_uca_calisir(self, qapp, fake_network, temp_downloads, make_service):
        veri = b"MZ" + b"k" * 2048
        fake_network["payload"] = veri
        servis = make_service("https://x/version.json", current_version="1.0.0")
        biten: list = []
        ilerleme: list = []
        servis.downloadFinished.connect(biten.append)
        servis.downloadProgress.connect(lambda *a: ilerleme.append(a))

        info = UpdateInfo.from_dict(manifest_icin(veri))
        assert servis.download(info) is True
        assert self._bekle(qapp, lambda: bool(biten)), "downloadFinished gelmeli"
        assert os.path.isfile(biten[0])
        assert os.path.dirname(biten[0]) == str(temp_downloads)
        assert ilerleme

    def test_bos_adres_hata_verir(self, qapp, make_service):
        servis = make_service("")
        hatalar: list = []
        servis.checkFailed.connect(hatalar.append)
        assert servis.check_for_updates() is False
        assert hatalar and "adres" in hatalar[0]

    def test_eski_kurulumlar_temizlenir(self, temp_downloads):
        temp_downloads.mkdir(parents=True, exist_ok=True)
        (temp_downloads / "eski.exe").write_bytes(b"x")
        (temp_downloads / "yeni.exe").write_bytes(b"y")
        silinen = UpdaterService.cleanup_downloads(keep=str(temp_downloads / "yeni.exe"))
        assert silinen == 1
        assert (temp_downloads / "yeni.exe").exists()
        assert not (temp_downloads / "eski.exe").exists()


# ======================================================================
# 5.5 Sessiz kurulum
# ======================================================================
class TestSessizKurulum:
    def test_inno_setup_parametreleriyle_baslatilir(self, tmp_path):
        komut = up.installer_command(str(tmp_path / "setup.exe"))
        assert komut[0] == str(tmp_path / "setup.exe")
        assert "/SILENT" in komut
        assert "/CLOSEAPPLICATIONS" in komut
        assert any(arg.startswith("/LOG=") for arg in komut)
        # Kurulum sonrası uygulamayı geri açan bayrak. Restart Manager'ın
        # /RESTARTAPPLICATIONS'ı Qt uygulamasını geri açmıyor (kaydolmuyor);
        # kurulum betiği bu bayrağı görünce uygulamayı kendisi başlatır.
        assert "/RESTARTAPP" in komut
        assert "/RESTARTAPPLICATIONS" not in komut
        # Kapsam bildirilmezse Inno "tüm kullanıcılar mı?" diye sorar.
        assert ("/ALLUSERS" in komut) or ("/CURRENTUSER" in komut)

    def test_kurulum_betigi_surecleri_zorla_kapatir(self):
        """Regresyon: XFA formu açıkken güncelleme geri alınıyordu.

        ``CloseApplications=yes`` ile Restart Manager penceresiz
        ``QtWebEngineProcess.exe``i (XFA formu açıkken çalışır) kapatamıyor,
        "Some applications could not be shut down" deyip kurulumu geri
        alıyordu. ``force`` yanıt vermeyen süreci zaman aşımından sonra
        sonlandırır; ana pencere yine önce nazikçe kapatılır.
        """
        kok = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        betik = open(
            os.path.join(kok, "AGY_PDF_Editor_Setup.iss"), encoding="utf-8"
        ).read()
        assert "\nCloseApplications=force" in betik

    def test_program_files_kurulumu_tum_kullanicilar_olur(self, monkeypatch):
        """Program Files'a kurulu uygulama yönetici hakkıyla güncellenmeli.

        Kapsam bildirilmezse sessiz güncelleme fazladan bir soru sorar ve
        yanlış seçim ikinci bir kopya kurar.
        """
        monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
        assert up.install_scope_args(r"C:\Program Files\AGY Software\App") == [
            "/ALLUSERS"
        ]

    def test_kullanici_dizinindeki_kurulum_yonetici_istemez(self, monkeypatch):
        monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
        assert up.install_scope_args(
            r"C:\Users\x\AppData\Local\Programs\App"
        ) == ["/CURRENTUSER"]

    def test_kurulum_kabuk_uzerinden_baslatilir(self, monkeypatch, tmp_path,
                                                temp_downloads):
        """Kurulum, biz kapandıktan sonra yaşamalı.

        Uygulama bir Windows *Job* nesnesine bağlıysa (kabuktan/terminalden
        açıldığında) biz kapandığımız anda tüm alt süreçler öldürülür;
        ``DETACHED_PROCESS`` ve ``CREATE_BREAKAWAY_FROM_JOB`` bunu
        engellemiyor. Bu yüzden kurulum ``ShellExecuteW`` ile Explorer'a
        doğurtulur — kurulum hiç başlamama hatasının kök nedeni buydu.
        """
        kurulum = tmp_path / "setup.exe"
        kurulum.write_bytes(b"MZ")
        temp_downloads.mkdir(parents=True, exist_ok=True)
        kabuk_cagrilari: list = []
        popen_cagrilari: list = []

        monkeypatch.setattr(up.sys, "platform", "win32")
        monkeypatch.setattr(up, "_shell_execute",
                            lambda yol, arg: kabuk_cagrilari.append((yol, arg)) or True)
        monkeypatch.setattr(up.subprocess, "Popen",
                            lambda c, **k: popen_cagrilari.append(c) or type("P", (), {})())

        launch_installer(str(kurulum))

        assert popen_cagrilari == [], "Kurulum subprocess ile başlatılmamalı"
        (yol, argumanlar), = kabuk_cagrilari
        assert yol == str(kurulum)
        assert "/SILENT" in argumanlar
        assert "/CLOSEAPPLICATIONS" in argumanlar, "Inno açık uygulamayı kendisi kapatır"

    def test_kabuk_basarisizsa_dogrudan_baslatilir(self, monkeypatch, tmp_path,
                                                   temp_downloads):
        kurulum = tmp_path / "setup.exe"
        kurulum.write_bytes(b"MZ")
        temp_downloads.mkdir(parents=True, exist_ok=True)
        cagrilar: list = []
        monkeypatch.setattr(up.sys, "platform", "win32")
        monkeypatch.setattr(up, "_shell_execute", lambda yol, arg: False)
        monkeypatch.setattr(up.subprocess, "Popen",
                            lambda c, **k: cagrilar.append((c, k)) or type("P", (), {})())
        launch_installer(str(kurulum))
        komut, kwargs = cagrilar[0]
        assert komut[0] == str(kurulum)
        assert "/SILENT" in komut
        assert kwargs.get("creationflags") or kwargs.get("start_new_session")

    def test_sessiz_olmayan_kurulumda_parametre_yok(self, monkeypatch, tmp_path,
                                                   temp_downloads):
        kurulum = tmp_path / "setup.exe"
        kurulum.write_bytes(b"MZ")
        temp_downloads.mkdir(parents=True, exist_ok=True)
        cagrilar: list = []
        monkeypatch.setattr(up.sys, "platform", "linux")
        monkeypatch.setattr(up.subprocess, "Popen",
                            lambda c, **k: cagrilar.append(c) or type("P", (), {})())
        launch_installer(str(kurulum), silent=False)
        assert cagrilar[0] == [str(kurulum)]

    def test_olmayan_dosya_hata_verir(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            launch_installer(str(tmp_path / "yok.exe"))

    def test_servis_kurulum_hatasini_yakalar(self, qapp, monkeypatch, make_service):
        servis = make_service("https://x/version.json")
        hatalar: list = []
        servis.installFailed.connect(hatalar.append)
        assert servis.install("C:/olmayan/dosya.exe") is False
        assert hatalar and "başlatılamadı" in hatalar[0]

    def test_basarili_kurulum_sinyal_yayinlar(self, qapp, monkeypatch, tmp_path,
                                              temp_downloads, make_service):
        kurulum = tmp_path / "setup.exe"
        kurulum.write_bytes(b"MZ")
        temp_downloads.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(up.subprocess, "Popen",
                            lambda c, **k: type("P", (), {"pid": 1})())
        servis = make_service("https://x/version.json")
        baslayan: list = []
        servis.installStarted.connect(baslayan.append)
        assert servis.install(str(kurulum)) is True
        assert baslayan == [str(kurulum)]


# ======================================================================
# 5.6 Biçimlendirme yardımcıları
# ======================================================================
class TestBicimlendirme:
    @pytest.mark.parametrize("bayt,beklenen", [
        (512, "512 B"),
        (2048, "2.0 KB"),
        (5 * 1024 * 1024, "5.0 MB"),
    ])
    def test_boyut_okunabilir(self, bayt, beklenen):
        assert human_size(bayt) == beklenen

    def test_hiz_okunabilir(self):
        assert human_speed(0) == "—"
        assert human_speed(1024 * 1024).endswith("/s")


# ======================================================================
# 5.7 Arayüz
# ======================================================================
class TestGuncellemeArayuzu:
    def test_bildirim_diyalogu_bilgileri_gosterir(self, qapp, window):
        from app.ui.dialogs import UpdateAvailableDialog

        dialog = UpdateAvailableDialog(UpdateInfo.from_dict(MANIFEST), window)
        assert "Canlı metin" in dialog.notes.toPlainText()
        assert dialog.btn_update.text() == "Şimdi Güncelle"
        assert dialog.btn_later.text() == "Daha Sonra"
        assert dialog.btn_later.isEnabled() is True
        assert dialog.skip_box.isVisible() or not dialog.isVisible()
        dialog.deleteLater()

    def test_zorunlu_guncellemede_erteleme_kapali(self, qapp, window):
        from app.ui.dialogs import UpdateAvailableDialog

        info = UpdateInfo.from_dict({**MANIFEST, "mandatory": True})
        dialog = UpdateAvailableDialog(info, window)
        assert dialog.btn_later.isEnabled() is False
        assert dialog.skip_requested is False
        dialog.deleteLater()

    def test_ilerleme_diyalogu_yuzde_ve_hiz_gosterir(self, qapp, window):
        from app.ui.dialogs import UpdateProgressDialog

        dialog = UpdateProgressDialog(UpdateInfo.from_dict(MANIFEST), window)
        dialog.update_progress(512, 1024, 2 * 1024 * 1024)
        assert dialog.bar.value() == 50
        assert "2.0 MB/s" in dialog.detail.text()
        assert "512 B" in dialog.detail.text()

        dialog.set_installing()
        assert dialog.bar.value() == 100
        assert dialog.btn_cancel.isEnabled() is False
        dialog.deleteLater()

    def test_boyut_bilinmiyorsa_belirsiz_cubuk(self, qapp, window):
        from app.ui.dialogs import UpdateProgressDialog

        dialog = UpdateProgressDialog(UpdateInfo.from_dict(MANIFEST), window)
        dialog.update_progress(4096, 0, 1024)
        assert dialog.bar.maximum() == 0, "Belirsiz ilerleme çubuğu olmalı"
        dialog.deleteLater()

    def test_iptal_sinyali_yayinlanir(self, qapp, window):
        from app.ui.dialogs import UpdateProgressDialog

        dialog = UpdateProgressDialog(UpdateInfo.from_dict(MANIFEST), window)
        iptaller: list = []
        dialog.cancelled.connect(lambda: iptaller.append(True))
        dialog.btn_cancel.click()
        assert iptaller == [True]
        dialog.deleteLater()

    def test_ilerleme_diyalogu_kapatilabilir(self, qapp, window):
        """``close()`` şeridi gerçekten kapatmalı.

        ``reject()`` yalnızca iptali tetikleyip ``super().reject()``
        çağırmadığı için diyalog hiçbir yoldan kapanmıyordu: kullanıcı
        "Kurulum başlatılıyor… / İptal ediliyor…" yazan pencerede kilitli
        kalıyordu.
        """
        from app.ui.dialogs import UpdateProgressDialog

        dialog = UpdateProgressDialog(UpdateInfo.from_dict(MANIFEST), window)
        dialog.show()
        pump(qapp)
        dialog.set_installing()
        dialog.close()
        pump(qapp)
        assert not dialog.isVisible(), "Şerit kapatılabilmeli"
        dialog.deleteLater()

    def test_kaydetmeyi_reddeden_kullanicida_serit_kapanir(self, qapp, window,
                                                           monkeypatch, tmp_path):
        """Kurulum onaylanmazsa ilerleme şeridi ekranda kalmamalı."""
        from app.ui.dialogs import UpdateProgressDialog

        dialog = UpdateProgressDialog(UpdateInfo.from_dict(MANIFEST), window)
        dialog.show()
        pump(qapp)
        window._update_progress = dialog
        monkeypatch.setattr(window, "_confirm_discard", lambda: False)

        window._install_update(str(tmp_path / "kurulum.exe"))
        pump(qapp)
        assert not dialog.isVisible(), "Vazgeçilince şerit kapanmalı"
        assert window._update_progress is None
        dialog.deleteLater()

    def test_kaydedilmemis_degisiklikte_indirme_baslamaz(self, qapp, window,
                                                         monkeypatch):
        """Soru indirmeden önce sorulur; vazgeçilirse indirme hiç başlamaz."""
        monkeypatch.setattr(window, "_confirm_discard", lambda: False)
        indirmeler: list = []
        monkeypatch.setattr(window.updater, "download",
                            lambda info: indirmeler.append(info) or True)

        window._start_update_download(UpdateInfo.from_dict(MANIFEST))
        pump(qapp)
        assert indirmeler == [], "Vazgeçilince indirme başlamamalı"
        assert window._update_progress is None


# ======================================================================
# 5.8 Ana pencere entegrasyonu
# ======================================================================
class TestAnaPencereEntegrasyonu:
    def test_yardim_menusunde_eylem_var(self, window):
        from PySide6.QtWidgets import QMenu

        eylem = window._actions.get("check_updates")
        assert eylem is not None
        assert eylem.text() == "Güncellemeleri Kontrol Et…"

        yardim = next(
            (m for m in window.menuBar().findChildren(QMenu) if "Yardım" in m.title()),
            None,
        )
        assert yardim is not None, "Yardım menüsü bulunmalı"
        assert eylem in yardim.actions(), "Eylem Yardım menüsünde olmalı"
        assert window._actions["update_on_startup"] in yardim.actions()

    def test_acilis_kontrolu_ayardan_kapatilabilir(self, window, monkeypatch):
        cagrilar: list = []
        monkeypatch.setattr(window, "check_for_updates",
                            lambda silent=False: cagrilar.append(silent))

        window.settings.update_check_on_startup = False
        window.check_for_updates_on_startup()
        assert cagrilar == []

        window.settings.update_check_on_startup = True
        window.check_for_updates_on_startup()
        assert cagrilar == [True], "Açılış kontrolü sessiz olmalı"

    def test_ayar_eylemi_kalici_yazar(self, window):
        window.set_update_check_on_startup(False)
        assert window.settings.update_check_on_startup is False
        window.set_update_check_on_startup(True)
        assert window.settings.update_check_on_startup is True

    def test_servis_ayarlardaki_adresi_kullanir(self, window):
        window.settings.update_feed_url = "https://ornek.test/version.json"
        window._updater = None                      # yeniden kurulmasını sağla
        assert window.updater.feed_url == "https://ornek.test/version.json"
        assert window.updater.current_version == __version__

    def test_guncel_surumde_sessizce_durum_cubugu(self, window, qapp):
        window._updater = None
        window.updater._silent = True
        window._on_up_to_date("1.0.0")
        assert "güncel" in window.statusBar().currentMessage().lower()

    def test_atlanan_surum_sessiz_kontrolde_gosterilmez(self, window, monkeypatch, qapp):
        acilanlar: list = []
        monkeypatch.setattr(
            "app.ui.dialogs.UpdateAvailableDialog",
            lambda info, parent=None: acilanlar.append(info) or _SahteDiyalog(),
        )
        window._updater = None
        window.updater._silent = True
        window.settings.update_skipped_version = "2.5.0"

        window._on_update_available(UpdateInfo.from_dict(MANIFEST))
        assert acilanlar == [], "Atlanan sürüm için diyalog açılmamalı"

    def test_atlanan_surum_zorunluysa_gosterilir(self, window, monkeypatch, qapp):
        acilanlar: list = []
        monkeypatch.setattr(
            "app.ui.dialogs.UpdateAvailableDialog",
            lambda info, parent=None: acilanlar.append(info) or _SahteDiyalog(),
        )
        window._updater = None
        window.updater._silent = True
        window.settings.update_skipped_version = "2.5.0"

        window._on_update_available(UpdateInfo.from_dict({**MANIFEST, "mandatory": True}))
        assert len(acilanlar) == 1, "Zorunlu güncelleme her hâlükârda gösterilmeli"


class _SahteDiyalog:
    """``exec`` çağrısını reddederek diyaloğu kapatan sahte pencere."""

    skip_requested = False

    def exec(self) -> int:
        return QDialog.Rejected


# ======================================================================
# 5.9 Uçtan uca akış (bildirim -> indirme -> kurulum -> çıkış)
# ======================================================================
class TestUctanUcaAkis:
    def test_tam_guncelleme_akisi(self, window, qapp, fake_network, temp_downloads,
                                  monkeypatch):
        """Kullanıcı "Şimdi Güncelle" derse dosya inip kurulum tetiklenmeli."""
        from PySide6.QtCore import QDeadlineTimer

        kurulum_verisi = b"MZ" + b"kurulum" * 500
        fake_network["payload"] = kurulum_verisi

        # 1) Bildirim diyaloğu "Şimdi Güncelle" ile onaylanmış gibi davransın
        class Onaylayan(_SahteDiyalog):
            def exec(self) -> int:
                return QDialog.Accepted

        monkeypatch.setattr("app.ui.dialogs.UpdateAvailableDialog",
                            lambda info, parent=None: Onaylayan())

        # 2) Kurulum süreci gerçekten başlatılmasın
        baslatilan: list = []
        monkeypatch.setattr(up.subprocess, "Popen",
                            lambda c, **k: baslatilan.append(c) or type("P", (), {"pid": 7})())
        # 3) Kaydedilmemiş değişiklik sorusu ve gerçek çıkış devre dışı
        monkeypatch.setattr(window, "_confirm_discard", lambda: True)
        cikislar: list = []
        monkeypatch.setattr("PySide6.QtWidgets.QApplication.quit",
                            staticmethod(lambda: cikislar.append(True)))

        window._updater = None
        window.settings.update_skipped_version = ""
        window._on_update_available(UpdateInfo.from_dict(manifest_icin(kurulum_verisi)))

        son = QDeadlineTimer(5000)
        while not son.hasExpired() and not baslatilan:
            qapp.processEvents()

        assert baslatilan, "Kurulum başlatılmalı"
        komut = baslatilan[0]
        # Windows'ta kurulum, uygulamanın kapanmasını bekleyen bir kabuk
        # üzerinden başlatılır; komut satırı orada kodlanmış durur.
        if "-EncodedCommand" in komut:
            metin = base64.b64decode(
                komut[komut.index("-EncodedCommand") + 1]
            ).decode("utf-16-le")
            yol = metin.split("-FilePath '", 1)[1].split("'", 1)[0]
        else:
            metin = " ".join(komut)
            yol = komut[0]
        assert yol.endswith("AGY_PDF_Editor_v2.5_Setup.exe")
        assert os.path.isfile(yol), "İndirilen dosya %TEMP% altında olmalı"
        assert "/SILENT" in metin

        son = QDeadlineTimer(2000)
        while not son.hasExpired() and not cikislar:
            qapp.processEvents()
        assert cikislar, "Kurulum sonrası uygulama kapanmalı"
        assert window._quitting_for_update is True

        if window._update_progress is not None:
            window._update_progress.close()
        window.updater.shutdown()

    def test_indirme_hatasi_uygulamayi_cokertmez(self, window, qapp, fake_network,
                                                 temp_downloads, monkeypatch):
        fake_network["error"] = urllib.error.URLError("bağlantı koptu")
        uyarilar: list = []
        monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning",
                            staticmethod(lambda *a, **k: uyarilar.append(a)))
        from PySide6.QtCore import QDeadlineTimer

        window._updater = None
        window._start_update_download(UpdateInfo.from_dict(MANIFEST))

        son = QDeadlineTimer(5000)
        while not son.hasExpired() and not uyarilar:
            qapp.processEvents()
        assert uyarilar, "Kullanıcı hata konusunda bilgilendirilmeli"
        assert window.isVisible(), "Pencere ayakta kalmalı"
        window.updater.shutdown()
