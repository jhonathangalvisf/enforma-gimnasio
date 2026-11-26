"""Motor SQLite con WAL y claves foráneas activas en cada conexión."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from gimnasio.config import url_base_datos


def _configurar_conexion(conexion_dbapi, _registro) -> None:
    cursor = conexion_dbapi.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def crear_motor(url: str | None = None, **opciones) -> Engine:
    motor = create_engine(url or url_base_datos(), **opciones)
    if motor.dialect.name == "sqlite":
        event.listen(motor, "connect", _configurar_conexion)
    return motor


def crear_fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=motor, expire_on_commit=False)
