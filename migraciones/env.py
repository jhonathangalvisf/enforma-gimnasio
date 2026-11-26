"""Entorno de Alembic: usa los modelos de gimnasio y el mismo motor de la app."""

from __future__ import annotations

from alembic import context

from gimnasio.db.engine import crear_motor
from gimnasio.modelos import Base

config = context.config
metadatos = Base.metadata


def _url() -> str | None:
    return config.get_main_option("sqlalchemy.url") or None


def ejecutar_sin_conexion() -> None:
    context.configure(
        url=_url() or crear_motor().url.render_as_string(hide_password=False),
        target_metadata=metadatos,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def ejecutar_con_conexion() -> None:
    motor = crear_motor(_url())
    with motor.connect() as conexion:
        context.configure(
            connection=conexion,
            target_metadata=metadatos,
            render_as_batch=True,  # SQLite necesita modo batch para alterar tablas
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    motor.dispose()


if context.is_offline_mode():
    ejecutar_sin_conexion()
else:
    ejecutar_con_conexion()
