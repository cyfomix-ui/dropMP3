#define MyAppId "{{C85CD763-1021-48C5-B807-6B0AE893CF8E}"
#ifndef MyAppVersion
  #define MyAppVersion "1.00"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\dist"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\release"
#endif

[Setup]
AppId={#MyAppId}
AppName=DropMP3
AppVersion={#MyAppVersion}
AppVerName=DropMP3 Ver{#MyAppVersion}
AppPublisher=cyfomix-ui
AppPublisherURL=https://github.com/cyfomix-ui/dropMP3
AppSupportURL=https://github.com/cyfomix-ui/dropMP3/issues
AppUpdatesURL=https://github.com/cyfomix-ui/dropMP3/releases/latest
DefaultDirName={localappdata}\Programs\DropMP3
DefaultGroupName=DropMP3
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\DropMP3.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\DropMP3.ico
OutputDir={#MyOutputDir}
OutputBaseFilename=DropMP3-Setup-Ver{#MyAppVersion}-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\DropMP3.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#MySourceDir}\_conf\app_version.xml"; DestDir: "{app}\_conf"; Flags: ignoreversion
Source: "{#MySourceDir}\_conf\html\*"; DestDir: "{app}\_conf\html"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\DropMP3"; Filename: "{app}\DropMP3.exe"; WorkingDir: "{app}"; IconFilename: "{app}\DropMP3.exe"
Name: "{autodesktop}\DropMP3"; Filename: "{app}\DropMP3.exe"; WorkingDir: "{app}"; IconFilename: "{app}\DropMP3.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DropMP3.exe"; Description: "{cm:LaunchProgram,DropMP3}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; User data is intentionally stored under {localappdata}\DropMP3 and retained.
Type: filesandordirs; Name: "{app}"
