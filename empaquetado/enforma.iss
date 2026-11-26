; Instalador de Enforma (Inno Setup 6).
;
; Compilar (desde la raíz del proyecto, después de PyInstaller y del manual en PDF):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DVersion=1.0.0 empaquetado\enforma.iss
; Lo hacen solos construir.bat y el workflow .github/workflows/windows.yml.
;
; Los datos del gimnasio (base, fotos, copias, recibos) NO viven aquí: están en
; %APPDATA%\Enforma de cada usuario de Windows. Instalar, actualizar o desinstalar
; nunca los toca.

#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
; AppId identifica la instalación: no cambiarlo nunca (las actualizaciones lo usan).
AppId={{6E0B7C1A-4F2D-4B8E-9A35-2C7D1E5F8A40}
AppName=Enforma
AppVersion={#Version}
AppVerName=Enforma {#Version}
AppPublisher=Enforma - Centro de acondicionamiento físico
DefaultDirName={autopf}\Enforma
DefaultGroupName=Enforma
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=Enforma-Instalador-{#Version}
SetupIconFile=..\src\gimnasio\recursos\enforma.ico
UninstallDisplayIcon={app}\Enforma.exe
UninstallDisplayName=Enforma {#Version}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
; Si Enforma está abierto, el instalador pide cerrarlo (mismo nombre que crea el programa).
AppMutex=EnformaGimnasioAplicacion
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#Version}
VersionInfoProductName=Enforma
VersionInfoDescription=Instalador de Enforma

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Messages]
spanish.ConfirmUninstall=¿Desinstalar %1?%n%nLos datos del gimnasio (clientes, pagos, fotos y copias de seguridad) NO se borran: quedan en la carpeta de datos y Enforma los vuelve a usar si lo instala de nuevo.
spanish.FinishedLabel=Enforma quedó instalado.%n%nLa primera vez que lo abra le pedirá crear el usuario administrador. Después, cree la contraseña de las copias de seguridad en el módulo Copias de seguridad.

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[InstallDelete]
; Al actualizar, se quitan los archivos internos de la versión anterior antes de copiar
; los nuevos (evita mezclar bibliotecas de dos versiones). Solo la carpeta del programa.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Enforma\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\Manual-Enforma.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Enforma"; Filename: "{app}\Enforma.exe"; Comment: "Gestión del gimnasio Enforma"
Name: "{group}\Manual de instalación y respaldo"; Filename: "{app}\Manual-Enforma.pdf"
Name: "{group}\Diagnóstico de Enforma"; Filename: "{app}\Enforma.exe"; Parameters: "--diagnostico"; Comment: "Revisa la instalación, la protección de la contraseña y la última copia"
Name: "{group}\Desinstalar Enforma"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Enforma"; Filename: "{app}\Enforma.exe"; Tasks: escritorio

[Run]
; Se abre con el usuario que instaló (no como administrador): así usa su carpeta de datos.
Filename: "{app}\Enforma.exe"; Description: "Abrir Enforma ahora"; Flags: nowait postinstall skipifsilent runasoriginaluser
