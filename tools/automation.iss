; Automation-Setup.exe: the installer for the folder built by tools/build.py.
;
;   python tools/build.py
;   "C:\Program Files\Inno Setup 7\ISCC.exe" tools\automation.iss
;
; Nothing is compiled or hidden. What lands on disk is the same plain .py files
; as the repo, plus a Python of its own, so the folder can be opened in an
; editor and the scripts run from a terminal exactly as before.
;
; Two rules are deliberate and easy to break by accident:
;
;   1. Per-user, never Program Files. That folder is not only the program, it is
;      also the user's scripts, and the app writes into it: a twin file on every
;      Run, the GUI line when a script is ticked, and any script the user adds.
;      Program Files is locked, so Run itself would fail there. Installing under
;      the user's own AppData also means no administrator password.
;
;   2. A later version never overwrites a script. Only the program is replaced.
;      See the onlyifdoesntexist flag below.

#define AppName "Automation"
#define AppVersion "0.1.0"
#define AppPublisher "Ingrid Kjos"
#define AppURL "https://github.com/kjos-i/Automation"
#define Built "..\build\Automation"

[Setup]
; A fixed AppId is what makes the next version an UPGRADE rather than a second
; copy. Never change it.
AppId={{F56C57E8-409F-4E91-9ECC-95DA912D2141}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
VersionInfoVersion={#AppVersion}

DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

LicenseFile=..\LICENSE
SetupIconFile=..\images\automation.ico
UninstallDisplayIcon={app}\images\automation.ico
WizardStyle=modern

; x64 only, because the bundled Python and Flet client are both x64 builds.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\build
OutputBaseFilename={#AppName}-Setup
Compression=lzma2/max
SolidCompression=yes

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the desktop"; GroupDescription: "Shortcuts:"

[Files]
; The program. Replaced wholesale on an upgrade, since nobody edits it.
Source: "{#Built}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Built}\gui\*"; DestDir: "{app}\gui"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Built}\images\*"; DestDir: "{app}\images"; Flags: ignoreversion
Source: "{#Built}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Built}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Built}\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
; Launches the same window WITH a console, so a startup failure is readable.
; The shortcut uses pythonw, which would swallow it.
Source: "{#Built}\debug.cmd"; DestDir: "{app}"; Flags: ignoreversion

; The scripts. `onlyifdoesntexist` is the upgrade rule: a first install writes
; them, a later version adds any that are new and LEAVES THE REST ALONE. That
; keeps both the settings someone edited by hand and which scripts show in the
; window, since that is the GUI line inside the file.
Source: "{#Built}\*.py"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\images\automation.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui\app.py"""; WorkingDir: "{app}"; IconFilename: "{app}\images\automation.ico"; Tasks: desktopicon

[Run]
; pythonw, not python: a windowed launch with no console behind the window.
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui\app.py"""; WorkingDir: "{app}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the user added are not registered with the installer, so without this
; the folder would survive with their scripts in it. Uninstall removes
; everything, which is why InitializeUninstall says so first.
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := MsgBox(
      'This removes the whole Automation folder, including any scripts you added'
      + ' and any changes you made to the ones that came with it.'#13#10#13#10
      + 'Save anything you want to keep first.'#13#10#13#10
      + 'Your API keys are stored by Windows, not in this folder, and are left'
      + ' alone.'#13#10#13#10
      + 'Continue?',
      mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ClientDir: String;
begin
  // The Flet client is a shared display component in the user's home folder,
  // not ours: any other app built with Flet uses the same copy. Ask, and
  // default to leaving it, because removing it makes those apps re-download
  // ~96 MB on their next start, which looks to the user like a broken program.
  if CurUninstallStep = usPostUninstall then
  begin
    ClientDir := ExpandConstant('{%USERPROFILE}\.flet\client');
    if DirExists(ClientDir) then
      if MsgBox(
          'Also remove the shared display component (about 96 MB)?'#13#10#13#10
          + 'Other apps built with Flet use the same copy. If you have none,'
          + ' it is safe to remove.',
          mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ClientDir, True, True, True);
  end;
end;
