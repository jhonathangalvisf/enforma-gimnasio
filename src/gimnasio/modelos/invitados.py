"""Invitados. Las visitas se cuentan desde invitado_asistencias (RN-10)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, event
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc
from gimnasio.texto import normalizar


class Invitado(Base):
    __tablename__ = "invitados"
    __table_args__ = (Index("ix_invitados_documento", "documento", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160))
    documento: Mapped[str] = mapped_column(String(20))
    telefono: Mapped[str | None] = mapped_column(String(30))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # Nombre en minúsculas y sin tildes, para buscar rápido. Se calcula al guardar.
    busqueda: Mapped[str] = mapped_column(String(160), default="", server_default="")
    # Visitas del programa anterior sin fecha conocida (importación, migración 0009).
    # Se suman al total; no cuentan para el límite del mes.
    visitas_anteriores: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


@event.listens_for(Invitado, "before_insert")
@event.listens_for(Invitado, "before_update")
def _actualizar_busqueda(_mapper, _conexion, invitado: Invitado) -> None:
    invitado.busqueda = normalizar(invitado.nombre)


class InvitadoAsistencia(Base):
    __tablename__ = "invitado_asistencias"
    __table_args__ = (
        CheckConstraint(
            "eliminada = 0 OR (motivo_eliminacion IS NOT NULL AND trim(motivo_eliminacion) <> '')",
            name="motivo_eliminacion",
        ),
        Index("ix_invitado_asistencias_invitado_id", "invitado_id"),
        Index("ix_invitado_asistencias_fecha", "fecha"),
        Index("ix_invitado_asistencias_cliente_anfitrion_id", "cliente_anfitrion_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invitado_id: Mapped[int] = mapped_column(ForeignKey("invitados.id"))
    fecha_hora: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    fecha: Mapped[date] = mapped_column(Date)
    cliente_anfitrion_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    eliminada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    motivo_eliminacion: Mapped[str | None] = mapped_column(String(200))
    eliminada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    eliminada_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Administrador que autorizó la visita cuando el invitado ya llegó al límite del mes.
    autorizada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
