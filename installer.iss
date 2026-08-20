; Inno Setup script for Offline Directory Browser.
; Build the standalone exe first with: pyinstaller build.spec

#define MyAppName "ODeR"
#define MyAppVersion "1.0.0"
#define MyBuildExeName "ODeR-Portable.exe"
#define MyAppExeName "ODeR.exe"

[Setup]
AppId={{D8C0F60B-AB9E-4D91-90AA-0BD000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=kaderka
AppPublisherURL=https://github.com/Ka-derka/ODeR
AppSupportURL=https://github.com/Ka-derka/ODeR/issues
AppUpdatesURL=https://github.com/Ka-derka/ODeR/releases
DefaultDirName={autopf}\ODeR
DefaultGroupName={#MyAppName}
OutputDir=release-dist
OutputBaseFilename=ODeR Installer
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
Root: HKCR; Subkey: ".oder"; ValueType: string; ValueName: ""; ValueData: "ODeR.DirectoryPackage"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "ODeR.DirectoryPackage"; ValueType: string; ValueName: ""; ValueData: "ODeR directory package"; Flags: uninsdeletekey
Root: HKCR; Subkey: "ODeR.DirectoryPackage\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCR; Subkey: "ODeR.DirectoryPackage\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
