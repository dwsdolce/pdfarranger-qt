; Inno Setup script for PDF Arranger Qt.
;
; Normally built by packaging\build_win.bat (cmd) or packaging/build_win
; (Cygwin or Git Bash), which stamp the version from git, run PyInstaller and
; then call ISCC. Compiling this script on its own works too, provided
; dist\pdfarranger-qt exists and the version has been stamped:
;
;   python tools\gen_version_build.py
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\pdfarranger-qt.iss

#pragma verboselevel 9

; The version comes from a file rather than an ISCC /D argument on purpose.
; Git Bash rewrites any argument that looks like a Unix path, so /DMyAppVersion=
; arrives as C:\Program Files\Git\DMyAppVersion= there, while the // escape that
; fixes that is passed through literally by Cygwin. A file works in both, and in
; cmd, and in the Inno Setup IDE.
#ifndef MyAppVersion
  #define VersionFile AddBackslash(SourcePath) + "..\build\installer_version"
  #if !FileExists(VersionFile)
    #error build\installer_version is missing. Run: python tools\gen_version_build.py
  #endif
  #define VersionHandle FileOpen(VersionFile)
  #define MyAppVersion Trim(FileRead(VersionHandle))
  #expr FileClose(VersionHandle)
#endif

#define MyAppName "PDF Arranger Qt"
#define MyAppPublisher "Dolce Sfogato"
#define MyAppURL "https://github.com/dwsdolce/pdfarranger-qt"
#define MyAppExeName "pdfarranger-qt.exe"

; ProgId for the "Open with" entry. Versioned by convention so a future
; incompatible change can register a new one without disturbing this.
#define MyAppProgId "PdfArrangerQt.Document.1"

[Setup]
; Uniquely identifies this application. Changing it makes Windows treat a new
; build as a separate product, so upgrades would stop replacing old installs.
AppId={{3812C377-C9B4-41C2-B9E6-A7EF1BAE2047}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Always show the Directory page so the user may choose a different location
; when an existing install is present (see [Code]).
UsePreviousAppDir=no
LicenseFile=..\COPYING
; Install for all users by default; the user may pick a per-user install, which
; needs no administrator rights, from the dialog Inno shows first.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\installer
OutputBaseFilename=PDF_Arranger_Qt_V{#MyAppVersion}
SetupIconFile=..\data\pdfarranger.ico
Compression=lzma2/max
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern
; Uses the Restart Manager to ask a running copy to close rather than requiring
; a reboot to replace files that are in use.
CloseApplications=yes
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "pdfassoc"; Description: "Add {#MyAppName} to the ""Open with"" list for PDF files"; GroupDescription: "File associations:"

[Files]
Source: "..\dist\pdfarranger-qt\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\pdfarranger-qt\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Deliberately an "Open with" entry rather than the default PDF handler: this is
; an editor, not a reader, and silently taking over every PDF double-click is
; not a decision an installer should make. HKA resolves to HKLM for an
; all-users install and HKCU for a per-user one.
Root: HKA; Subkey: "Software\Classes\{#MyAppProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyAppProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyAppProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletekey; Tasks: pdfassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// Win32 API imports for disabling WOW64 file-system redirection.
// The installer is a 32-bit process; without these, FileExists on
// "C:\Program Files\..." is silently redirected to "C:\Program Files (x86)\...".
// ArchitecturesAllowed=x64compatible already blocks 32-bit Windows, so these
// kernel32 exports are guaranteed to be present at runtime.
function Wow64DisableWow64FsRedirection(var OldValue: LongWord): Boolean;
  external 'Wow64DisableWow64FsRedirection@kernel32.dll stdcall';
function Wow64RevertWow64FsRedirection(OldValue: LongWord): Boolean;
  external 'Wow64RevertWow64FsRedirection@kernel32.dll stdcall';

// Detect any existing install of this AppId and let the user choose to
// uninstall it, install alongside it in a different location, or cancel.
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1';

function GetExistingRegValue(const ValueName: String): String;
var
  S: String;
begin
  S := '';
  if not RegQueryStringValue(HKLM, UninstallKey, ValueName, S) then
    RegQueryStringValue(HKCU, UninstallKey, ValueName, S);
  Result := S;
end;

// An earlier install may not have registered under our current AppId (or the
// registry entry was lost), so also probe the chosen directory for an Inno
// uninstaller EXE (unins000.exe..unins009.exe).
function FindUninstallerInDir(const Dir: String): String;
var
  I: Integer;
  NumStr, Candidate: String;
  OldRedir: LongWord;
begin
  Result := '';
  Wow64DisableWow64FsRedirection(OldRedir);
  try
    for I := 0 to 9 do
    begin
      NumStr := IntToStr(I);
      while Length(NumStr) < 3 do
        NumStr := '0' + NumStr;
      Candidate := AddBackslash(Dir) + 'unins' + NumStr + '.exe';
      if FileExists(Candidate) then
      begin
        Result := Candidate;
        Break;
      end;
    end;
  finally
    Wow64RevertWow64FsRedirection(OldRedir);
  end;
end;

function InitializeSetup(): Boolean;
var
  UninstallCmd, ExistingVersion, ExistingLocation, Msg: String;
  Response, ResultCode: Integer;
begin
  Result := True;
  UninstallCmd := GetExistingRegValue('UninstallString');
  if UninstallCmd = '' then
    Exit;

  ExistingVersion  := GetExistingRegValue('DisplayVersion');
  ExistingLocation := GetExistingRegValue('InstallLocation');

  Msg := '{#MyAppName}';
  if ExistingVersion <> '' then
    Msg := Msg + ' ' + ExistingVersion;
  Msg := Msg + ' is already installed';
  if ExistingLocation <> '' then
    Msg := Msg + ' at:' + #13#10 + ExistingLocation;
  Msg := Msg + #13#10#13#10 +
    'Yes    - Uninstall the existing version, then install {#MyAppVersion}.' + #13#10 +
    'No     - Install {#MyAppVersion} to a different location (the existing install stays on disk and must be uninstalled manually if unwanted).' + #13#10 +
    'Cancel - Abort this installation.';

  Response := MsgBox(Msg, mbConfirmation, MB_YESNOCANCEL);
  case Response of
    IDYES:
      begin
        UninstallCmd := RemoveQuotes(UninstallCmd);
        if not Exec(UninstallCmd, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
                    SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to launch the existing uninstaller. Please uninstall {#MyAppName} manually, then re-run this installer.',
                 mbError, MB_OK);
          Result := False;
        end
        else if ResultCode <> 0 then
        begin
          MsgBox('The existing uninstaller returned error code ' + IntToStr(ResultCode) + '.' + #13#10 +
                 'Installation cannot continue. Please uninstall {#MyAppName} manually, then re-run this installer.',
                 mbError, MB_OK);
          Result := False;
        end;
      end;
    IDCANCEL:
      Result := False;
    // IDNO: fall through - the Directory page will let the user pick a new path.
  end;
end;

// Fires after the user picks a destination folder. If that folder already
// contains an Inno uninstaller (from a prior install whose registry entry is
// missing or used a different AppId), offer to run it before overwriting.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  SelectedDir, UninstallExe, Msg: String;
  Response, ResultCode: Integer;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;

  SelectedDir := WizardDirValue;
  UninstallExe := FindUninstallerInDir(SelectedDir);
  if UninstallExe = '' then
    Exit;

  Msg := 'An existing installation was found at:' + #13#10 + SelectedDir + #13#10#13#10 +
    'Yes    - Run the existing uninstaller, then install {#MyAppVersion}.' + #13#10 +
    'No     - Install {#MyAppVersion} into this folder anyway (existing files may be overwritten and orphaned files may remain).' + #13#10 +
    'Cancel - Go back and choose a different location.';

  Response := MsgBox(Msg, mbConfirmation, MB_YESNOCANCEL);
  case Response of
    IDYES:
      begin
        if not Exec(UninstallExe, '/SILENT /NORESTART /SUPPRESSMSGBOXES', '',
                    SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to launch the existing uninstaller.', mbError, MB_OK);
          Result := False;
        end
        else if ResultCode <> 0 then
        begin
          MsgBox('The existing uninstaller returned error code ' + IntToStr(ResultCode) + '.',
                 mbError, MB_OK);
          Result := False;
        end;
      end;
    IDCANCEL:
      Result := False;
    // IDNO: fall through and install into the same folder.
  end;
end;
