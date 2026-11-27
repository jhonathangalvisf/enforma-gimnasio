"""Autorización de un administrador para que Recepción cobre o inscriba.

Regla del dueño: el módulo Pagos, registrar cualquier pago (mensualidad, saldo antiguo,
casillero u otro) e inscribir un cliente nuevo necesitan la contraseña de un
administrador **cada vez**. Si quien trabaja es administrador no se le pide nada.

Cómo funciona:
1. La pantalla pide usuario y contraseña de un administrador y llama a `autorizar`.
   Se comprueban con `ServicioSesion.verificar_administrador` (los fallos cuentan
   para el bloqueo) y queda en la auditoría.
2. `autorizar` devuelve una `Autorizacion` (un número aleatorio) que solo vive en la
   memoria del programa, vence pronto y se puede usar un número limitado de veces:
   - "pago": un cobro.
   - "inscripcion": inscribir al cliente y su primer cobro (2 usos).
   - "activacion": activar a un cliente inactivo desde Recepción y cobrarle la
     mensualidad (2 usos).
   - "modulo_pagos": ver la caja y consultar pagos mientras la pantalla esté abierta.
3. También el módulo Clientes (datos confidenciales) pide la clave cada vez que se entra,
   al administrador incluido ("modulo_clientes": la lista y los contadores mientras la
   pantalla esté abierta). La búsqueda Ctrl+K de la barra superior también la pide.
4. Cada servicio protegido llama a `verificar` antes de guardar y a `gastar` después
   de confirmar la transacción: si la operación falla (p. ej. falta la referencia)
   la autorización sigue sirviendo y no hay que volver a pedir la clave.

Así la regla no depende de esconder botones: sin autorización válida el servicio
rechaza la operación de Recepción.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import ahora_utc
from gimnasio.servicios import auditoria
from gimnasio.servicios.errores import ErrorPermiso
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual
from gimnasio.servicios.sesion import Reloj, ServicioSesion, usuario_vigente

PARA_MODULO_CLIENTES = "modulo_clientes"
PARA_PAGO = "pago"
PARA_INSCRIPCION = "inscripcion"
PARA_MODULO_PAGOS = "modulo_pagos"
PARA_ACTIVACION = "activacion"
DESCRIPCIONES = {
    PARA_MODULO_CLIENTES: "abrir el módulo de Clientes",
    PARA_PAGO: "registrar un pago",
    PARA_INSCRIPCION: "inscribir un cliente nuevo",
    PARA_MODULO_PAGOS: "abrir el módulo de Pagos",
    PARA_ACTIVACION: "activar un cliente inactivo y cobrarle la mensualidad",
}
# (duración, usos; None = sin límite de usos mientras no venza ni se revoque)
_REGLAS: dict[str, tuple[timedelta, int | None]] = {
    PARA_MODULO_CLIENTES: (timedelta(hours=12), None),
    PARA_PAGO: (timedelta(minutes=10), 1),
    PARA_INSCRIPCION: (timedelta(minutes=20), 2),
    PARA_MODULO_PAGOS: (timedelta(hours=12), None),
    PARA_ACTIVACION: (timedelta(minutes=20), 2),
}


class ErrorAutorizacion(ErrorPermiso):
    """Falta la autorización de un administrador (o ya se usó o venció)."""


@dataclass(frozen=True)
class Autorizacion:
    token: str
    para: str
    admin: UsuarioActual


@dataclass
class _Vigente:
    autorizacion: Autorizacion
    solicitante_id: int
    vence: datetime
    usos: int | None


def necesita_autorizacion(actual: UsuarioActual) -> bool:
    """Solo Recepción la necesita: el administrador ya tiene la clave."""
    return actual is not None and actual.rol != ROL_ADMIN


class ServicioAutorizaciones:
    def __init__(self, fabrica: sessionmaker[Session], sesiones: ServicioSesion,
                 reloj: Reloj = ahora_utc):
        self._fabrica = fabrica
        self._sesiones = sesiones
        self._reloj = reloj
        self._vigentes: dict[str, _Vigente] = {}

    def autorizar(self, actual: UsuarioActual, usuario_admin: str, clave_admin: str,
                  para: str) -> Autorizacion:
        if para not in _REGLAS:
            raise ValueError(f"Autorización desconocida: {para}")
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
        admin = self._sesiones.verificar_administrador(
            usuario_admin, clave_admin, DESCRIPCIONES[para])
        ahora = self._reloj()
        duracion, usos = _REGLAS[para]
        autorizacion = Autorizacion(secrets.token_urlsafe(16), para, admin)
        self._limpiar(ahora)
        self._vigentes[autorizacion.token] = _Vigente(autorizacion, actual.id, ahora + duracion,
                                                      usos)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "autorizacion_admin", "usuarios", usuario_id=admin.id,
                entidad_id=admin.id, momento=ahora,
                detalle={"para": DESCRIPCIONES[para], "solicitado_por": actual.usuario},
            )
            sesion.commit()
        return autorizacion

    def verificar(self, actual: UsuarioActual, autorizacion: Autorizacion | None,
                  *paras: str) -> UsuarioActual | None:
        """Devuelve el administrador que autorizó, o None si `actual` es administrador.
        No gasta la autorización (ver `gastar`)."""
        if not necesita_autorizacion(actual):
            return None
        que = DESCRIPCIONES[paras[0]]
        vigente = self._vigentes.get(autorizacion.token) if autorizacion else None
        if (vigente is None or vigente.autorizacion.para not in paras
                or vigente.solicitante_id != actual.id):
            raise ErrorAutorizacion(
                f"Para {que} se necesita la contraseña de un administrador.")
        if vigente.vence <= self._reloj():
            self._vigentes.pop(autorizacion.token, None)
            raise ErrorAutorizacion(
                f"La autorización del administrador venció. Pídala de nuevo para {que}.")
        return vigente.autorizacion.admin

    def gastar(self, autorizacion: Autorizacion | None) -> None:
        """Cuenta un uso (después de que la operación quedó guardada)."""
        vigente = self._vigentes.get(autorizacion.token) if autorizacion else None
        if vigente is None or vigente.usos is None:
            return
        vigente.usos -= 1
        if vigente.usos <= 0:
            self._vigentes.pop(autorizacion.token, None)

    def revocar(self, autorizacion: Autorizacion | None) -> None:
        if autorizacion is not None:
            self._vigentes.pop(autorizacion.token, None)

    def _limpiar(self, ahora: datetime) -> None:
        for token in [t for t, v in self._vigentes.items() if v.vence <= ahora]:
            del self._vigentes[token]


def registrar_uso(sesion: Session, actual: UsuarioActual, admin: UsuarioActual | None,
                  operacion: str, momento: datetime, **detalle) -> None:
    """Deja en la auditoría (en la misma transacción de la operación) qué administrador
    autorizó lo que hizo Recepción. Si `admin` es None (lo hizo un administrador) no
    se escribe nada: la operación ya queda a su nombre."""
    if admin is None:
        return
    auditoria.registrar(
        sesion, "operacion_autorizada", "usuarios", usuario_id=actual.id, entidad_id=admin.id,
        momento=momento,
        detalle={"operacion": operacion, "autorizado_por": admin.usuario, **detalle},
    )
