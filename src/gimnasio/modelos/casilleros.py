"""Casilleros y su historial de asignaciones.

Regla (RN-06): un cliente tiene como máximo un casillero activo y un casillero
pertenece como máximo a un cliente activo. Se refuerza en la base con dos
índices únicos parciales sobre las asignaciones sin fecha de liberación.

Cada asignación tiene su propio vencimiento ("pagado hasta", día local de Bogotá,
inclusive), independiente de la membresía del cliente: el casillero puede
asignarse o pagarse en una fecha distinta a la del plan. La vigencia del
casillero se calcula a partir de esa fecha; nunca se guarda.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Casillero(Base):
    __tablename__ = "casilleros"
    __table_args__ = (
        CheckConstraint("zona IN ('hombres','mujeres','mixto')", name="zona"),
        CheckConstraint("estado IN ('disponible','ocupado','mantenimiento')", name="estado"),
        Index("ix_casilleros_numero", "numero", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero: Mapped[str] = mapped_column(String(10))
    zona: Mapped[str] = mapped_column(String(7))
    estado: Mapped[str] = mapped_column(
        String(13), default="disponible", server_default="disponible"
    )
    notas: Mapped[str | None] = mapped_column(Text)


class CasilleroAsignacion(Base):
    __tablename__ = "casillero_asignaciones"
    __table_args__ = (
        CheckConstraint(
            "fecha_liberacion IS NULL OR fecha_liberacion >= fecha_asignacion",
            name="fechas",
        ),
        Index(
            "uq_casillero_activo",
            "casillero_id",
            unique=True,
            sqlite_where=text("fecha_liberacion IS NULL"),
        ),
        Index(
            "uq_cliente_casillero_activo",
            "cliente_id",
            unique=True,
            sqlite_where=text("fecha_liberacion IS NULL"),
        ),
        Index("ix_casillero_asignaciones_fecha_asignacion", "fecha_asignacion"),
        Index("ix_casillero_asignaciones_fecha_liberacion", "fecha_liberacion"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    casillero_id: Mapped[int] = mapped_column(ForeignKey("casilleros.id"))
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    fecha_asignacion: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    fecha_liberacion: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Último día pagado del casillero (inclusive). NULL solo en datos anteriores a la Fase 5.
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    asignado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    liberado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    motivo_liberacion: Mapped[str | None] = mapped_column(String(200))
