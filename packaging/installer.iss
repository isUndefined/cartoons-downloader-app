; All payload files are emitted explicitly from the verified package inventory.
; No user data, wildcard recursion, downloads, forced closing or data deletion.
#include "BuildConfig.iss"

[Setup]
AppId={{B148E74E-40DC-4F99-86BD-208F661609A6}
AppName=Cartoon Downloader
AppVersion={#AppVersion}
AppVerName=Cartoon Downloader {#AppVersion}
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=Cartoon Downloader Installer
DefaultDirName={localappdata}\Programs\Cartoon Downloader
DefaultGroupName=Cartoon Downloader
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.14393
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
UsePreviousTasks=yes
UninstallDisplayIcon={app}\CartoonDownloader.exe
SetupIconFile={#PackageDir}\CartoonDownloader.ico
AppMutex=Local\CartoonDownloader.Desktop.Running
CloseApplications=no
RestartApplications=no
UninstallRestartComputer=no
WizardStyle=modern dynamic polar includetitlebar
LicenseFile=InstallationTerms.txt
OutputDir={#OutputDir}
OutputBaseFilename=CartoonDownloader-Setup
Compression=lzma2/normal
SolidCompression=yes
LZMANumBlockThreads=2
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
#include "Payload.iss"

[Icons]
Name: "{group}\Cartoon Downloader"; Filename: "{app}\CartoonDownloader.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Cartoon Downloader"; Filename: "{app}\CartoonDownloader.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CartoonDownloader.exe"; Description: "{cm:LaunchProgram,Cartoon Downloader}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup: Boolean;
begin
  Result := IsDotNetInstalled(net462, 0);
  if not Result then
    SuppressibleMsgBox(FmtMessage(SetupMessage(msgWinVersionTooLowError), ['.NET Framework', '4.6.2']), mbCriticalError, MB_OK, IDOK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not FileExists(ExpandConstant('{app}\installed.marker')) and
    (DirExists(ExpandConstant('{app}\data')) or
     DirExists(ExpandConstant('{app}\downloads')) or
     FileExists(ExpandConstant('{app}\app.py'))) then
    Result := 'This folder contains a portable application or user data. Choose a new installation folder. Existing data will not be moved or deleted.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  RuntimePath: String;
begin
  if CurStep = ssPostInstall then begin
    { Required by Microsoft for Fixed Version WebView2 on Windows 10, v120+. }
    RuntimePath := ExpandConstant('{app}\tools\webview2\runtime');
    if not Exec(ExpandConstant('{sys}\icacls.exe'), '"' + RuntimePath +
      '" /grant *S-1-15-2-2:(OI)(CI)(RX) *S-1-15-2-1:(OI)(CI)(RX) /T /C /Q',
      '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('Cannot configure the bundled display engine permissions.');
    if Code <> 0 then
      RaiseException('Display engine permissions failed: ' + IntToStr(Code));
  end;
end;

{ User data is never registered for uninstallation. Library/downloads stay in LocalAppData. }
