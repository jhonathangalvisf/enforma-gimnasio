"""Alertas manuales, biometría (reservada), auditoría, backups y configuración."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (
        CheckConstraint("nivel IN ('info','advertencia','critica')", name="nivel"),
        Index("ix_alertas_cliente_id_activa", "cliente_id", "activa"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    mensaje: Mapped[str] = mapped_column(String(300))
    nivel: Mapped[str] = mapped_column(String(11))
    activa: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    creada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creada_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    resuelta_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    resuelta_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)


class Biometria(Base):
    """RESERVADA para la fase de huella. Guarda la plantilla cifrada, nunca la imagen."""

    __tablename__ = "biometria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    dedo: Mapped[str] = mapped_column(String(20))
    plantilla_cifrada: Mapped[bytes] = mapped_column(LargeBinary)
    proveedor: Mapped[str] = mapped_column(String(60))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class Auditoria(Base):
    __tablename__ = "auditoria"
    __table_args__ = (Index("ix_auditoria_fecha_hora", "fecha_hora"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha_hora: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str] = mapped_column(String(60))
    entidad: Mapped[str] = mapped_column(String(40))
    entidad_id: Mapped[int | None] = mapped_column(Integer)
    detalle_json: Mapped[str | None] = mapped_column(Text)


class BackupLog(Base):
    __tablename__ = "backups_log"
    # seguridad = copia automática que se hace justo antes de restaurar otra.
    __table_args__ = (
        CheckConstraint("tipo IN ('automatico','manual','seguridad')", name="tipo"),
        CheckConstraint("resultado IN ('exitoso','fallido')", name="resultado"),
        Index("ix_backups_log_fecha_hora", "fecha_hora"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fecha_hora: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    tipo: Mapped[str] = mapped_column(String(10))
    ruta: Mapped[str] = mapped_column(String(500))
    tamano_bytes: Mapped[int | None] = mapped_column(Integer)
    resultado: Mapped[str] = mapped_column(String(20))
    detalle: Mapped[str | None] = mapped_column(Text)


class Config(Base):
    __tablename__ = "config"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[str | None] = mapped_column(Text)
