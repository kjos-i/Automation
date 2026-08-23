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
; The README, opened in a browser rather than as the README.md file beside the
; scripts: a clean Windows machine has nothing registered for .md, so
; double-clicking it asks the user to choose a program. The web copy renders
; properly and is the current one rather than the one frozen at install time.
Name: "{group}\{#AppName} help"; Filename: "{#AppURL}#the-window"

[Run]
; pythonw, not python: a windowed launch with no console behind the window.
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\gui\app.py"""; WorkingDir: "{app}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Files the user added are not registered with the installer, so without this
; the folder would survive with their scripts in it. Uninstall removes
; everything, which is why InitializeUninstall says so first.
Type: filesandordirs; Name: "{app}"

[Code]
{ One dialog, not a run of yes/no boxes: what uninstalling always does is said
  once, and the two things that live OUTSIDE this folder are offered as ticks.
  Both start unticked, because both are shared or hard to get back. }

var
  RemoveKeys: Boolean;
  RemoveFletClient: Boolean;

function FletClientDir(): String;
begin
  Result := ExpandConstant('{%USERPROFILE}\.flet\client');
end;

{ Design units. CreateCustomForm SCALES the numbers it is given (by 2.96 on a
  247% display), so passing ScaleX(...) scales them a second time: the first
  version came out 3360 pixels wide with its buttons off the screen. Pass the
  form raw units, then measure what it became and lay the children out in the
  same proportion. }
const
  BaseWidth = 460;
  BaseHeight = 300;

var
  FormScaleNum: Integer;

function D(Value: Integer): Integer;
begin
  Result := MulDiv(Value, FormScaleNum, BaseWidth);
end;

function AskWhatToRemove(): Boolean;
var
  Form: TSetupForm;
  Info: TNewStaticText;
  KeysBox: TNewCheckBox;
  FletBox: TNewCheckBox;
  OkButton: TNewButton;
  CancelButton: TNewButton;
  Y: Integer;
begin
  { CreateCustomForm(ClientWidth, ClientHeight, KeepSizeX, KeepSizeY). The last
    two say whether the form may grow with WizardSizePercent; nothing here
    stretches, so both are False. }
  Form := CreateCustomForm(BaseWidth, BaseHeight, False, False);
  FormScaleNum := Form.ClientWidth;
  try
    Form.Caption := 'Uninstall Automation';

    Info := TNewStaticText.Create(Form);
    Info.Parent := Form;
    Info.Left := D(16);
    Info.Top := D(16);
    Info.Width := Form.ClientWidth - D(32);
    Info.WordWrap := True;
    { AutoSize False, then AdjustHeight once the caption is set. With AutoSize
      True the label sizes to its longest line in BOTH directions instead of
      wrapping, and the form grows with it: the first version came out wider
      than the screen with its buttons out of reach. }
    Info.AutoSize := False;
    { A checkbox cannot wrap (TNewCheckBox has no WordWrap), so the reasoning
      lives here and the ticks stay to one line each. No indent on the two
      middle paragraphs: a label cannot hang an indent under a wrapped line,
      so an indented paragraph loses it the moment it runs to two lines. }
    Info.Caption :=
      'Uninstalling removes the whole Automation folder, including any scripts'
      + ' you added and any changes you made to the ones that came with it.'
      + ' Save anything you want to keep first.'#13#10#13#10
      + 'Two things are kept outside that folder and will stay unless you tick'
      + ' them:'#13#10#13#10
      + 'Your API keys are held by Windows, not by this app, so reinstalling'
      + ' would find them again.'#13#10#13#10
      + 'The display component is about 96 MB in your user folder and is'
      + ' shared with any other app built with Flet. Removing it makes those'
      + ' download it again.';
    Info.AdjustHeight;

    Y := Info.Top + Info.Height + D(16);

    KeysBox := TNewCheckBox.Create(Form);
    KeysBox.Parent := Form;
    KeysBox.Left := D(16);
    KeysBox.Top := Y;
    KeysBox.Width := Form.ClientWidth - D(32);
    KeysBox.Height := D(20);
    KeysBox.Checked := False;
    KeysBox.Caption := 'Also remove my saved API keys';

    Y := Y + KeysBox.Height + D(8);

    FletBox := TNewCheckBox.Create(Form);
    FletBox.Parent := Form;
    FletBox.Left := D(16);
    FletBox.Top := Y;
    FletBox.Width := Form.ClientWidth - D(32);
    FletBox.Height := D(20);
    FletBox.Checked := False;
    FletBox.Enabled := DirExists(FletClientDir);
    FletBox.Caption := 'Also remove the shared display component (96 MB)';

    { The form is sized to the content, not the other way round, so the buttons
      cannot end up below the bottom edge however the text wraps. }
    Y := Y + FletBox.Height + D(20);
    Form.ClientHeight := Y + D(28) + D(16);

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Width := D(90);
    CancelButton.Height := D(28);
    CancelButton.Left := Form.ClientWidth - CancelButton.Width - D(16);
    CancelButton.Top := Y;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    OkButton := TNewButton.Create(Form);
    OkButton.Parent := Form;
    OkButton.Width := CancelButton.Width;
    OkButton.Height := CancelButton.Height;
    OkButton.Left := CancelButton.Left - OkButton.Width - D(8);
    OkButton.Top := CancelButton.Top;
    OkButton.Caption := 'Uninstall';
    OkButton.ModalResult := mrOk;
    OkButton.Default := True;

    Result := Form.ShowModal = mrOk;
    RemoveKeys := Result and KeysBox.Checked;
    RemoveFletClient := Result and FletBox.Checked and FletBox.Enabled;
  finally
    Form.Free;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := AskWhatToRemove;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  { Credentials go first, while the app is still on disk: clearing them means
    running its own code, which knows the names because it reads them out of
    each script's os.getenv calls. }
  if (CurUninstallStep = usUninstall) and RemoveKeys then
    Exec(ExpandConstant('{app}\python\python.exe'),
         ExpandConstant('"{app}\gui\clear_keys.py"'),
         ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);

  { The Flet client is in the user's home folder and is shared with every other
    app built with Flet, which is why this is a tick rather than a default. }
  if (CurUninstallStep = usPostUninstall) and RemoveFletClient then
    DelTree(FletClientDir, True, True, True);
end;
