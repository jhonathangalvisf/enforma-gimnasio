"""Ejecuta las migraciones de Alembic desde código (arranque, seed y pruebas)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

RAIZ_PROYECTO = Path(__file__).resolve().parents[3]


def configuracion_alembic(url: str | None = None) -> Config:
    cfg = Config(str(RAIZ_PROYECTO / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ_PROYECTO / "migraciones"))
    if url:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def actualizar_esquema(url: str | None = None) -> None:
    """Equivale a `alembic upgrade head`."""
    command.upgrade(configuracion_alembic(url), "head")
