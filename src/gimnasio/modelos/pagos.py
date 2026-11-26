"""Planes, membresías y pagos. Nada financiero se borra: se anula con motivo."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Plan(Base):
    __tablename__ = "planes"
    __table_args__ = (
        CheckConstraint("duracion_dias > 0", name="duracion_positiva"),
        CheckConstraint("precio >= 0", name="precio_no_negativo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre: Mapped[str] = mapped_column(String(60))
    duracion_dias: Mapped[int] = mapped_column(Integer)
    precio: Mapped[int] = mapped_column(Integer)  # COP sin decimales
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class Membresia(Base):
    """fecha_fin = fecha_inicio + duracion_dias - 1 (inclusive, RN-03)."""

    __tablename__ = "membresias"
    __table_args__ = (
        CheckConstraint("estado IN ('activa','anulada')", name="estado"),
        CheckConstraint("fecha_fin >= fecha_inicio", name="fechas"),
        CheckConstraint("precio_pactado >= 0", name="precio_no_negativo"),
        Index("ix_membresias_cliente_id_fecha_fin", "cliente_id", "fecha_fin"),
        Index("ix_membresias_fecha_fin", "fecha_fin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes.id"))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)
    precio_pactado: Mapped[int] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(8), default="activa", server_default="activa")
    motivo_descuento: Mapped[str | None] = mapped_column(String(200))
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)


class Pago(Base):
    __tablename__ = "pagos"
    __table_args__ = (
        CheckConstraint("concepto IN ('membresia','casillero','otro')", name="concepto"),
        CheckConstraint("metodo IN ('efectivo','tarjeta','transferencia')", name="metodo"),
        CheckConstraint("monto > 0", name="monto_positivo"),
        CheckConstraint(
            "metodo = 'efectivo' OR (referencia IS NOT NULL AND trim(referencia) <> '')",
            name="referencia_obligatoria",
        ),
        CheckConstraint(
            "anulado = 0 OR (motivo_anulacion IS NOT NULL AND trim(motivo_anulacion) <> '')",
            name="motivo_anulacion",
        ),
        Index("ix_pagos_consecutivo", "consecutivo", unique=True),
        Index("ix_pagos_cliente_id", "cliente_id"),
        Index("ix_pagos_fecha_hora", "fecha_hora"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    consecutivo: Mapped[int] = mapped_column(Integer)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    membresia_id: Mapped[int | None] = mapped_column(ForeignKey("membresias.id"))
    concepto: Mapped[str] = mapped_column(String(10))
    monto: Mapped[int] = mapped_column(Integer)
    metodo: Mapped[str] = mapped_column(String(13))
    referencia: Mapped[str | None] = mapped_column(String(60))
    fecha_hora: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    anulado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    motivo_anulacion: Mapped[str | None] = mapped_column(String(200))
    anulado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    anulado_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
