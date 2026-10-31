; =====================================================================
; Inno Setup Script: Calibre Institutional Digital Library
; Complete Windows x64 Installation Package with Bundled Runtime
; =====================================================================

#define MyAppName "Calibre Institutional Digital Library"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Institutional Digital Library Project"
#define MyAppURL "http://127.0.0.1:8085"
#define MyAppExeName "CalibreInstitutional.exe"

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
OutputBaseFilename=Calibre-Institutional-Setup
SetupIconFile=..\upstream\calibre\icons\library.ico
Compression=lzma2/fast
LZMANumBlockThreads=8
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
; Safe runtime application-data directories (Always preserved during upgrade & uninstall)
Name: "{localappdata}\CalibreInstitutional\config"; Flags: uninsneveruninstall
Name: "{localappdata}\CalibreInstitutional\local-cache"; Flags: uninsneveruninstall
Name: "{localappdata}\CalibreInstitutional\desktop-config"; Flags: uninsneveruninstall
Name: "{localappdata}\CalibreInstitutional\logs"; Flags: uninsneveruninstall

[Files]
; 1. Native Launcher Executable
Source: "..\build\launcher\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; 2. Complete Bundled Calibre Native Runtime (Executables, Python 3.14 runtime, Qt6 DLLs, and dependencies)
Source: "..\test-environment\installed-app\calibre\*"; DestDir: "{app}\calibre"; Flags: recursesubdirs createallsubdirs ignoreversion

; 3. Modified Calibre Institutional Source Code
Source: "..\upstream\calibre\src\*"; DestDir: "{app}\src"; Excludes: "*.bak, *.pyc, __pycache__, .git*"; Flags: recursesubdirs createallsubdirs ignoreversion

; 4. Institutional Customization Layer (Backend Gateway, Frontend Templates, Static Assets & Configuration)
Source: "..\customization\*"; DestDir: "{app}\customization"; Excludes: "*.bak, *.pyc, __pycache__, .git*"; Flags: recursesubdirs createallsubdirs ignoreversion

; 5. Licenses and Distribution Notices (GPL v3, Third-party Licenses)
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Calibre Institutional Web Portal"; Filename: "{#MyAppURL}"
Name: "{group}\View License Notices"; Filename: "{app}\licenses\CALIBRE_GPL_v3.txt"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""Calibre Institutional Digital Library"" dir=in action=allow protocol=TCP localport=8085"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Calibre Institutional Digital Library"""; Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/F /IM calibre-server.exe"; Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/F /IM calibre.exe"; Flags: runhidden
Filename: "taskkill.exe"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM calibre.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM calibre-parallel.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM calibre-server.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(250);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    MsgBox(
      'Calibre Institutional Digital Library has been successfully uninstalled.' + #13#10 + #13#10 +
      'Note: Your Calibre library books, user accounts, and configuration files ' +
      'have been safely preserved in your LocalAppData and library directories.',
      mbInformation, MB_OK
    );
  end;
end;
