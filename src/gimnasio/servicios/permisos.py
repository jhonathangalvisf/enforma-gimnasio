"""Permisos por rol (sección 2 de la especificación).

Cada servicio llama a `exigir()` antes de actuar. Ocultar botones en la interfaz
es solo comodidad: la verificación real ocurre aquí.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from gimnasio.servicios.errores import ErrorPermiso

ROL_ADMIN = "admin"
ROL_RECEPCION = "recepcion"
ROLES = {ROL_ADMIN: "Administrador", ROL_RECEPCION: "Recepción"}


class Permiso(str, Enum):
    REGISTRAR_ASISTENCIA = "registrar_asistencia"
    VER_CLIENTES = "ver_clientes"
    REGISTRAR_CLIENTES = "registrar_clientes"
    MODIFICAR_CONTACTO_CLIENTE = "modificar_contacto_cliente"
    MODIFICAR_CLIENTE_COMPLETO = "modificar_cliente_completo"
    ACTIVAR_CLIENTES = "activar_clientes"
    REGISTRAR_PAGOS = "registrar_pagos"
    ANULAR_PAGOS = "anular_pagos"
    ELIMINAR_ASISTENCIA_DEL_DIA = "eliminar_asistencia_del_dia"
    ELIMINAR_ASISTENCIA_CUALQUIERA = "eliminar_asistencia_cualquiera"
    ASIGNAR_CASILLERO = "asignar_casillero"
    LIBERAR_CASILLERO = "liberar_casillero"
    REGISTRAR_INVITADOS = "registrar_invitados"
    REPORTES_BASICOS = "reportes_basicos"
    REPORTES_TODOS = "reportes_todos"
    ADMINISTRAR_CATALOGOS = "administrar_catalogos"  # planes, precios, casilleros
    CONFIGURACION = "configuracion"
    USUARIOS = "usuarios"
    AUDITORIA = "auditoria"
    BACKUPS = "backups"
    AYUDA = "ayuda"


_RECEPCION = frozenset({
    Permiso.REGISTRAR_ASISTENCIA,
    Permiso.VER_CLIENTES,
    Permiso.REGISTRAR_CLIENTES,
    Permiso.MODIFICAR_CONTACTO_CLIENTE,
    Permiso.REGISTRAR_PAGOS,
    Permiso.ELIMINAR_ASISTENCIA_DEL_DIA,
    Permiso.ASIGNAR_CASILLERO,
    Permiso.LIBERAR_CASILLERO,
    Permiso.REGISTRAR_INVITADOS,
    Permiso.REPORTES_BASICOS,
    Permiso.AYUDA,
})

PERMISOS_POR_ROL: dict[str, frozenset[Permiso]] = {
    ROL_RECEPCION: _RECEPCION,
    ROL_ADMIN: frozenset(Permiso),
}


@dataclass(frozen=True)
class UsuarioActual:
    """Quién tiene la sesión abierta. Lo crea el servicio de sesión al iniciar."""

    id: int
    usuario: str
    nombre_completo: str
    rol: str
    debe_cambiar_clave: bool = False

    @property
    def es_admin(self) -> bool:
        return self.rol == ROL_ADMIN

    @property
    def nombre_rol(self) -> str:
        return ROLES.get(self.rol, self.rol)

    def puede(self, permiso: Permiso) -> bool:
        return tiene_permiso(self.rol, permiso)


def tiene_permiso(rol: str, permiso: Permiso) -> bool:
    return permiso in PERMISOS_POR_ROL.get(rol, frozenset())


def exigir(actual: UsuarioActual | None, permiso: Permiso) -> None:
    """Lanza ErrorPermiso si no hay sesión o el rol no tiene el permiso."""
    if actual is None:
        raise ErrorPermiso("Debe iniciar sesión para realizar esta acción.")
    if not tiene_permiso(actual.rol, permiso):
        raise ErrorPermiso("No tiene permiso para realizar esta acción.")
