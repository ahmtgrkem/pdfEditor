; AGY PDF Editor - Inno Setup 6 Kurulum Betiği
; Derleme: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" AGY_PDF_Editor_Setup.iss
; Önkoşul: dist\AGY_PDF_Editor\ klasörü (pyinstaller agy_pdf_editor.spec)

#define MyAppName "AGY PDF Editor"
; Sürüm tek kaynaktan gelir: app/__init__.py -> __version__
; build.ps1 bunu /DMyAppVersion=x.y.z ile geçirir; elle derlemede
; aşağıdaki yedek değer kullanılır.
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "AGY Software"
#define MyAppExeName "AGY_PDF_Editor.exe"
#define MyAppId "{{D72B9F4E-8E1A-4C2D-B3F5-1A9086E2C51D}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Kurulumu
DefaultDirName={autopf}\AGY Software\AGY PDF Editor
DefaultGroupName={#MyAppName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=dist\installer
OutputBaseFilename=AGY_PDF_Editor_v{#MyAppVersion}_Setup
SetupIconFile=assets\app_icon.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; "force": Restart Manager yanıt vermeyen süreçleri zaman aşımından sonra
; sonlandırır. Zorunlu, çünkü XFA formu açıkken çalışan penceresiz
; QtWebEngineProcess.exe süreci RM'nin WM_CLOSE'unu alamıyor; "yes" ile
; kurulum "Some applications could not be shut down" deyip geri alınıyordu.
; Ana pencere yine önce nazikçe kapatılır (kaydetme onayı çıkar).
CloseApplications=force
RestartApplications=no

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "associate"; Description: "PDF dosyalarını {#MyAppName} ile varsayılan olarak aç"; GroupDescription: "Dosya İlişkilendirme:"; Flags: unchecked

[Files]
; PyInstaller Çıktısının Tamamı (exe + _internal klasörü)
Source: "dist\AGY_PDF_Editor\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\AGY_PDF_Editor\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Windows Birlikte Aç Listesi Kayıtları
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

; İsteğe Bağlı PDF Dosya İlişkilendirmesi
Root: HKA; Subkey: "Software\Classes\AGYPDFEditor.Document"; ValueType: string; ValueName: ""; ValueData: "AGY PDF Belgesi"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\AGYPDFEditor.Document\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\AGYPDFEditor.Document\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "AGYPDFEditor.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: associate

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "AGY PDF Editor'ü Çalıştır"; Flags: nowait postinstall skipifsilent
; Otomatik güncelleme: uygulama kendi kurulumunu /RESTARTAPP ile başlatır ve
; kurulum bitince uygulamayı geri açar. Restart Manager'ın /RESTARTAPPLICATIONS
; bayrağına güvenilemez; yalnızca RegisterApplicationRestart ile kaydolmuş
; uygulamaları geri açar, Qt uygulaması kaydolmadığı için kapalı kalıyordu.
; Bayrak açıkça istendiği için toplu (SCCM/Intune) sessiz kurulumlar etkilenmez.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: GuncellemeSonrasiBaslat

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
{ Kurulum /RESTARTAPP ile mi çağrıldı? Yalnızca otomatik güncelleme akışı bu
  bayrağı geçirir; elle ya da toplu dağıtımla yapılan sessiz kurulumlarda
  uygulama kendiliğinden açılmaz. }
function GuncellemeSonrasiBaslat: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/RESTARTAPP') = 0 then
    begin
      Result := True;
      Exit;
    end;
end;
