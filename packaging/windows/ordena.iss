; Instalador de Windows, con Inno Setup 6. Lo compila la CI después de PyInstaller:
;     iscc packaging\windows\ordena.iss
; La versión llega en la variable de entorno ORDENA_VERSION.

#define AppVersion GetEnv("ORDENA_VERSION")

[Setup]
; Este identificador no se cambia nunca: es lo que hace que una versión nueva se instale
; encima de la anterior en vez de al lado.
AppId={{7D1ADAF3-6AA0-433C-87E0-61186722233F}
AppName=ordena
AppVersion={#AppVersion}
AppVerName=ordena {#AppVersion}
AppPublisher=espi0207
AppPublisherURL=https://github.com/espi0207/ordena
AppSupportURL=https://github.com/espi0207/ordena/issues
DefaultDirName={autopf}\ordena
DisableProgramGroupPage=yes
; Sin permisos de administrador se instala solo para quien lo instala (y no sale el aviso
; de "¿Quieres permitir que esta aplicación haga cambios?").
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist
OutputBaseFilename=ordena-windows
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\ordena.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "contextmenu"; Description: "Añadir «Ordenar con ordena» al menú de las carpetas (clic derecho)"
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "..\..\dist\ordena\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\ordena"; Filename: "{app}\ordena.exe"
Name: "{autodesktop}\ordena"; Filename: "{app}\ordena.exe"; Tasks: desktopicon

[Registry]
; Clic derecho sobre una carpeta, y clic derecho en el fondo de una carpeta abierta.
; En Windows 11 salen dentro de "Mostrar más opciones".
Root: HKA; Subkey: "Software\Classes\Directory\shell\ordena"; ValueType: string; ValueName: ""; ValueData: "Ordenar con ordena"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\ordena"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\ordena.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\ordena\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ordena.exe"" ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\ordena"; ValueType: string; ValueName: ""; ValueData: "Ordenar esta carpeta con ordena"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\ordena"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\ordena.exe"; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\ordena\command"; ValueType: string; ValueName: ""; ValueData: """{app}\ordena.exe"" ""%V"""; Tasks: contextmenu

[Run]
Filename: "{app}\ordena.exe"; Description: "Abrir ordena"; Flags: nowait postinstall skipifsilent
