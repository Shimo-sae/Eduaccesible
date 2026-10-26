; Inno Setup (gratis: jrsoftware.org). Abre este archivo con Inno Setup y pulsa Compilar (Ctrl+F9).
; Resultado: Output\EduAccesible-Instalador.exe  (un solo archivo, se instala con Siguiente, Siguiente)
[Setup]
AppName=EduAccesible
AppVersion=1.0
DefaultDirName={localappdata}\EduAccesible
; Se instala en la carpeta del usuario (no en Program Files) para que la app pueda guardar materiales y ajustes
PrivilegesRequired=lowest
DefaultGroupName=EduAccesible
OutputBaseFilename=EduAccesible-Instalador
Compression=lzma2
SolidCompression=yes
DiskSpanning=no
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\EduAccesible.exe
SetupIconFile=logo.ico
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; Flags: checkedonce

[Files]
Source: "dist\EduAccesible\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\EduAccesible"; Filename: "{app}\EduAccesible.exe"
Name: "{autodesktop}\EduAccesible"; Filename: "{app}\EduAccesible.exe"; Tasks: escritorio

[Run]
Filename: "{app}\EduAccesible.exe"; Description: "Abrir EduAccesible"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Al desinstalar se borra TODO lo que la app guardó o descargó (materiales, ajustes, entrada, modelos)
Type: filesandordirs; Name: "{app}"
