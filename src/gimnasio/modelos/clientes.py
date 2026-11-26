from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Cliente(Base):
    """Cliente del gimnasio. Se identifica con su código de 6 dígitos (o su QR).

    La vigencia (vigente / por vencer / vencida / sin membresía) NO se guarda:
    se calcula desde las membresías. `estado` es solo el estado administrativo.
    """

    __tablename__ = "clientes"
    __table_args__ = (
        CheckConstraint(
            "codigo GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'", name="codigo_6_digitos"
        ),
        CheckConstraint("sexo IN ('M','F','O')", name="sexo"),
        CheckConstraint("estado IN ('activo','inactivo')", name="estado"),
        Index("ix_clientes_codigo", "codigo", unique=True),
        Index("ix_clientes_qr_token", "qr_token", unique=True),
        Index("ix_clientes_documento", "documento", unique=True),
        Index("ix_clientes_apellidos_nombres", "apellidos", "nombres"),
        Index("ix_clientes_estado", "estado"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(6))
    qr_token: Mapped[str] = mapped_column(String(64))
    tipo_documento: Mapped[str] = mapped_column(String(10))
    documento: Mapped[str] = mapped_column(String(20))
    nombres: Mapped[str] = mapped_column(String(80))
    apellidos: Mapped[str] = mapped_column(String(80))
    sexo: Mapped[str] = mapped_column(String(1))
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)
    direccion: Mapped[str | None] = mapped_column(String(200))
    foto_ruta: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[str] = mapped_column(String(8), default="activo", server_default="activo")
    notas: Mapped[str | None] = mapped_column(Text)
    autoriza_datos_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    autoriza_biometria_en: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
    actualizado_en: Mapped[datetime] = mapped_column(
        FechaHoraUTC, default=ahora_utc, onupdate=ahora_utc
    )
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    contactos: Mapped[list[Contacto]] = relationship(back_populates="cliente")


class Contacto(Base):
    """Teléfonos, correos y contactos de emergencia (varios por cliente)."""

    __tablename__ = "contactos"
    __table_args__ = (
        CheckConstraint("tipo IN ('telefono','email','emergencia')", name="tipo"),
        Index("ix_contactos_valor", "valor"),
        Index("ix_contactos_cliente_id", "cliente_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    tipo: Mapped[str] = mapped_column(String(10))
    valor: Mapped[str] = mapped_column(String(120))
    nombre_contacto: Mapped[str | None] = mapped_column(String(120))
    principal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    cliente: Mapped[Cliente] = relationship(back_populates="contactos")
