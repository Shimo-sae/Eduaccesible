; Inno Setup (gratis: jrsoftware.org). Abre este archivo con Inno Setup y pulsa Compilar (Ctrl+F9).
; Resultado: Output\EduAccesible-Instalador.exe  (un solo archivo, se instala con Siguiente, Siguiente)
[Setup]
AppName=EduAccesible
AppVersion=8.0
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

[Code]
// Al desinstalar: ofrece guardar una copia de los materiales en Documentos (se borra todo lo demas).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Origen, Destino: String;
  Codigo: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Origen := ExpandConstant('{app}\materiales');
    if (not UninstallSilent) and DirExists(Origen) then
    begin
      if MsgBox('Quieres guardar una copia de tus materiales en la carpeta Documentos antes de desinstalar?', mbConfirmation, MB_YESNO) = IDYES then
      begin
        Destino := ExpandConstant('{userdocs}\EduAccesible materiales');
        Exec(ExpandConstant('{sys}\xcopy.exe'), '"' + Origen + '" "' + Destino + '" /E /I /Y /Q', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
      end;
    end;
  end;
end;
