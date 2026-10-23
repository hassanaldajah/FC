; Windows installer for FC, built with Inno Setup 7 (free):
;   ISCC.exe /DVersion=2.1.0 packaging\windows\FC.iss      (after PyInstaller made dist\FC)
; Installs for the current user only (no administrator prompt) into
; %LOCALAPPDATA%\Programs\FC, the folder FC 1.x installed itself into, so an update simply
; replaces it and the old shortcuts keep working. The installed FC opens at once: unlike the
; old single exe it has nothing to unpack at start.
; Silent install for tests: FC-<version>-win64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART

#ifndef Version
  #error Pass the version: ISCC /DVersion=2.1.0 FC.iss
#endif

[Setup]
AppId={{5B0C7F3E-6A51-4C8B-9F0E-3D2A7C1E9B64}
AppName=FC
AppVerName=FC {#Version}
AppVersion={#Version}
AppPublisher=Hassan Aldajah
AppPublisherURL=https://github.com/hassanaldajah/FC
AppSupportURL=https://github.com/hassanaldajah/FC/issues
AppComments=Convert, compress, merge, split and protect files
VersionInfoVersion={#Version}
VersionInfoDescription=FC (File Converter) setup
SourceDir=..\..
OutputDir=dist
OutputBaseFilename=FC-{#Version}-win64-setup
SetupIconFile=fc.ico
UninstallDisplayIcon={app}\FC.exe
UninstallDisplayName=FC (File Converter)
PrivilegesRequired=lowest
DefaultDirName={autopf}\FC
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a shortcut on the Desktop"

[InstallDelete]
; libraries of the version being replaced: never mix two versions' files
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\FC\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FC"; Filename: "{app}\FC.exe"; Comment: "FC: convert, compress and edit files"
Name: "{autodesktop}\FC"; Filename: "{app}\FC.exe"; Comment: "FC: convert, compress and edit files"; Tasks: desktopicon

[Run]
Filename: "{app}\FC.exe"; Description: "Open FC now"; Flags: nowait postinstall skipifsilent
