"""Inicio y cierre de sesión, bloqueo por intentos fallidos e inactividad (RF-A1, RF-A2)."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import Usuario, ahora_utc
from gimnasio.servicios import auditoria, claves
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorPermiso, UsuarioBloqueado
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual

Reloj = Callable[[], datetime]
MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos."


def a_usuario_actual(usuario: Usuario) -> UsuarioActual:
    return UsuarioActual(
        id=usuario.id,
        usuario=usuario.usuario,
        nombre_completo=usuario.nombre_completo,
        rol=usuario.rol,
        debe_cambiar_clave=usuario.debe_cambiar_clave,
    )


def usuario_vigente(sesion: Session, actual: UsuarioActual | None) -> Usuario:
    """Vuelve a leer el usuario de la base: si lo desactivaron o le cambiaron el rol
    mientras tenía la sesión abierta, sus permisos se actualizan de inmediato."""
    if actual is None:
        raise ErrorPermiso("Debe iniciar sesión para realizar esta acción.")
    usuario = sesion.get(Usuario, actual.id)
    if usuario is None or not usuario.activo:
        raise ErrorPermiso("Su usuario fue desactivado. Cierre la sesión.")
    if usuario.rol != actual.rol:
        raise ErrorPermiso("Su rol cambió. Cierre la sesión y vuelva a entrar.")
    return usuario


class ServicioSesion:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._config = configuracion
        self._reloj = reloj

    def iniciar_sesion(self, nombre_usuario: str, clave: str) -> UsuarioActual:
        nombre = (nombre_usuario or "").strip().lower()
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario = sesion.scalar(select(Usuario).where(func.lower(Usuario.usuario) == nombre))
            if usuario is None:
                claves.verificar(None, clave)  # mismo tiempo de respuesta
                auditoria.registrar(
                    sesion, "login_fallido", "usuarios", momento=ahora,
                    detalle={"usuario_digitado": nombre[:40], "motivo": "no existe"},
                )
                sesion.commit()
                raise ErrorAutenticacion(MENSAJE_CREDENCIALES)

            if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
                restante = (usuario.bloqueado_hasta - ahora).total_seconds() / 60
                raise UsuarioBloqueado(max(1, math.ceil(restante)))

            if not claves.verificar(usuario.hash_clave, clave):
                self._registrar_fallo(sesion, usuario, ahora)
                sesion.commit()
                if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
                    raise UsuarioBloqueado(self._config.obtener("minutos_bloqueo"))
                raise ErrorAutenticacion(MENSAJE_CREDENCIALES)

            if not usuario.activo:
                auditoria.registrar(
                    sesion, "login_fallido", "usuarios", usuario_id=usuario.id,
                    entidad_id=usuario.id, momento=ahora, detalle={"motivo": "desactivado"},
                )
                sesion.commit()
                raise ErrorAutenticacion(
                    "Este usuario está desactivado. Consulte con el administrador."
                )

            usuario.intentos_fallidos = 0
            usuario.bloqueado_hasta = None
            usuario.ultimo_login = ahora
            if claves.necesita_rehash(usuario.hash_clave):
                usuario.hash_clave = claves.generar_hash(clave)
            auditoria.registrar(
                sesion, "login_exitoso", "usuarios", usuario_id=usuario.id,
                entidad_id=usuario.id, momento=ahora,
            )
            sesion.commit()
            return a_usuario_actual(usuario)

    def verificar_administrador(self, nombre_usuario: str, clave: str, motivo: str) -> UsuarioActual:
        """Confirma usuario y contraseña de un administrador activo sin abrir sesión
        (p. ej. "Ingreso autorizado" en Recepción). Los fallos cuentan para el bloqueo
        igual que en el inicio de sesión y quedan en la auditoría."""
        nombre = (nombre_usuario or "").strip().lower()
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario = sesion.scalar(select(Usuario).where(func.lower(Usuario.usuario) == nombre))
            if usuario is None:
                claves.verificar(None, clave)
                auditoria.registrar(
                    sesion, "autorizacion_fallida", "usuarios", momento=ahora,
                    detalle={"usuario_digitado": nombre[:40], "motivo": "no existe",
                             "para": motivo},
                )
                sesion.commit()
                raise ErrorAutenticacion(MENSAJE_CREDENCIALES)
            if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
                restante = (usuario.bloqueado_hasta - ahora).total_seconds() / 60
                raise UsuarioBloqueado(max(1, math.ceil(restante)))
            if not claves.verificar(usuario.hash_clave, clave):
                self._registrar_fallo(sesion, usuario, ahora, accion="autorizacion_fallida")
                sesion.commit()
                if usuario.bloqueado_hasta and usuario.bloqueado_hasta > ahora:
                    raise UsuarioBloqueado(self._config.obtener("minutos_bloqueo"))
                raise ErrorAutenticacion(MENSAJE_CREDENCIALES)
            if not usuario.activo or usuario.rol != ROL_ADMIN:
                auditoria.registrar(
                    sesion, "autorizacion_fallida", "usuarios", usuario_id=usuario.id,
                    entidad_id=usuario.id, momento=ahora,
                    detalle={"motivo": "no es administrador activo", "para": motivo},
                )
                sesion.commit()
                raise ErrorPermiso("Solo un administrador activo puede autorizar el ingreso.")
            usuario.intentos_fallidos = 0
            sesion.commit()
            return a_usuario_actual(usuario)

    def _registrar_fallo(self, sesion: Session, usuario: Usuario, ahora: datetime,
                         accion: str = "login_fallido") -> None:
        maximo = self._config.obtener("intentos_login_max", sesion)
        usuario.intentos_fallidos += 1
        auditoria.registrar(
            sesion, accion, "usuarios", usuario_id=usuario.id,
            entidad_id=usuario.id, momento=ahora,
            detalle={"motivo": "clave incorrecta", "intento": usuario.intentos_fallidos},
        )
        if usuario.intentos_fallidos >= maximo:
            minutos = self._config.obtener("minutos_bloqueo", sesion)
            usuario.bloqueado_hasta = ahora + timedelta(minutes=minutos)
            usuario.intentos_fallidos = 0
            auditoria.registrar(
                sesion, "usuario_bloqueado", "usuarios", usuario_id=usuario.id,
                entidad_id=usuario.id, momento=ahora, detalle={"minutos": minutos},
            )

    def cerrar_sesion(self, actual: UsuarioActual, por_inactividad: bool = False) -> None:
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "cierre_por_inactividad" if por_inactividad else "logout", "usuarios",
                usuario_id=actual.id, entidad_id=actual.id, momento=self._reloj(),
            )
            sesion.commit()

    def cambiar_clave_propia(
        self, actual: UsuarioActual, clave_actual: str, clave_nueva: str
    ) -> UsuarioActual:
        claves.validar_clave(clave_nueva)
        with self._fabrica() as sesion:
            usuario = usuario_vigente(sesion, actual)
            if not claves.verificar(usuario.hash_clave, clave_actual):
                raise ErrorAutenticacion("La contraseña actual no es correcta.")
            if claves.verificar(usuario.hash_clave, clave_nueva):
                raise ErrorAutenticacion("La nueva contraseña debe ser distinta de la actual.")
            usuario.hash_clave = claves.generar_hash(clave_nueva)
            usuario.debe_cambiar_clave = False
            auditoria.registrar(
                sesion, "clave_cambiada", "usuarios", usuario_id=actual.id,
                entidad_id=actual.id, momento=self._reloj(),
            )
            sesion.commit()
            return a_usuario_actual(usuario)


class ControlInactividad:
    """Lleva la cuenta del tiempo sin uso. La interfaz llama a `registrar_actividad()`
    con cada tecla o clic y consulta `vencido()` periódicamente."""

    def __init__(self, minutos: int, reloj: Reloj = ahora_utc):
        self._reloj = reloj
        self.minutos = minutos
        self._ultima = reloj()

    def registrar_actividad(self) -> None:
        self._ultima = self._reloj()

    def segundos_inactivo(self) -> float:
        return (self._reloj() - self._ultima).total_seconds()

    def vencido(self, en_recepcion: bool = False) -> bool:
        """En Recepción nunca vence: esa pantalla permanece abierta (RF-A2)."""
        if en_recepcion:
            return False
        return self.segundos_inactivo() >= self.minutos * 60
