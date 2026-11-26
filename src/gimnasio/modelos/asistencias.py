from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Asistencia(Base):
    """Ingreso de un cliente. `fecha` es el día local (Bogotá) del ingreso.

    `casillero_numero` es una instantánea (RN-11): no cambia si luego se libera.
    """

    __tablename__ = "asistencias"
    __table_args__ = (
        CheckConstraint(
            "resultado IN ('permitido','por_vencer','vencido','inactivo','autorizado')",
            name="resultado",
        ),
        CheckConstraint(
            "eliminada = 0 OR (motivo_eliminacion IS NOT NULL AND trim(motivo_eliminacion) <> '')",
            name="motivo_eliminacion",
        ),
        Index("ix_asistencias_cliente_id_fecha", "cliente_id", "fecha"),
        Index("ix_asistencias_fecha", "fecha"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    fecha_hora: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    fecha: Mapped[date] = mapped_column(Date)
    resultado: Mapped[str] = mapped_column(String(10))
    casillero_numero: Mapped[str | None] = mapped_column(String(10))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    eliminada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    motivo_eliminacion: Mapped[str | None] = mapped_column(String(200))
    eliminada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    eliminada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
