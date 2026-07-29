<#
    AGY PDF Editor - yayın (release) betiği.

    Ne yapar
    --------
    1. app/__init__.py'den sürümü ve yayın deposunu okur.
    2. build.ps1 ile exe + kurulum dosyasını üretir (-SkipBuild ile atlanır).
    3. version.json'ı gerçek indirme adresi, boyut ve sha256 ile hazırlar.
    4. GitHub Release açar, kurulum dosyasını yükler ve erişilebilirliğini
       gerçekten indirmeye çalışarak doğrular.
    5. EN SON version.json'ı depoya pushlar.

    Adım 4-5 sırası kritiktir: manifest önce yayınlanırsa kullanıcılar henüz
    var olmayan bir dosyayı indirmeye çalışır ve güncelleme hataya düşer.
    Adım 4 başarısız olursa manifest hiç yayınlanmaz.

    Kullanım
    --------
        .\release.ps1 -NotesFile .\notes.md
        .\release.ps1 -Notes "- Şu düzeltildi`n- Bu eklendi"
        .\release.ps1 -NotesFile .\notes.md -Mandatory
        .\release.ps1 -Notes "deneme" -DryRun     # hiçbir şey yayınlamaz
        .\release.ps1 -Notes "deneme" -SkipBuild  # mevcut dist çıktısını kullanır

    Önkoşullar (tek seferlik)
    -------------------------
        winget install --id GitHub.cli
        gh auth login                 # tarayıcı açar
        Depo GitHub'da public olmalı.
#>
[CmdletBinding()]
param(
    [string]$Notes,
    [string]$NotesFile,
    [switch]$Mandatory,
    [switch]$SkipBuild,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Read-InitValue([string]$Name) {
    $initFile = Join-Path $Root "app\__init__.py"
    $match = Select-String -Path $initFile -Pattern "^$Name\s*=\s*`"([^`"]+)`"" |
        Select-Object -First 1
    if (-not $match) { throw "$Name okunamadı: $initFile" }
    return $match.Matches[0].Groups[1].Value
}

# gh günlüklerini stderr'e yazar; PowerShell bunu hata sanmasın.
function Invoke-Native {
    param([string]$File, [string[]]$Arguments, [string]$FailMessage)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $File @Arguments | ForEach-Object { Write-Host $_ }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw $FailMessage }
}

# ------------------------------------------------------------ 1) yapılandırma
$AppVersion = Read-InitValue "__version__"
$Repo       = Read-InitValue "__update_repo__"
$Branch     = Read-InitValue "__update_branch__"
$Tag        = "v$AppVersion"
$SetupName  = "AGY_PDF_Editor_v${AppVersion}_Setup.exe"
$SetupPath  = Join-Path $Root "dist\installer\$SetupName"
$FeedUrl    = "https://raw.githubusercontent.com/$Repo/$Branch/version.json"
$AssetUrl   = "https://github.com/$Repo/releases/download/$Tag/$SetupName"

Write-Host "Sürüm : $AppVersion" -ForegroundColor DarkGray
Write-Host "Depo  : $Repo ($Branch)" -ForegroundColor DarkGray
Write-Host "Etiket: $Tag" -ForegroundColor DarkGray

# ------------------------------------------------------------ 2) önkoşullar
$ghVar = [bool](Get-Command gh -ErrorAction SilentlyContinue)
if (-not $ghVar) {
    $ghMesaj = @"
GitHub CLI (gh) bulunamadı. Kurulum:

    winget install --id GitHub.cli

Kurduktan sonra YENİ bir terminal açıp bir kez giriş yapın:

    gh auth login
"@
    # -DryRun yalnızca manifesti gösterir; gh olmadan da önizlenebilmeli.
    if ($DryRun) { Write-Warning $ghMesaj } else { throw $ghMesaj }
}

if (-not $DryRun -and $ghVar) {
    # Depo public mi? Private depoda updater indirme yapamaz; sessizce
    # başarısız olmaktansa yayın öncesi durmak yeğdir.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $gorunurluk = (& gh repo view $Repo --json visibility --jq .visibility) 2>$null
    $ghExit = $LASTEXITCODE
    $ErrorActionPreference = $previous

    if ($ghExit -ne 0) {
        throw "Depo bilgisi alınamadı: $Repo. 'gh auth login' ile giriş yaptınız mı?"
    }
    if ($gorunurluk -ne "PUBLIC") {
        throw @"
Depo $Repo şu anda $gorunurluk.

Private depoda hem raw.githubusercontent.com hem de release ekleri kimlik
doğrulaması ister; kullanıcıların uygulaması güncellemeyi indiremez.

Çözüm 1: Depoyu public yapın.
    Settings -> General -> Danger Zone -> Change visibility

Çözüm 2: Kaynak kodu gizli tutup yalnızca yayın dosyaları için ayrı bir
    public depo açın, sonra app/__init__.py içindeki __update_repo__
    değerini o depoya çevirin.
"@
    }
    Write-Host "Görünürlük: PUBLIC" -ForegroundColor DarkGray
}

# ------------------------------------------------------------ 3) sürüm notları
if ($NotesFile) {
    if (-not (Test-Path $NotesFile)) { throw "Sürüm notu dosyası bulunamadı: $NotesFile" }
    $Notes = (Get-Content $NotesFile -Raw -Encoding UTF8).Trim()
}
if (-not $Notes) {
    throw "Sürüm notu zorunlu. -Notes ""- Değişiklik"" veya -NotesFile .\notes.md kullanın."
}

# Aynı etiket zaten yayınlanmış mı? Üzerine yazmak, güncellemeyi almış
# kullanıcılarda sha256 uyuşmazlığına yol açar.
if (-not $DryRun -and $ghVar) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & gh release view $Tag --repo $Repo --json tagName 2>$null | Out-Null
    $varMi = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
    if ($varMi) {
        throw @"
$Tag etiketi zaten yayınlanmış.

Yeni bir yayın için app/__init__.py içindeki __version__ değerini yükseltin.
Bu yayını gerçekten değiştirmek istiyorsanız önce silin:

    gh release delete $Tag --repo $Repo --cleanup-tag
"@
    }
}

# ------------------------------------------------------------ 4) derleme
if (-not $SkipBuild) {
    Write-Step "Uygulama derleniyor"
    & (Join-Path $Root "build.ps1")
}
else {
    Write-Host "Derleme atlandı (-SkipBuild)." -ForegroundColor DarkGray
}

if (-not (Test-Path $SetupPath)) {
    $mevcut = (Get-ChildItem (Join-Path $Root 'dist\installer') -ErrorAction SilentlyContinue |
        ForEach-Object { "  " + $_.Name }) -join "`n"
    throw @"
Kurulum dosyası bulunamadı: $SetupPath

dist\installer içindekiler:
$mevcut
"@
}

# ------------------------------------------------------------ 5) manifest
Write-Step "version.json hazırlanıyor"
$SetupFile = Get-Item $SetupPath
$Manifest = [ordered]@{
    version       = $AppVersion
    download_url  = $AssetUrl
    mandatory     = [bool]$Mandatory
    release_notes = $Notes
    release_date  = (Get-Date -Format "yyyy-MM-dd")
    size          = $SetupFile.Length
    sha256        = (Get-FileHash $SetupPath -Algorithm SHA256).Hash.ToLower()
}
$ManifestJson = $Manifest | ConvertTo-Json
$ManifestPath = Join-Path $Root "version.json"

Write-Host $ManifestJson
Write-Host "Kurulum: $SetupName  ($([math]::Round($SetupFile.Length / 1MB, 1)) MB)"

if ($DryRun) {
    Write-Host ""
    Write-Host "-DryRun: hiçbir şey yayınlanmadı." -ForegroundColor Yellow
    return
}

# BOM'suz UTF-8: BOM'lu dosyada istemci tarafındaki json.loads hata verir.
[System.IO.File]::WriteAllText(
    $ManifestPath, $ManifestJson, (New-Object System.Text.UTF8Encoding $false))

# ------------------------------------------------------------ 6) release
Write-Step "GitHub Release oluşturuluyor ve kurulum dosyası yükleniyor"
$NotesPath = Join-Path $env:TEMP "agy_release_notes_$AppVersion.md"
[System.IO.File]::WriteAllText($NotesPath, $Notes, (New-Object System.Text.UTF8Encoding $false))

Invoke-Native "gh" @(
    "release", "create", $Tag, $SetupPath,
    "--repo", $Repo,
    "--target", $Branch,
    "--title", $Tag,
    "--notes-file", $NotesPath
) "Release oluşturulamadı."

Write-Step "Kurulum dosyası doğrulanıyor"
try {
    $head = Invoke-WebRequest -Uri $AssetUrl -Method Head -UseBasicParsing -TimeoutSec 60
    $uzak = [int64]$head.Headers['Content-Length']
    if ($uzak -ne $SetupFile.Length) {
        throw "Boyut uyuşmuyor: yerel $($SetupFile.Length), uzak $uzak"
    }
    Write-Host "Erişilebilir: $AssetUrl ($uzak bayt)" -ForegroundColor Green
}
catch {
    throw @"
Yüklenen dosyaya erişilemedi: $AssetUrl
$($_.Exception.Message)

version.json YAYINLANMADI; kullanıcılar etkilenmedi. Release'i inceleyin:
    gh release view $Tag --repo $Repo --web
"@
}

# ------------------------------------------------------------ 7) manifesti yayınla
# Buradan sonrası yayının kendisi: manifest push edildiği anda güncelleme canlı.
Write-Step "version.json yayınlanıyor (yayın burada başlıyor)"
Invoke-Native "git" @("add", "--", "version.json") "version.json eklenemedi."
Invoke-Native "git" @("commit", "-m", "Yayin: v$AppVersion") "Commit oluşturulamadı."
Invoke-Native "git" @("push", "origin", $Branch) "version.json pushlanamadı."

Write-Step "Yayın doğrulanıyor"

# Depodaki asıl içerik: API, raw.githubusercontent gibi CDN'de önbeklenmez.
try {
    $depoda = Invoke-RestMethod "https://api.github.com/repos/$Repo/contents/version.json?ref=$Branch" `
        -Headers @{ Accept = "application/vnd.github.raw" } -TimeoutSec 30 | ConvertFrom-Json
    if ($depoda.sha256 -eq $Manifest.sha256) {
        Write-Host "Depodaki manifest dogru (sha256 eslesti)." -ForegroundColor Green
    }
    else {
        throw "Depodaki sha256 ($($depoda.sha256)) beklenenden farkli ($($Manifest.sha256))."
    }
}
catch {
    Write-Warning "Depo icerigi dogrulanamadi: $($_.Exception.Message)"
}

# Kullanıcıların gerçekten gördüğü adres. DİKKAT: yalnızca "version" alanına
# bakmak yetmez — bayat önbellek de aynı sürüm numarasını taşıyabilir ve
# yayın başarılı sanılır. Ayırt edici alan sha256'dır.
Write-Host "raw.githubusercontent.com onbellegi bekleniyor (en fazla 5 dk)..." -ForegroundColor DarkGray
$tazelendi = $false
foreach ($deneme in 1..10) {
    try {
        $canli = (Invoke-WebRequest -Uri $FeedUrl -UseBasicParsing -TimeoutSec 30).Content |
            ConvertFrom-Json
        if ($canli.sha256 -eq $Manifest.sha256) {
            Write-Host "Feed guncel: v$($canli.version) (sha256 eslesti, $deneme. deneme)" -ForegroundColor Green
            $tazelendi = $true
            break
        }
        Write-Host "  $deneme/10 - hala bayat (sha256: '$($canli.sha256)')" -ForegroundColor DarkGray
    }
    catch {
        Write-Host "  $deneme/10 - okunamadi: $($_.Exception.Message)" -ForegroundColor DarkGray
    }
    if ($deneme -lt 10) { Start-Sleep -Seconds 30 }
}

if (-not $tazelendi) {
    Write-Warning @"
Feed hala bayat icerik donduruyor.

Depodaki dosya dogru; sorun raw.githubusercontent.com onbelleginde. Genelde
birkac dakika icinde kendiliginden duzelir. Kullanicilar bu sure boyunca
guncellemeyi gormez - veri kaybi ya da bozuk kurulum riski yoktur.

Kontrol:  curl -s $FeedUrl
"@
}

Write-Host ""
Write-Host "Yayın tamamlandı: $Tag" -ForegroundColor Green
Write-Host "  Manifest: $FeedUrl"
Write-Host "  Kurulum : $AssetUrl"
