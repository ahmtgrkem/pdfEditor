<#
    PDF Editor - tek komutla derleme betiği.

    Kullanım:
        .\build.ps1                  # exe + kurulum
        .\build.ps1 -SkipInstaller   # yalnızca exe
        .\build.ps1 -SkipExe         # yalnızca kurulum
        .\build.ps1 -Rebuild         # sanal ortamı sıfırdan kur
#>
[CmdletBinding()]
param(
    [switch]$SkipExe,
    [switch]$SkipInstaller,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

$VenvDir = Join-Path $Root ".venv-build"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

# Sürümün tek doğru kaynağı app/__init__.py'dir; kurulum betiği de buradan besleniyor.
function Get-AppVersion {
    $initFile = Join-Path $Root "app\__init__.py"
    $match = Select-String -Path $initFile -Pattern '^__version__\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if (-not $match) { throw "Sürüm okunamadı: $initFile" }
    return $match.Matches[0].Groups[1].Value
}

# Yayın deposu da aynı dosyadan gelir (bkz. __update_repo__).
function Get-UpdateRepo {
    $initFile = Join-Path $Root "app\__init__.py"
    $match = Select-String -Path $initFile -Pattern '^__update_repo__\s*=\s*"([^"]+)"' |
        Select-Object -First 1
    if (-not $match) { throw "Yayın deposu okunamadı: $initFile" }
    return $match.Matches[0].Groups[1].Value
}

$AppVersion = Get-AppVersion
Write-Host "Sürüm: $AppVersion (app/__init__.py)" -ForegroundColor DarkGray

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

# PyInstaller ve ISCC günlüklerini stderr'e yazar; PowerShell bunu hata sanmasın.
function Invoke-Native {
    param([string]$File, [string[]]$Arguments, [string]$FailMessage)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $File @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) { throw $FailMessage }
}

# ---------------------------------------------------------------- 1) ortam
if (-not $SkipExe) {
    if ($Rebuild -and (Test-Path $VenvDir)) {
        Write-Step "Eski derleme ortamı siliniyor"
        Remove-Item $VenvDir -Recurse -Force
    }

    if (-not (Test-Path $VenvPy)) {
        Write-Step "Temiz derleme ortamı kuruluyor (.venv-build)"
        Invoke-Native "python" @("-m", "venv", $VenvDir) "Sanal ortam kurulamadı."
        Invoke-Native $VenvPy @("-m", "pip", "install", "--upgrade", "pip") "pip güncellenemedi."
        Invoke-Native $VenvPy @("-m", "pip", "install", "-r",
            (Join-Path $Root "requirements.txt")) "Bağımlılıklar kurulamadı."
        Invoke-Native $VenvPy @("-m", "pip", "install", "pyinstaller") "PyInstaller kurulamadı."
    }
    else {
        Write-Host "Derleme ortamı hazır: $VenvDir"
    }

    # ------------------------------------------------------------ 2) simge
    $Icon = Join-Path $Root "assets\app.ico"
    if (-not (Test-Path $Icon)) {
        Write-Step "Uygulama simgesi üretiliyor"
        Invoke-Native $VenvPy @((Join-Path $Root "tools\make_icon.py")) "Simge üretilemedi."
    }

    # ------------------------------------------------------------ 3) exe
    Write-Step "PyInstaller ile uygulama derleniyor"
    Invoke-Native $VenvPy @("-m", "PyInstaller",
        (Join-Path $Root "agy_pdf_editor.spec"),
        "--noconfirm", "--clean") "PyInstaller başarısız oldu."

    $Exe = Join-Path $Root "dist\AGY_PDF_Editor\AGY_PDF_Editor.exe"
    if (-not (Test-Path $Exe)) { throw "Beklenen çıktı bulunamadı: $Exe" }
    $SizeMb = [math]::Round(((Get-ChildItem (Split-Path $Exe) -Recurse -File |
        Measure-Object Length -Sum).Sum / 1MB), 1)
    Write-Host "Tamam: $Exe  ($SizeMb MB)" -ForegroundColor Green
}

# ------------------------------------------------------------- 4) kurulum
if (-not $SkipInstaller) {
    $Iscc = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $Iscc) {
        Write-Warning "Inno Setup 6 bulunamadı; kurulum dosyası atlandı."
        Write-Warning "İndirme: https://jrsoftware.org/isdl.php"
        return
    }

    Write-Step "Inno Setup ile kurulum dosyası derleniyor (v$AppVersion)"
    Invoke-Native $Iscc @(
        "/DMyAppVersion=$AppVersion",
        (Join-Path $Root "AGY_PDF_Editor_Setup.iss")
    ) "Inno Setup başarısız oldu."

    $Setup = Join-Path $Root "dist\installer\AGY_PDF_Editor_v${AppVersion}_Setup.exe"
    if (Test-Path $Setup) {
        $Mb = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
        Write-Host "Tamam: $Setup  ($Mb MB)" -ForegroundColor Green

        # Yayın için version.json taslağı (sha256 ve gerçek indirme adresi dahil).
        $Hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
        $Manifest = [ordered]@{
            version       = $AppVersion
            download_url  = "https://github.com/$(Get-UpdateRepo)/releases/download/v$AppVersion/$(Split-Path $Setup -Leaf)"
            mandatory     = $false
            release_notes = "- Bu sürümün değişikliklerini buraya yazın."
            release_date  = (Get-Date -Format "yyyy-MM-dd")
            size          = (Get-Item $Setup).Length
            sha256        = $Hash
        }
        $ManifestPath = Join-Path $Root "dist\installer\version.json"
        # BOM'suz yazılmalı: Out-File -Encoding utf8 (PS 5.1) BOM ekler ve
        # istemcideki json.loads ilk karakterde hata verir.
        [System.IO.File]::WriteAllText(
            $ManifestPath,
            ($Manifest | ConvertTo-Json),
            (New-Object System.Text.UTF8Encoding $false)
        )
        Write-Host "Güncelleme bildirimi: $ManifestPath" -ForegroundColor Green
        Write-Host "  -> release_notes alanını doldurup .\release.ps1 ile yayınlayın." -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "Derleme tamamlandı." -ForegroundColor Green
