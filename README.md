# PDF Editor

Modern, hızlı ve tamamen Türkçe arayüzlü **PDF görüntüleme ve düzenleme** masaüstü
uygulaması. Python 3.10+, PySide6 (Qt 6) ve PyMuPDF üzerine kurulu; temiz katmanlı
(Clean Architecture) bir mimariyle yazılmıştır.

![Uygulama](assets/app.png)

---

## Özellikler

### Görüntüleyici
- Dosyayı pencerenin **herhangi bir yerine** sürükleyip bırakarak açma
  (belge alanı ve küçük resim paneli dâhil)
- **XFA (etkileşimli XML) formu** desteği: "Adobe Reader gerekli" uyarısı
  yerine formun kendisi çizilir ve doldurulabilir — bkz.
  [XFA formları](#xfa-etkileşimli-form-desteği)
- Ctrl + fare tekerleği ile yakınlaştırma, sayfaya sığdır / genişliğe sığdır
- Tek sayfa, sürekli kaydırma ve çift sayfa (kitap) görünümleri
- Sayfa önizlemeleri, içindekiler (yer imleri) ağacı ve belge içi arama paneli
- Arama sonuçlarının vurgulanması, sonuçlar arasında hızlı gezinme (F3 / Shift+F3)
- Geçerli sayfayı veya tüm sayfaları 90° sağa/sola döndürme
- Koyu / açık tema, kalıcı pencere ve araç ayarları

### Düzenleme ve açıklamalar
- **Canlı metin düzenleyici (WYSIWYG):** sayfa üzerinde doğrudan yazma; yüzen
  biçim çubuğu, sol taşıma (`⋮⋮`) ve sağ genişlik (`⇹`) tutamakları. Ekranda
  görülen konum ve punto, PDF'e işlenenle birebir aynıdır (bkz.
  [Canlı metin düzenleyici](#canlı-metin-düzenleyici-hizalama-sözleşmesi))
- Mevcut metne çift tıklayarak yerinde düzenleme (satır kaymadan)
- Metin kutusu ekleme (yazı tipi, boyut, renk, kalın/italik, hizalama; tam Türkçe karakter desteği)
- Vurgulama, altını çizme, üstünü çizme
- Serbest çizim (kalem) ve silgi
- Şekiller: dikdörtgen, daire/elips, çizgi, ok
- Görsel (PNG/JPG) ekleme
- Fare veya grafik tabletle çizilen dijital imza ekleme
- Metin veya görsel filigran (açı, saydamlık, sayfa aralığı seçimiyle)
- Anlık görüntü tabanlı sınırsız **geri al / yinele**

### Sayfa yönetimi
- Küçük resimleri sürükleyip bırakarak sayfa sıralama
- Sayfa silme, boş sayfa ekleme, sayfa çoğaltma
- Seçili sayfaları ayrı PDF olarak dışa aktarma
- Birden çok PDF'i birleştirme (sayfa aralığı seçimiyle)
- PDF'i aralıklara, sabit adıma veya tek sayfalara bölme

### Araçlar ve dönüştürme
- Sayfaları PNG / JPG / TIFF / BMP / WEBP olarak dışa aktarma (DPI, kalite, çok sayfalı TIFF)
- Metin (.txt) olarak dışa aktarma
- Görsellerden PDF oluşturma
- PDF sıkıştırma / optimizasyon (hazır ayarlarla)
- AES-256 parola koruması ekleme ve mevcut parolayı kaldırma
- Belge bilgileri (metadata) görüntüleme ve düzenleme
- Yazdırma

---

## Klavye kısayolları

| Kısayol | İşlev | Kısayol | İşlev |
|---|---|---|---|
| `Ctrl+O` | Aç | `Ctrl+S` | Kaydet |
| `Ctrl+Shift+S` | Farklı kaydet | `Ctrl+P` | Yazdır |
| `Ctrl+Z` / `Ctrl+Y` | Geri al / yinele | `Ctrl+C` | Seçili metni kopyala |
| `Ctrl+F` | Ara | `F3` / `Shift+F3` | Sonraki / önceki sonuç |
| `Ctrl++` / `Ctrl+-` | Yakınlaştır / uzaklaştır | `Ctrl+0` | Gerçek boyut |
| `Ctrl+8` / `Ctrl+9` | Genişliğe / sayfaya sığdır | `Ctrl+1/2/3` | Görünüm modu |
| `Ctrl+B` | Kenar çubuğu | `Ctrl+T` | Tema değiştir |
| `F11` | Tam ekran | `Ctrl+G` | Sayfaya git |
| `Ctrl+R` / `Ctrl+Shift+R` | Sayfayı döndür | `Ctrl+Delete` | Sayfayı sil |
| `Boşluk` + sürükle | Sayfayı kaydır | `Esc` | Çizimi iptal et |

---

## Proje yapısı

```
pdfEditor/
├── app/
│   ├── core/                 # Saf Python alan katmanı (Qt'den bağımsız)
│   │   ├── pdf_backend.py    # PyMuPDF uyumluluk katmanı
│   │   ├── document.py       # PdfDocument: açma, render, arama, kaydetme
│   │   ├── annotations.py    # Vurgu, çizim, şekil, metin, görsel, filigran
│   │   ├── page_ops.py       # Döndür/sil/ekle/sırala/birleştir/böl
│   │   ├── exporter.py       # Görsel/metin dışa aktarma, sıkıştırma, şifreleme
│   │   ├── fonts.py          # Unicode (Türkçe) yazı tipi çözümleme
│   │   ├── xfa.py            # XFA form alanlarını okuma/doldurma
│   │   ├── xfa_render.py     # XFA şablonunu görüntülenebilir PDF'e çizme
│   │   └── history.py        # Anlık görüntü tabanlı geri al/yinele
│   ├── services/             # Qt köprüsü
│   │   ├── document_controller.py   # UI ↔ core arasındaki tek kapı
│   │   ├── render_service.py        # Arka plan render + LRU önbellek
│   │   ├── updater.py               # Otomatik güncelleme (kontrol/indirme/kurulum)
│   │   └── settings.py              # Kalıcı ayarlar (QSettings)
│   ├── ui/                   # Sunum katmanı
│   │   ├── main_window.py    # Menüler, araç çubukları, tüm akışlar
│   │   ├── file_drop.py      # Dosya sürükle-bırak (alt widget'lar için)
│   │   ├── page_view.py      # Sayfa görüntüleyici ve etkileşimli araçlar
│   │   ├── inline_text_editor.py    # Canlı (tuval üzeri) metin düzenleyici
│   │   ├── theme.py          # Koyu/açık tema ve stil sayfası
│   │   ├── icons.py          # Gömülü SVG simgeler (harici dosya yok)
│   │   ├── tools.py          # Araç durumu ve stil ayarları
│   │   ├── panels/           # Küçük resimler, içindekiler, arama
│   │   └── dialogs/          # Metin, imza, filigran, birleştir, böl, ...
│   └── main.py               # Giriş noktası
├── assets/app.ico            # Uygulama simgesi
├── agy_pdf_editor.spec       # PyInstaller yapılandırması
├── AGY_PDF_Editor_Setup.iss  # Inno Setup kurulum betiği
├── tools/make_icon.py        # Simge üretici
├── build.ps1                 # exe + setup üreten tek komut
├── release.ps1               # derle + GitHub Release + version.json yayını
├── version.json              # Güncelleme bildirimi (canlı feed)
├── requirements.txt
└── run.py                    # Geliştirme başlatıcısı
```

**Mimari kural:** Arayüz katmanı PyMuPDF'e asla doğrudan dokunmaz. Her değişiklik
`DocumentController.edit()` bağlamından geçer; böylece geri al/yinele, kirli-durum
takibi ve önbellek geçersizleme tek noktada toplanır.

---

## Canlı metin düzenleyici (hizalama sözleşmesi)

`app/ui/inline_text_editor.py`, sayfa üzerinde yazarken görülenle PDF'e işlenenin
üst üste oturmasını garanti eder. Üç kural bunu sağlar:

**1. Konum — 0 piksel hizalama.** Kök widget'ta layout yoktur; araç çubuğu,
tutamaklar ve kesikli çerçeve elle konumlandırılır ve çerçeve metin alanının
*dışına* çizilir. `QTextEdit` bütün iç boşluklarından arındırılır
(`setDocumentMargin(0)`, `NoFrame`, `setViewportMargins(0,0,0,0)`, CSS
`padding/margin: 0`). `text_origin()` araç çubuğu + tutamak ofsetini dinamik
döndürür; `PdfView` widget'ı `ekran(x0, y0) - text_origin()` noktasına koyar.
Sonuç: ilk karakterin sol-üst köşesi = PDF `(x0, y0)`.

**2. Punto — DPI tuzağı.** PyMuPDF 72 DPI tabanlıdır; `zoom` ile render edilen
sayfada `fontsize` puntosu tam `fontsize * zoom` piksel yer kaplar. Qt ise
`pointSize`ı ekran DPI'ıyla (Windows'ta 96) çarpar, yani `setFontPointSize(24)`
metni **32 piksel** çizer — %33 büyük. Bu yüzden font boyutu her yerde
**piksel cinsinden** (`QFont.setPixelSize`) verilir ve karakter biçimi
`QTextCharFormat.setFont()` ile aktarılır.

**3. Taban çizgisi.** `page.insert_text(origin, …)` çağrısında `origin` metnin
*taban çizgisidir*, kutunun üstü değil. Düzenleyici ilk satırın taban çizgisini
kendi yerleşiminden okur ve PDF uzayına çevirir:

```
origin_y     = y0 + line.ascent() / zoom
line_height  = line.height() / zoom
```

Böylece PyMuPDF'e "taban çizgisini tam olarak buraya koy" denir. Ölçülen sapma
her zoom ve punto değerinde yatayda **0.000 pt**, dikeyde **≤ 0.01 pt**'dir
(`tests/test_04_inline_text.py`).

Metin onaylandıktan sonra araç otomatik olarak `Tool.SELECT`e döner; sayfaya
tekrar tıklamak yeni kutu açmaz.

---

## XFA (etkileşimli form) desteği

Bazı kurumsal formlar (AB hibe başvuruları, resmî beyannameler…) içeriğini
sayfa akışında değil, belgeye gömülü bir **XML şablonunda** taşır. Katalogda
`/NeedsRendering true` işaretlidir ve sayfada yalnızca şu uyarı görünür:

> The document you are trying to load requires Adobe Reader 8 or higher.

Bu bir bozukluk değildir: form içeriği gerçekten sayfada yoktur. Adobe Reader
dışında hemen hiçbir görüntüleyici (MuPDF, Chrome, Edge, Preview) bu şablonu
çizemez.

Uygulama iki yol sunar.

### 1. Formu görüntüle (önerilen)

*Araçlar ▸ Formu görüntüle (XFA)* — dosya açılırken de teklif edilir.

Şablondaki yerleşim hesaplanır, metin/çizgi/görseller sayfaya işlenir ve
alanlar gerçek **AcroForm widget'ları** olarak eklenir. Sonuç, **her
görüntüleyicide açılan ve doldurulabilen sıradan bir PDF**'tir ve belgenin
Adobe/Foxit'teki görünümünü hedefler:

| Öğe | Davranış |
|---|---|
| `position` (varsayılan düzen) | Çocuklar kendi `x`/`y` değerleriyle |
| `tb` | Yukarıdan aşağıya akış, taşınca yeni sayfa |
| `table` / `row` | Satırlar dikey, hücreler yatay |
| `pageArea` | Arka plan deseni, logo ve altbilgi her sayfaya çizilir |
| `border` kenarları | Üst/sağ/alt/sol ayrı ayrı; çoğu alanda yalnızca alt kenar → alt çizgi stili |
| `caption placement` / `reserve` | Etiket sol/sağ/üst/alt, ayrılan genişlikle |
| `checkButton shape="round"` | Radyo düğmesi (kare kutu değil) |
| `margin` iç boşlukları | Bitişik alanlar birbirine yapışmaz |
| `imageEdit` alanları | Değerlerindeki görsel çizilir (logo, bayrak) |
| Altbilgi `xfa:embed` | `Page <n> of <m>` sayaçları yerine konur |

Üretilen belge **adsız** açılır — diskteki dosyanın karşılığı olmadığı için
"Kaydet" özgün XFA dosyasının üzerine yazmaz, "Farklı Kaydet" sorar.

### 1b. Tüm bölümleriyle görüntüle

*Araçlar ▸ Formu tüm bölümleriyle görüntüle* — özgün belgede yalnızca
seçime göre açılan (`presence="hidden"`) bölümleri de çizer. Görünüm
özgününe sadık değildir ama formun tamamı tek seferde doldurulabilir.
Örnek formda: özgün görünüm 1 sayfa / 5 alan, tüm bölümler 3 sayfa /
66 alan.

### 2. Alanları doğrudan doldur

*Araçlar ▸ Etkileşimli formu doldur…* alanları bölümlere ayrılmış bir
iletişim kutusunda sunar. Girilen değerler özgün belgenin `datasets`
paketine yazılır — Adobe verileri zaten oradan okuduğu için **kaydedilen
dosya Adobe Reader'da dolu olarak açılır**. Alan yolları altform
hiyerarşisini izler (`form.PADORV2.Identification.orgName`).

### Sınırlar ve kabuller

- **Betik kuralları çalıştırılmaz** (koşullu alanlar, hesaplamalar). Özgün
  belgede bir seçim yapılınca açılan bölümler kendiliğinden görünmez;
  bunun için "tüm bölümleriyle" seçeneği vardır.
- Yerleşim Adobe'nin çıktısıyla piksel birebir değildir; bölüm sırası ve
  alan konumları doğru, boşluklar farklılaşabilir.
- Görünür bir metinle örtüşen gizli kopyalar elenir (koşullu başlıklar
  aynı yere iki kez yazılır, elenmezse üst üste biner).
- `presence="invisible"` alanlar çizilmez: bunlar ekranda yer kaplamayan
  iç veri taşıyıcılarıdır (dosya eki içeriği gibi).
- Onay kutusunda şablondaki `<value>` mevcut durum değil, kutu
  işaretlenince kaydedilecek değerdir; durum yalnızca form verisinden gelir.

---

## Otomatik güncelleme

Uzak makinelerdeki kurulumlar kendini internet üzerinden günceller.

- **Sürüm kaynağı:** `app/__init__.py` → `__version__`. Kurulum betiği (`.iss`)
  ve `build.ps1` bu değeri okur; elle senkronlanmaz.
- **Akış:** `Yardım ▸ Güncellemeleri Kontrol Et…` (veya açılışta sessiz kontrol)
  → `version.json` arka plan `QThread`inde indirilir → yeni sürüm varsa bildirim
  diyaloğu → "Şimdi Güncelle" → `%TEMP%\AGYPDFEditorUpdate\` altına canlı
  ilerleme/hız göstergesiyle indirme → Inno Setup kurulumu
  `/SILENT /CLOSEAPPLICATIONS /NORESTART /RESTARTAPP` ile ayrı süreç olarak
  başlatılır → uygulama kapanır → kurulum biter → uygulama geri açılır.
- **Kurulum sonrası yeniden başlatma:** Restart Manager'ın
  `/RESTARTAPPLICATIONS` bayrağı kullanılmaz; yalnızca
  `RegisterApplicationRestart` ile kaydolmuş uygulamaları geri açtığı için Qt
  uygulaması kapalı kalıyordu. Bunun yerine `.iss` içindeki `[Run]` girdisi
  `/RESTARTAPP` bayrağını görünce uygulamayı kendisi başlatır. Bayrak açıkça
  istendiğinden toplu (SCCM/Intune) sessiz kurulumlarda uygulama açılmaz.
- **Güvenlik:** kurulum dosyası yalnızca `https` üzerinden indirilir ve
  `version.json` **geçerli bir `sha256` taşımak zorundadır** — özet eksikse
  manifest baştan reddedilir, eşleşmezse indirilen dosya silinir. (Eksik özet
  sessizce kabul edilseydi doğrulanmamış bir kurulum çalıştırılırdı; bayat CDN
  önbelleği böyle bir manifest üretebiliyor.) İndirme `.part` uzantısıyla
  yapılır, yarım dosya kurulum sanılmaz.
- **Ayarlar:** `Yardım ▸ Açılışta güncelleme kontrol et` ile kapatılabilir;
  komut satırında `--no-update-check` de aynı işi görür. Kullanıcı bir sürümü
  atlarsa (zorunlu olmayan) o sürüm için bir daha sorulmaz.

`version.json` şeması (kök dizindeki dosya örnektir; `build.ps1` her derlemede
`dist/installer/version.json` taslağını `sha256` ve boyutla birlikte üretir):

```json
{
  "version": "1.1.0",
  "download_url": "https://sunucu/AGY_PDF_Editor_v1.1.0_Setup.exe",
  "mandatory": false,
  "release_notes": "- Yenilik\n- Düzeltme",
  "release_date": "2026-08-01",
  "size": 52428800,
  "sha256": "…"
}
```

`mandatory: true` verildiğinde "Daha Sonra" ve "Bu sürümü atla" seçenekleri
kapatılır. Güncelleme adresi `AppSettings.update_feed_url` ile değiştirilebilir.

---

## Geliştirme ortamı

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py                 # veya:  python run.py belge.pdf
```

Gereksinimler: Python 3.10+, PySide6 ≥ 6.6, PyMuPDF ≥ 1.24, Pillow, pypdf.

### Testler

```powershell
pip install pytest
pytest tests -q                     # başsız (offscreen) çalışır
$env:QT_QPA_PLATFORM="windows"; pytest tests -q    # gerçek pencerelerle
```

| Dosya | Kapsam |
|---|---|
| `test_01_file_operations.py` | Açma/kaydetme, dışa aktarma, şifreleme |
| `test_02_text_engine.py` | Metin seçimi, kopyalama, metin motoru |
| `test_03_ui_widgets.py` | Paneller, kısayollar, araç çubukları |
| `test_04_inline_text.py` | Canlı metin düzenleyici: hizalama, punto, taban çizgisi |
| `test_05_updater.py` | Güncelleme servisi (ağ taklitli), diyaloglar, kurulum |

> Not: `offscreen` platformunda Qt taslak font metrikleri döndürür. Bu yüzden
> hizalama testleri mutlak `bbox` yerine "düzenleyicinin bildirdiği taban
> çizgisi = PDF'e yazılan taban çizgisi" sözleşmesini doğrular; bu ölçüm font
> veritabanından bağımsızdır.

---

## Windows kurulum dosyası (.exe) üretimi

Tek komutla hem uygulamayı hem kurulumu üretir:

```powershell
.\build.ps1
```

Betik sırasıyla şunları yapar:

1. `.venv-build` adında temiz bir sanal ortam kurar (yalnızca gerekli paketler —
   böylece pakete sistemdeki alakasız kütüphaneler karışmaz).
2. `assets/app.ico` yoksa üretir.
3. PyInstaller ile `dist/AGY_PDF_Editor/AGY_PDF_Editor.exe` (konsolsuz) oluşturur.
4. Inno Setup varsa `dist/installer/AGY_PDF_Editor_v<sürüm>_Setup.exe` kurulumunu
   derler ve yanına `sha256` içeren bir `version.json` taslağı bırakır.

Yalnızca tek bir adımı çalıştırmak için:

```powershell
.\build.ps1 -SkipInstaller     # sadece exe
.\build.ps1 -SkipExe           # sadece kurulum (mevcut dist klasöründen)
```

Elle yapmak isterseniz:

```powershell
pyinstaller agy_pdf_editor.spec --noconfirm --clean
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" AGY_PDF_Editor_Setup.iss
```

Kurulum dosyası masaüstü kısayolu, Başlat menüsü girdisi, kaldırma (uninstall)
desteği ve isteğe bağlı `.pdf` dosya ilişkilendirmesi içerir. Yönetici hakkı
gerektirmeden kullanıcı klasörüne de kurulabilir.

---

## Yeni sürüm yayınlama

Kurulu uygulamalar `version.json`ı düzenli olarak yoklar; yeni sürüm görünce
kullanıcıya bildirir, indirir, `sha256` ile doğrular ve sessizce kurar.

```powershell
# 1) Sürümü yükseltin: app/__init__.py -> __version__ = "1.0.1"
# 2) Tek komutla yayınlayın
.\release.ps1 -NotesFile .\notes.md
```

`release.ps1` derler, GitHub Release açıp kurulum dosyasını yükler,
**erişilebilirliğini doğrular**, ancak ondan sonra `version.json`ı pushlar.
Bu sıra kritiktir: manifest önce yayınlanırsa istemciler var olmayan bir
dosyayı indirmeye çalışır. Yükleme doğrulanamazsa manifest hiç yayınlanmaz.

Önizleme için `.\release.ps1 -Notes "deneme" -DryRun` hiçbir şey yayınlamaz.

**Önkoşullar:** `gh auth login` ile giriş yapılmış olmalı ve
`__update_repo__`daki depo **public** olmalıdır — private depoda hem manifest
hem release eki kimlik doğrulaması ister, istemciler indiremez.

Yayından sonra `raw.githubusercontent.com` önbelleği nedeniyle güncellemenin
tüm istemcilere ulaşması birkaç dakika sürebilir.

---

## Lisans ve bağımlılıklar

Bu proje PyMuPDF (AGPL / ticari) ve PySide6 (LGPL) kullanır. Uygulamayı
dağıtırken bu bileşenlerin lisans koşullarını gözden geçirin.
