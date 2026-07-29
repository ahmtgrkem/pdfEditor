"""AGY PDF Editor - Modern PDF görüntüleme ve düzenleme masaüstü uygulaması.

Sürüm numarasının **tek doğru kaynağı** bu dosyadaki ``__version__``tur.
Kurulum betiği (``installer/*.iss``) ve derleme betiği (``build.ps1``) bu
değeri buradan okur; elle güncellenmemelidir.
"""

__version__ = "1.0.0"
__app_name__ = "AGY PDF Editor"
__app_short_name__ = "AGY PDF"
__org_name__ = "AGY Software"
__author__ = "Ahmet Görkem Yavuz"

#: Güncellemelerin yayınlandığı GitHub deposu (``kullanıcı/depo``).
#:
#: **Public olmalıdır.** Private depoda hem ham dosya hem release eki kimlik
#: doğrulaması ister; uygulama bunları indiremez. Kaynak kodu gizli tutmak
#: isteniyorsa burada yalnızca yayın dosyalarını barındıran ayrı bir public
#: depo kullanılabilir — ``release.ps1`` her iki durumda da aynı çalışır.
#:
#: Bu değer tek doğru kaynaktır: ``release.ps1`` manifest adresini de kurulum
#: dosyasının indirme adresini de buradan üretir.
__update_repo__ = "ahmtgrkem/pdfEditor"

#: ``version.json``ın yayınlandığı dal. Manifest deponun kökünde durur.
__update_branch__ = "main"

#: Otomatik güncelleme akışının (version.json) adresi.
#: Kullanıcı ayarlarından (``AppSettings.update_feed_url``) değiştirilebilir.
__update_feed__ = (
    f"https://raw.githubusercontent.com/{__update_repo__}/{__update_branch__}/version.json"
)


def update_download_url(version: str, filename: str) -> str:
    """``vX.Y.Z`` etiketine yüklenen kurulum dosyasının indirme adresi.

    GitHub release ekleri sabit bir kalıptan servis edilir; adres dosya
    yüklenmeden önce de bilinir. ``release.ps1`` manifesti bununla üretir.
    """
    return (
        f"https://github.com/{__update_repo__}/releases/download/v{version}/{filename}"
    )
