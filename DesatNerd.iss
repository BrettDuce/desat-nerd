; Script generated for desatNerd
; Inno Setup 6.x configuration script

#define MyAppName "desatNerd"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Brett Duce"
#define MyAppURL "https://sleepnerd.net"
#define MyAppExeName "DesatNerd.exe"
#define MyAppAssocName MyAppName + " Study File"
#define MyAppAssocExt ".edf"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; Unique application GUID
AppId={{5D8E423A-8F71-4A59-B1D6-9E457F26E771}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
; Enforce modern 64-bit installation path (Program Files instead of Program Files (x86))
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
OutputDir=installer_output
OutputBaseFilename=DesatNerd_Setup_v{#MyAppVersion}
SetupIconFile=assets\SleepNerd.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; If built using --onedir (folder distribution):
; Copies all binaries, dependencies, and internal DLLs
Source: "dist\DesatNerd\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Explicitly ensure assets folder (icon and PDF User Guide) is copied
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; NOTE: If you built using PyInstaller --onefile instead of --onedir, replace the lines above with:
; Source: "dist\DesatNerd.exe"; DestDir: "{app}"; Flags: ignoreversion
; Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu Application Shortcut
Name: "{autoprograms}\{#MyAppName}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\SleepNerd.ico"

; Start Menu User Guide Shortcut
Name: "{autoprograms}\{#MyAppName}\desatNerd User Guide"; Filename: "{app}\assets\DesatNerd Clinical & Technical User Guide.pdf"

; Desktop Shortcut (Optional task)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; IconFilename: "{app}\assets\SleepNerd.ico"

; Uninstaller Shortcut
Name: "{autoprograms}\{#MyAppName}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Option to launch desatNerd immediately after setup completes
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Cleans up temporary application files or cache if created during runtime
Type: filesandordirs; Name: "{app}\__pycache__"
Type: dirifempty; Name: "{app}\assets"
Type: dirifempty; Name: "{app}"