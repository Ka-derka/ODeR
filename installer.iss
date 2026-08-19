; Inno Setup script for Offline Directory Browser.
; Build the standalone exe first with: pyinstaller build.spec

#define MyAppName "ODeR"
#define MyAppVersion "0.15.2"
#define MyAppExeName "OfflineDirectoryBrowser.exe"

[Setup]
AppId={{D8C0F60B-AB9E-4D91-90AA-0BD000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\Offline Directory Browser
DefaultGroupName={#MyAppName}
OutputDir=installer-dist
OutputBaseFilename=OfflineDirectoryBrowser-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
ChangesAssociations=yes

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

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
