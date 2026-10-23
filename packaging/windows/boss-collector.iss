#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define RepoRoot "..\..\"
#define AppName "BOSS采集助手"

[Setup]
AppId={{7C4C6D6A-7E5E-4F08-9C71-A23B75B0E17A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=BOSS Collector Local Tool
DefaultDirName={localappdata}\Programs\BossCollector
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#RepoRoot}dist\artifacts
OutputBaseFilename=BossCollector-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile={#RepoRoot}assets\boss-collector.ico
UninstallDisplayIcon={app}\BossCollector.exe
UninstallDisplayName={#AppName}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："

[Files]
Source: "{#RepoRoot}dist\BossCollector\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallfiles

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\BossCollector.exe"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\BossCollector.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BossCollector.exe"; Description: "立即启动 {#AppName}"; Flags: nowait postinstall skipifsilent
