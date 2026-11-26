from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from gimnasio.modelos.base import Base, FechaHoraUTC, ahora_utc


class Usuario(Base):
    """Personal del gimnasio que inicia sesión. No se elimina: se desactiva."""

    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("rol IN ('admin','recepcion')", name="rol"),
        CheckConstraint("intentos_fallidos >= 0", name="intentos_fallidos"),
        Index("ix_usuarios_usuario", "usuario", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nombre_completo: Mapped[str] = mapped_column(String(120))
    usuario: Mapped[str] = mapped_column(String(40))
    hash_clave: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(10))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    intentos_fallidos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    ultimo_login: Mapped[datetime | None] = mapped_column(FechaHoraUTC)
    # Tras un restablecimiento hecho por el administrador, el usuario debe cambiarla al entrar.
    debe_cambiar_clave: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    creado_en: Mapped[datetime] = mapped_column(FechaHoraUTC, default=ahora_utc)
