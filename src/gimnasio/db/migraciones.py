"""Ejecuta las migraciones de Alembic desde código (arranque, seed y pruebas)."""

from __future__ import annotations

from alembic import command
from alembic.config import Config

from gimnasio.rutas import carpeta_programa

RAIZ_PROYECTO = carpeta_programa()  # en el ejecutable: la carpeta interna de PyInstaller


def configuracion_alembic(url: str | None = None) -> Config:
    # No se lee alembic.ini (es para la línea de comandos `alembic ...`): tiene comentarios
    # con tildes y en Windows Python lo leería con la codificación del sistema. El
    # programa solo necesita saber dónde están las migraciones.
    cfg = Config()
    cfg.set_main_option("script_location", str(RAIZ_PROYECTO / "migraciones"))
    cfg.set_main_option("path_separator", "os")
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def actualizar_esquema(url: str | None = None) -> None:
    """Equivale a `alembic upgrade head`."""
    command.upgrade(configuracion_alembic(url), "head")
