; All payload files are emitted explicitly from the verified package inventory.
; No user data, wildcard recursion, forced closing or user-data deletion.
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
#ifdef OnlineInstaller
OutputBaseFilename=CartoonDownloader-Online-Setup
ArchiveExtraction=full
#else
OutputBaseFilename=CartoonDownloader-Setup
#endif
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
#ifdef OnlineInstaller
#include "online.iss"
#endif
function NativeFileAttributes(const FileName: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function IsPlainPath(const Path: String; Directory: Boolean): Boolean;
var
  Attributes: LongWord;
begin
  Attributes := NativeFileAttributes(Path);
  Result := (Attributes <> $FFFFFFFF) and ((Attributes and $400) = 0);
  if Directory then
    Result := Result and ((Attributes and $10) <> 0)
  else
    Result := Result and ((Attributes and $10) = 0);
end;

procedure RemovePreviousPythonSymbols;
var
  Lines: TArrayOfString;
  Index: Integer;
  Prefix, RelativeName, FileName, SymbolPath, ManifestPath, ExpectedHash: String;
begin
  { Upgrades otherwise retain files omitted from the new payload. Only remove
    unchanged symbols recorded as owned by the previous installer. }
  if not IsPlainPath(ExpandConstant('{app}'), True) or
     not IsPlainPath(ExpandConstant('{app}\runtime'), True) or
     not IsPlainPath(ExpandConstant('{app}\runtime\python'), True) or
     not IsPlainPath(ExpandConstant('{app}\runtime\python\DLLs'), True) then
    Exit;
  ManifestPath := ExpandConstant('{app}\INSTALLED.sha256');
  if not IsPlainPath(ManifestPath, False) then
    Exit;
  if not LoadStringsFromFile(ManifestPath, Lines) then
    Exit;
  Prefix := 'runtime/python/DLLs/';
  for Index := 0 to GetArrayLength(Lines) - 1 do begin
    if Copy(Lines[Index], 65, 2) <> '  ' then
      Continue;
    RelativeName := Copy(Lines[Index], 67, Length(Lines[Index]));
    if Copy(RelativeName, 1, Length(Prefix)) <> Prefix then
      Continue;
    FileName := Copy(RelativeName, Length(Prefix) + 1, Length(RelativeName));
    if (Length(FileName) <= 4) or (Lowercase(ExtractFileExt(FileName)) <> '.pdb') or
       (Pos('/', FileName) <> 0) or (Pos('\', FileName) <> 0) or
       (Pos(':', FileName) <> 0) then
      Continue;
    SymbolPath := ExpandConstant('{app}\runtime\python\DLLs\') + FileName;
    if not IsPlainPath(SymbolPath, False) then
      Continue;
    ExpectedHash := Lowercase(Copy(Lines[Index], 1, 64));
    try
      if Lowercase(GetSHA256OfFile(SymbolPath)) = ExpectedHash then begin
        if DeleteFile(SymbolPath) then
          Log('Removed previous Python debug symbol: ' + FileName)
        else
          Log('Could not remove previous Python debug symbol: ' + FileName);
      end;
    except
      Log('Kept an unreadable previous Python debug symbol: ' + FileName);
    end;
  end;
end;

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
#ifdef OnlineInstaller
  if Result = '' then begin
    try
      PrepareOnlineDependencies;
    except
      Result := 'Application components could not be prepared. Check your connection and retry. ' + GetExceptionMessage;
    end;
  end;
#endif
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
  RuntimePath: String;
begin
  if CurStep = ssInstall then
    RemovePreviousPythonSymbols;
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
