; Inno Setup script for the separate ODeR Creator application.

#define MyAppName "ODeR Creator"
#define MyAppVersion "2026.0.2a"
#define MyBuildExeName "ODeR Creator.exe"
#define MyAppExeName "ODeR Creator.exe"

[Setup]
AppId={{D8C0F60B-AB9E-4D91-90AA-0BD000000002}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=kaderka
AppPublisherURL=https://github.com/Ka-derka/ODeR
AppSupportURL=https://github.com/Ka-derka/ODeR/issues
AppUpdatesURL=https://github.com/Ka-derka/ODeR/releases
DefaultDirName={autopf}\ODeR Creator
DefaultGroupName={#MyAppName}
OutputDir=release-dist
OutputBaseFilename=ODeR Creator Installer
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=yes
LicenseFile=LICENSE
CloseApplications=yes
RestartApplications=no

[Files]
Source: "dist\{#MyBuildExeName}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCR; Subkey: ".odrproj"; ValueType: string; ValueName: ""; ValueData: "ODeR.CreatorProject"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "ODeR.CreatorProject"; ValueType: string; ValueName: ""; ValueData: "ODeR Creator project"; Flags: uninsdeletekey
Root: HKCR; Subkey: "ODeR.CreatorProject\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "ODeR.CreatorProject\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
