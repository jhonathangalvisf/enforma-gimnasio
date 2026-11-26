"""Rutas y parámetros generales de la aplicación.

Los datos de usuario (base de datos, fotos, backups, logs) viven fuera de la
carpeta de instalación: en Windows en %APPDATA%\\Enforma. Se pueden cambiar con
variables de entorno, útil para pruebas:

- ENFORMA_DATOS: carpeta de datos.
- ENFORMA_DB_URL: URL completa de SQLAlchemy (tiene prioridad sobre la carpeta).
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

NOMBRE_APP = "Enforma"
ZONA_HORARIA = ZoneInfo("America/Bogota")
FORMATO_FECHA = "%d/%m/%Y"
FORMATO_FECHA_HORA = "%d/%m/%Y %H:%M"

# Valores por defecto de la tabla config (se podrán cambiar desde Configuración).
DIAS_POR_VENCER = 5
MINUTOS_INACTIVIDAD = 15
INTENTOS_LOGIN_MAX = 5


def carpeta_datos() -> Path:
    """Carpeta donde se guardan la base, las fotos y los backups locales."""
    personalizada = os.environ.get("ENFORMA_DATOS")
    if personalizada:
        ruta = Path(personalizada)
    elif os.name == "nt":
        ruta = Path(os.environ.get("APPDATA", Path.home())) / NOMBRE_APP
    else:  # desarrollo en Linux/macOS
        ruta = Path.home() / ".enforma"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def ruta_base_datos() -> Path:
    return carpeta_datos() / "enforma.db"


def url_base_datos() -> str:
    return os.environ.get("ENFORMA_DB_URL") or f"sqlite:///{ruta_base_datos().as_posix()}"
