"""Arma todos los servicios sobre una misma fábrica de sesiones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import ahora_utc
from gimnasio.servicios.auditoria import ServicioAuditoria
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.sesion import Reloj, ServicioSesion
from gimnasio.servicios.usuarios import ServicioUsuarios


@dataclass
class Servicios:
    configuracion: ServicioConfiguracion
    sesion: ServicioSesion
    usuarios: ServicioUsuarios
    auditoria: ServicioAuditoria


def crear_servicios(
    fabrica: sessionmaker[Session], carpeta_datos: Path | None = None, reloj: Reloj = ahora_utc
) -> Servicios:
    configuracion = ServicioConfiguracion(fabrica, carpeta_datos)
    return Servicios(
        configuracion=configuracion,
        sesion=ServicioSesion(fabrica, configuracion, reloj),
        usuarios=ServicioUsuarios(fabrica),
        auditoria=ServicioAuditoria(fabrica),
    )
