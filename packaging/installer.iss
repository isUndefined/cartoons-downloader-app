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

var
  PreviousInventory: TArrayOfString;

procedure RememberPreviousInventory;
var
  ManifestPath: String;
begin
  SetArrayLength(PreviousInventory, 0);
  if not IsPlainPath(ExpandConstant('{app}'), True) then
    Exit;
  ManifestPath := ExpandConstant('{app}\INSTALLED.sha256');
  if IsPlainPath(ManifestPath, False) then
    LoadStringsFromFile(ManifestPath, PreviousInventory);
end;

function RetiredSource(const Name: String): Boolean;
var
  Extension: String;
begin
  Extension := Lowercase(ExtractFileExt(Name));
  Result := (Name = 'app.py') or (Name = 'diagnostics.py') or
    (Name = 'verify_package.py') or (Name = 'START_WINDOWS.bat') or
    (Name = 'README.md') or
    (Pos('cartoon_downloader/', Name) = 1) or
    (Pos('migrations/', Name) = 1) or
    (Pos('packaging/', Name) = 1) or
    (Pos('launcher-source/', Name) = 1) or
    ((Pos('runtime/python/', Name) = 1) and
     (Pos('runtime/python/licenses/', Name) <> 1) and
     (Name <> 'runtime/python/PYTHON.json')) or
    ((Pos('static/', Name) = 1) and ((Extension = '.html') or
     (Extension = '.css') or (Extension = '.js') or (Extension = '.svg')));
end;

function PlainInstalledFile(const RelativeName: String; var FullPath: String): Boolean;
var
  Remaining, Part, Parent: String;
  Separator: Integer;
begin
  Result := False;
  Remaining := RelativeName;
  if (Remaining = '') or (Pos('\', Remaining) <> 0) or (Pos(':', Remaining) <> 0) then
    Exit;
  Parent := ExpandConstant('{app}');
  if not IsPlainPath(Parent, True) then
    Exit;
  while True do begin
    Separator := Pos('/', Remaining);
    if Separator = 0 then
      Part := Remaining
    else
      Part := Copy(Remaining, 1, Separator - 1);
    if (Part = '') or (Part = '.') or (Part = '..') or
       (Trim(Part) <> Part) or (Copy(Part, Length(Part), 1) = '.') then
      Exit;
    FullPath := Parent + '\' + Part;
    if Separator = 0 then begin
      Result := IsPlainPath(FullPath, False);
      Exit;
    end;
    if not IsPlainPath(FullPath, True) then
      Exit;
    Parent := FullPath;
    Delete(Remaining, 1, Separator);
  end;
end;

procedure RemovePreviousSources;
var
  Index: Integer;
  RelativeName, FullPath, Parent, AppPath, ExpectedHash: String;
begin
  { Only after the new payload is installed. Preserve modified/unlisted files
    and never follow a redirected parent, traverse upward or delete user data. }
  AppPath := ExpandConstant('{app}');
  for Index := 0 to GetArrayLength(PreviousInventory) - 1 do begin
    if Copy(PreviousInventory[Index], 65, 2) <> '  ' then
      Continue;
    RelativeName := Copy(PreviousInventory[Index], 67, Length(PreviousInventory[Index]));
    if not RetiredSource(RelativeName) then
      Continue;
    if not PlainInstalledFile(RelativeName, FullPath) then
      Continue;
    ExpectedHash := Lowercase(Copy(PreviousInventory[Index], 1, 64));
    try
      if Lowercase(GetSHA256OfFile(FullPath)) = ExpectedHash then begin
        if DeleteFile(FullPath) then begin
          Log('Removed previous source/runtime file: ' + RelativeName);
          Parent := ExtractFileDir(FullPath);
          while (Parent <> AppPath) and IsPlainPath(Parent, True) do begin
            if not RemoveDir(Parent) then
              Break;
            Parent := ExtractFileDir(Parent);
          end;
        end else
          Log('Could not remove previous source/runtime file: ' + RelativeName);
      end;
    except
      Log('Kept an unreadable previous file: ' + RelativeName);
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
    RememberPreviousInventory;
  if CurStep = ssPostInstall then begin
    { Required by Microsoft for Fixed Version WebView2 on Windows 10, v120+. }
    RuntimePath := ExpandConstant('{app}\tools\webview2\runtime');
    if not Exec(ExpandConstant('{sys}\icacls.exe'), '"' + RuntimePath +
      '" /grant *S-1-15-2-2:(OI)(CI)(RX) *S-1-15-2-1:(OI)(CI)(RX) /T /C /Q',
      '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('Cannot configure the bundled display engine permissions.');
    if Code <> 0 then
      RaiseException('Display engine permissions failed: ' + IntToStr(Code));
    RemovePreviousSources;
  end;
end;

{ User data is never registered for uninstallation. Library/downloads stay in LocalAppData. }
