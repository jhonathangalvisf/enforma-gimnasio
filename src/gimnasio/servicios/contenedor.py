"""Arma todos los servicios sobre una misma fábrica de sesiones."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import ahora_utc
from gimnasio.servicios.alertas import ServicioAlertas
from gimnasio.servicios.asistencia import ServicioAsistencia
from gimnasio.servicios.auditoria import ServicioAuditoria
from gimnasio.servicios.casilleros import ServicioCasilleros
from gimnasio.servicios.clientes import ServicioClientes
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.invitados import ServicioInvitados
from gimnasio.servicios.pagos import ServicioPagos
from gimnasio.servicios.planes import ServicioPlanes
from gimnasio.servicios.sesion import Reloj, ServicioSesion
from gimnasio.servicios.usuarios import ServicioUsuarios


@dataclass
class Servicios:
    configuracion: ServicioConfiguracion
    sesion: ServicioSesion
    usuarios: ServicioUsuarios
    auditoria: ServicioAuditoria
    clientes: ServicioClientes
    planes: ServicioPlanes
    pagos: ServicioPagos
    asistencia: ServicioAsistencia
    alertas: ServicioAlertas
    casilleros: ServicioCasilleros
    invitados: ServicioInvitados


def crear_servicios(
    fabrica: sessionmaker[Session], carpeta_datos: Path | None = None, reloj: Reloj = ahora_utc
) -> Servicios:
    configuracion = ServicioConfiguracion(fabrica, carpeta_datos)
    sesion = ServicioSesion(fabrica, configuracion, reloj)
    pagos = ServicioPagos(fabrica, configuracion, carpeta_datos, reloj)
    return Servicios(
        configuracion=configuracion,
        sesion=sesion,
        usuarios=ServicioUsuarios(fabrica, reloj),
        auditoria=ServicioAuditoria(fabrica),
        clientes=ServicioClientes(fabrica, configuracion, carpeta_datos, reloj),
        planes=ServicioPlanes(fabrica),
        pagos=pagos,
        asistencia=ServicioAsistencia(fabrica, configuracion, sesion, carpeta_datos, reloj),
        alertas=ServicioAlertas(fabrica, reloj),
        casilleros=ServicioCasilleros(fabrica, configuracion, pagos, carpeta_datos, reloj),
        invitados=ServicioInvitados(fabrica, configuracion, sesion, carpeta_datos, reloj),
    )
