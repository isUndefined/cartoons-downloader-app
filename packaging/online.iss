var
  DownloadPage: TDownloadWizardPage;
  ExtractionPage: TExtractionWizardPage;
  VerificationPage: TOutputProgressWizardPage;
  OnlinePrepared: Boolean;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading application components',
    'An internet connection is required. Files are checked before installation.', nil);
  DownloadPage.ShowBaseNameInsteadOfUrl := True;
  ExtractionPage := CreateExtractionPage('Preparing application components',
    'Unpacking the downloaded components into temporary storage.', nil);
  VerificationPage := CreateOutputProgressPage('Checking application components',
    'Verifying downloaded files before changing the installed application.');
end;

procedure ExtractDependency(const ArchiveName, Identifier: String);
begin
  ExtractionPage.Clear;
  ExtractionPage.Add(ExpandConstant('{tmp}\') + ArchiveName,
    ExpandConstant('{tmp}\online\') + Identifier, True);
  ExtractionPage.Extract;
end;

procedure VerifyOnlineFiles;
var
  Lines: TArrayOfString;
  Index: Integer;
  RelativeName, FileName, ExpectedHash: String;
begin
  ExtractTemporaryFile('OnlineFiles.sha256');
  if not LoadStringsFromFile(ExpandConstant('{tmp}\OnlineFiles.sha256'), Lines) then
    RaiseException('Cannot read the dependency file inventory.');
  VerificationPage.SetProgress(0, GetArrayLength(Lines));
  for Index := 0 to GetArrayLength(Lines) - 1 do begin
    if Copy(Lines[Index], 65, 2) <> '  ' then
      RaiseException('Invalid dependency file inventory.');
    ExpectedHash := Copy(Lines[Index], 1, 64);
    RelativeName := Copy(Lines[Index], 67, Length(Lines[Index]));
    FileName := ExpandConstant('{tmp}\') + RelativeName;
    VerificationPage.SetText('Checking application components', ExtractFileName(FileName));
    if not FileExists(FileName) then
      RaiseException('A required downloaded file is missing: ' + RelativeName);
    if Lowercase(GetSHA256OfFile(FileName)) <> ExpectedHash then
      RaiseException('Downloaded file verification failed: ' + RelativeName);
    VerificationPage.SetProgress(Index + 1, GetArrayLength(Lines));
  end;
end;

procedure PrepareOnlineDependencies;
begin
  if OnlinePrepared then
    Exit;
  DownloadPage.Clear;
  #include "OnlineDownloads.iss"
  DownloadPage.Show;
  try
    DownloadPage.Download;
  finally
    DownloadPage.Hide;
  end;
  ExtractionPage.Show;
  try
    #include "OnlineExtraction.iss"
  finally
    ExtractionPage.Hide;
  end;
  VerificationPage.Show;
  try
    VerifyOnlineFiles;
  finally
    VerificationPage.Hide;
  end;
  OnlinePrepared := True;
end;
