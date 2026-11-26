# -*- mode: python ; coding: utf-8 -*-
"""Empaquetado de Enforma con PyInstaller (modo carpeta, sin consola).

Uso (desde la raíz del proyecto, con el entorno activado):
    pyinstaller empaquetado/enforma.spec --noconfirm --clean

Resultado: dist/Enforma/Enforma.exe y su carpeta _internal/. El instalador de
Inno Setup (empaquetado/enforma.iss) toma esa carpeta completa.

Se usa modo carpeta y no un solo .exe porque arranca más rápido (no descomprime nada
en cada inicio) y los antivirus lo marcan mucho menos.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH lo define PyInstaller)
SRC = RAIZ / "src"
sys.path.insert(0, str(SRC))
from gimnasio import __version__  # noqa: E402

ICONO = SRC / "gimnasio" / "recursos" / "enforma.ico"

# Archivos que el programa lee del disco (ver gimnasio/rutas.py).
datos = [
    (str(RAIZ / "migraciones" / "env.py"), "migraciones"),
    (str(RAIZ / "migraciones" / "script.py.mako"), "migraciones"),
    (str(RAIZ / "migraciones" / "versions" / "*.py"), "migraciones/versions"),
    (str(SRC / "gimnasio" / "ayuda" / "*.md"), "gimnasio/ayuda"),
    (str(SRC / "gimnasio" / "recursos" / "*.wav"), "gimnasio/recursos"),
    (str(SRC / "gimnasio" / "recursos" / "*.ico"), "gimnasio/recursos"),
    (str(SRC / "gimnasio" / "recursos" / "*.png"), "gimnasio/recursos"),
]
datos += collect_data_files("tzdata")      # zona horaria America/Bogota en Windows
datos += collect_data_files("reportlab")   # fuentes de los PDF
datos += collect_data_files("alembic")     # plantillas de Alembic

# Las migraciones se cargan desde archivos .py en tiempo de ejecución: todo lo que
# importan debe ir dentro del ejecutable aunque el análisis no lo vea.
ocultos = (
    collect_submodules("gimnasio")
    + collect_submodules("alembic", filter=lambda n: not n.startswith("alembic.testing"))
    + collect_submodules("sqlalchemy.dialects.sqlite")
    + ["logging.handlers", "sqlite3", "winsound"]
)

a = Analysis(  # noqa: F821
    [str(SRC / "gimnasio" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datos,
    hiddenimports=ocultos,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "faker", "PyInstaller", "IPython", "matplotlib",
              "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821


def _info_version():
    """Propiedades del .exe (clic derecho → Propiedades → Detalles)."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
        VSVersionInfo,
    )
    numeros = tuple(int(n) for n in __version__.split(".")) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numeros, prodvers=numeros),
        kids=[
            StringFileInfo([StringTable("240A04B0", [  # español (Colombia), Unicode
                StringStruct("CompanyName", "Enforma"),
                StringStruct("FileDescription", "Enforma - Gestión del gimnasio"),
                StringStruct("FileVersion", __version__),
                StringStruct("InternalName", "Enforma"),
                StringStruct("OriginalFilename", "Enforma.exe"),
                StringStruct("ProductName", "Enforma"),
                StringStruct("ProductVersion", __version__),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x240A, 1200])]),
        ],
    )


exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Enforma",
    debug=False,
    strip=False,
    upx=False,          # UPX dispara falsos positivos de antivirus
    console=False,      # aplicación de ventanas, sin consola negra
    icon=str(ICONO),
    version=_info_version(),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Enforma",
)
