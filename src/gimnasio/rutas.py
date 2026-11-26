"""Dónde están los archivos del programa (no los datos del gimnasio).

En desarrollo, los archivos están en el proyecto (`src/gimnasio/...`,
`migraciones/`). Empaquetado con PyInstaller, todo queda dentro de la carpeta
interna del ejecutable (`sys._MEIPASS`): `migraciones/` en la raíz y
los recursos del paquete en `gimnasio/`. Los datos (base, fotos, copias) nunca van
aquí: ver `config.carpeta_datos()`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def empaquetado() -> bool:
    """True si corre desde el ejecutable de PyInstaller."""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def carpeta_programa() -> Path:
    """Carpeta que contiene `migraciones/`."""
    if empaquetado():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def carpeta_paquete() -> Path:
    """Carpeta del paquete `gimnasio` (ayuda, recursos)."""
    if empaquetado():
        return Path(sys._MEIPASS) / "gimnasio"
    return Path(__file__).resolve().parent


def recurso(nombre: str) -> Path:
    """Ruta de un archivo de `gimnasio/recursos` (sonido, ícono, logo)."""
    return carpeta_paquete() / "recursos" / nombre


def carpeta_ayuda() -> Path:
    return carpeta_paquete() / "ayuda"
