; =====================================================================
; Inno Setup Script: Calibre Institutional Digital Library MVP
; Safe packaging: Detects existing Calibre, never overwrites Calibre or user libraries.
; =====================================================================

#define MyAppName "Calibre Institutional Digital Library"
#define MyAppVersion "0.5.0"
#define MyAppPublisher "Institutional Digital Library Project"
#define MyAppURL "https://calibre-ebook.com"
#define MyAppExeName "CalibreInstitutionalGateway.exe"

[Setup]
AppId={{C8B7F1D0-4E82-4B6A-91D2-8A33F5E7B1C2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\CalibreInstitutional
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=licenses\LICENSE.txt
OutputDir=..\dist
OutputBaseFilename=CalibreInstitutional-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\bin\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; Safe runtime configuration directory (Preserved during upgrade & uninstall)
Name: "{autoappdata}\CalibreInstitutional\config"; Flags: uninsneveruninstall

[Files]
; Standalone compiled gateway binary & runtime
Source: "..\build\dist\CalibreInstitutionalGateway\*"; DestDir: "{app}\bin"; Flags: recursesubdirs createallsubdirs ignoreversion

; Frontend Templates, Stylesheets, Images, and Scripts (clean production files only)
Source: "..\customization\frontend\*"; DestDir: "{app}\frontend"; Excludes: "*.bak"; Flags: recursesubdirs createallsubdirs ignoreversion

; Scripts & Service Management Utilities
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Excludes: "*.bak"; Flags: recursesubdirs createallsubdirs ignoreversion

; License Notices (Upstream Calibre GPL v3 & Institutional Notices)
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion

; Default Configuration in App Dir
Source: "..\customization\configuration\gateway_config.json"; DestDir: "{app}\configuration"; Flags: ignoreversion

; Initial Configuration Template in AppData (NEVER overwrite existing production configuration)
Source: "..\customization\configuration\gateway_config.json"; DestDir: "{autoappdata}\CalibreInstitutional\config"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\Calibre Institutional Portal"; Filename: "http://127.0.0.1:8085/"
Name: "{group}\Calibre Institutional Admin"; Filename: "http://127.0.0.1:8085/admin"
Name: "{group}\Calibre Institutional First-Time Setup"; Filename: "http://127.0.0.1:8085/setup"
Name: "{group}\Start Background Service"; Filename: "{app}\scripts\start-service.bat"; Flags: runminimized
Name: "{group}\Stop Background Service"; Filename: "{app}\scripts\stop-service.bat"; Flags: runminimized
Name: "{group}\View License Notices"; Filename: "{app}\licenses\CALIBRE_GPL_v3.txt"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Calibre Institutional Library"; Filename: "http://127.0.0.1:8085/"

[Run]
; Register automatic Windows background service
Filename: "{app}\scripts\install-service.bat"; Flags: runhidden; StatusMsg: "Configuring automatic Windows background service..."

; Start service immediately
Filename: "{app}\scripts\start-service.bat"; Flags: runhidden; StatusMsg: "Starting Institutional Gateway service..."

; Launch default web browser to the first-time setup page
Filename: "{cmd}"; Parameters: "/c start http://127.0.0.1:8085/setup"; Description: "Open First-Time Setup Wizard in Browser"; Flags: postinstall shellexec skipifsilent

[UninstallRun]
; Stop service and unregister scheduled task cleanly
Filename: "{app}\scripts\uninstall-service.bat"; RunOnceId: "StopCalibreInstService"; Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; RunOnceId: "KillCalibreInstExe"; Flags: runhidden

[Code]
// ============================================================================
// Upstream Calibre Detection: Never overwrite Calibre or install if missing
// ============================================================================
function CheckCalibreInstalled(): Boolean;
var
  CalibrePath: String;
begin
  Result := False;

  // 1. Direct standard paths
  if FileExists('C:\Program Files\Calibre2\calibre-server.exe') or
     FileExists('C:\Program Files (x86)\Calibre2\calibre-server.exe') or
     FileExists(ExpandConstant('{pf}\Calibre2\calibre-server.exe')) or
     FileExists(ExpandConstant('{localappdata}\Programs\Calibre2\calibre-server.exe')) then
  begin
    Result := True;
    Exit;
  end;

  // 2. Registry App Paths check
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\calibre.exe', 'Path', CalibrePath) or
     RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\calibre.exe', 'Path', CalibrePath) or
     RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\calibre.exe', 'Path', CalibrePath) then
  begin
    if FileExists(AddBackslash(CalibrePath) + 'calibre-server.exe') then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  if not CheckCalibreInstalled() then
  begin
    MsgBox(
      'Calibre Installation Not Detected!' + #13#10 + #13#10 +
      'Calibre Institutional Digital Library requires an existing installation of Calibre ' +
      '(version 7.x, 8.x, or 9.x) to manage books and run the backend Content Server.' + #13#10 + #13#10 +
      'Please download and install Calibre from:' + #13#10 +
      'https://calibre-ebook.com/download_windows' + #13#10 + #13#10 +
      'Once installed, launch this installer again to complete setup.',
      mbCriticalError, MB_OK
    );
    Result := False;
  end
  else
  begin
    Result := True;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox(
      'Calibre Institutional Digital Library has been successfully uninstalled.' + #13#10 + #13#10 +
      'Note: Your Calibre library books, user accounts, and configuration files ' +
      'have been safely preserved in ProgramData/AppData and your original Calibre directories.',
      mbInformation, MB_OK
    );
  end;
end;
