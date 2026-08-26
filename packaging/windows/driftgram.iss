; Inno Setup script for Driftgram.
;
; Build:  iscc packaging\windows\driftgram.iss
; Expects PyInstaller to have produced dist\driftgram\ first (see build.py).
;
; Deliberately a per-user install (PrivilegesRequired=lowest):
;   * no UAC prompt, so a non-administrator can install it themselves;
;   * the app writes its manifest and Telegram session under %APPDATA%,
;     which is per-user anyway - a machine-wide install would put the program
;     in Program Files while its data stayed per-user, gaining nothing;
;   * uninstalling never needs elevation either.

#define AppName "Driftgram"
#define AppVersion "1.0.0"
#define AppPublisher "Driftgram"
#define AppExeName "driftgram.exe"

[Setup]
AppId={{7B2F4C1E-9A3D-4E58-B6C7-1F0A2D8E5B43}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=Driftgram-{#AppVersion}-Setup
SetupIconFile=..\generated\driftgram.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Shown on the first page - the audience for this app needs to know what it is
; and, just as importantly, that it never sends their files anywhere but their
; own Telegram account.
AppComments=Keeps your folders backed up to your own Telegram account.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startupicon"; Description: "Start {#AppName} when I log in"; GroupDescription: "Startup:"

[Files]
Source: "..\..\dist\driftgram\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\driftgram\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
; --tray so a login launch starts quietly in the notification area rather than
; throwing a window in the user's face every time they sign in.
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: "--tray"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName} now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The bundle directory only - never {userappdata}\Driftgram. That holds the
; manifest and the Telegram session, and an uninstall must not silently sign
; the user out or throw away the record of what has already been backed up.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  // A running copy holds an open lock on its data directory and its own exe,
  // so replacing the files under it would fail halfway through.
  Exec('taskkill.exe', '/IM driftgram.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec('taskkill.exe', '/IM driftgram.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
