"""Base declarativa y tipos comunes de los modelos."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

# Nombres explícitos para restricciones: Alembic los necesita en SQLite (modo batch).
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


class FechaHoraUTC(TypeDecorator):
    """Marca de tiempo que siempre se guarda en UTC.

    Exige fechas con zona horaria al guardar (evita mezclar hora local y UTC)
    y las devuelve con tzinfo=UTC. Para mostrarlas se convierten a Bogotá.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, valor: datetime | None, dialecto):
        if valor is None:
            return None
        if valor.tzinfo is None:
            raise ValueError("La fecha y hora debe tener zona horaria (se guarda en UTC).")
        return valor.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, valor: datetime | None, dialecto):
        if valor is None:
            return None
        return valor.replace(tzinfo=timezone.utc)


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)
