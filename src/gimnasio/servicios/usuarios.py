"""Gestión de usuarios del personal (RF-A3). Solo administradores. No se eliminan."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import Usuario, ahora_utc
from gimnasio.servicios import auditoria, claves
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import ROL_ADMIN, ROLES, Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import a_usuario_actual, usuario_vigente

_PATRON_USUARIO = re.compile(r"^[a-z0-9._-]{3,40}$")


@dataclass(frozen=True)
class DatosUsuario:
    id: int
    nombre_completo: str
    usuario: str
    rol: str
    nombre_rol: str
    activo: bool
    bloqueado_hasta: datetime | None
    ultimo_login: datetime | None
    debe_cambiar_clave: bool


def _a_datos(u: Usuario) -> DatosUsuario:
    return DatosUsuario(
        id=u.id, nombre_completo=u.nombre_completo, usuario=u.usuario, rol=u.rol,
        nombre_rol=ROLES.get(u.rol, u.rol), activo=u.activo, bloqueado_hasta=u.bloqueado_hasta,
        ultimo_login=u.ultimo_login, debe_cambiar_clave=u.debe_cambiar_clave,
    )


def _validar_nombre(nombre: str) -> str:
    nombre = " ".join((nombre or "").split())
    if len(nombre) < 3:
        raise ErrorValidacion("Escriba el nombre completo (mínimo 3 letras).")
    if len(nombre) > 120:
        raise ErrorValidacion("El nombre admite máximo 120 caracteres.")
    return nombre


def _validar_usuario(usuario: str) -> str:
    usuario = (usuario or "").strip().lower()
    if not _PATRON_USUARIO.match(usuario):
        raise ErrorValidacion(
            "El usuario debe tener de 3 a 40 caracteres: letras minúsculas sin tildes, "
            "números, punto, guion o guion bajo."
        )
    return usuario


def _validar_rol(rol: str) -> str:
    if rol not in ROLES:
        raise ErrorValidacion("Seleccione un rol válido.")
    return rol


class ServicioUsuarios:
    def __init__(self, fabrica: sessionmaker[Session], reloj=ahora_utc):
        self._fabrica = fabrica
        self._reloj = reloj

    # --- primer arranque -----------------------------------------------------
    def hay_usuarios(self) -> bool:
        with self._fabrica() as sesion:
            return sesion.scalar(select(func.count(Usuario.id))) > 0

    def crear_primer_administrador(
        self, nombre_completo: str, usuario: str, clave: str
    ) -> UsuarioActual:
        """Solo funciona con la base vacía de usuarios (primer arranque)."""
        nombre_completo = _validar_nombre(nombre_completo)
        usuario = _validar_usuario(usuario)
        claves.validar_clave(clave)
        with self._fabrica() as sesion:
            if sesion.scalar(select(func.count(Usuario.id))) > 0:
                raise ErrorValidacion("Ya existen usuarios: inicie sesión con un administrador.")
            nuevo = Usuario(
                nombre_completo=nombre_completo, usuario=usuario,
                hash_clave=claves.generar_hash(clave), rol=ROL_ADMIN, activo=True,
                creado_en=self._reloj(),
            )
            sesion.add(nuevo)
            sesion.flush()
            auditoria.registrar(
                sesion, "usuario_creado", "usuarios", usuario_id=nuevo.id, entidad_id=nuevo.id,
                detalle={"usuario": usuario, "rol": ROL_ADMIN, "primer_arranque": True},
                momento=self._reloj(),
            )
            sesion.commit()
            return a_usuario_actual(nuevo)

    # --- administración ----------------------------------------------------
    def listar(self, actual: UsuarioActual, incluir_inactivos: bool = True) -> list[DatosUsuario]:
        exigir(actual, Permiso.USUARIOS)
        consulta = select(Usuario).order_by(Usuario.activo.desc(), Usuario.nombre_completo)
        if not incluir_inactivos:
            consulta = consulta.where(Usuario.activo.is_(True))
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            return [_a_datos(u) for u in sesion.scalars(consulta)]

    def crear(
        self, actual: UsuarioActual, nombre_completo: str, usuario: str, rol: str, clave: str
    ) -> DatosUsuario:
        exigir(actual, Permiso.USUARIOS)
        nombre_completo = _validar_nombre(nombre_completo)
        usuario = _validar_usuario(usuario)
        rol = _validar_rol(rol)
        claves.validar_clave(clave)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            self._exigir_usuario_libre(sesion, usuario)
            nuevo = Usuario(
                nombre_completo=nombre_completo, usuario=usuario, rol=rol, activo=True,
                hash_clave=claves.generar_hash(clave), debe_cambiar_clave=True,
                creado_en=self._reloj(),
            )
            sesion.add(nuevo)
            sesion.flush()
            auditoria.registrar(
                sesion, "usuario_creado", "usuarios", usuario_id=actual.id,
                entidad_id=nuevo.id, detalle={"usuario": usuario, "rol": rol},
                momento=self._reloj(),
            )
            sesion.commit()
            return _a_datos(nuevo)

    def editar(
        self, actual: UsuarioActual, usuario_id: int, *, nombre_completo: str,
        usuario: str, rol: str,
    ) -> DatosUsuario:
        exigir(actual, Permiso.USUARIOS)
        nombre_completo = _validar_nombre(nombre_completo)
        usuario = _validar_usuario(usuario)
        rol = _validar_rol(rol)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            objetivo = self._obtener(sesion, usuario_id)
            if usuario != objetivo.usuario:
                self._exigir_usuario_libre(sesion, usuario)
            if objetivo.rol == ROL_ADMIN and rol != ROL_ADMIN and objetivo.activo:
                if objetivo.id == actual.id:
                    raise ErrorValidacion("No puede quitarse a sí mismo el rol de administrador.")
                self._exigir_otro_admin(sesion, objetivo.id)
            cambios = {}
            for campo, nuevo in (
                ("nombre_completo", nombre_completo), ("usuario", usuario), ("rol", rol)
            ):
                anterior = getattr(objetivo, campo)
                if anterior != nuevo:
                    cambios[campo] = {"antes": anterior, "despues": nuevo}
                    setattr(objetivo, campo, nuevo)
            if cambios:
                auditoria.registrar(
                    sesion, "usuario_editado", "usuarios", usuario_id=actual.id,
                    entidad_id=objetivo.id, detalle=cambios,
                    momento=self._reloj(),
                )
                sesion.commit()
            return _a_datos(objetivo)

    def desactivar(self, actual: UsuarioActual, usuario_id: int) -> DatosUsuario:
        exigir(actual, Permiso.USUARIOS)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            objetivo = self._obtener(sesion, usuario_id)
            if not objetivo.activo:
                return _a_datos(objetivo)
            if objetivo.id == actual.id:
                raise ErrorValidacion("No puede desactivar su propio usuario.")
            if objetivo.rol == ROL_ADMIN:
                self._exigir_otro_admin(sesion, objetivo.id)
            objetivo.activo = False
            auditoria.registrar(
                sesion, "usuario_desactivado", "usuarios", usuario_id=actual.id,
                entidad_id=objetivo.id, detalle={"usuario": objetivo.usuario},
                momento=self._reloj(),
            )
            sesion.commit()
            return _a_datos(objetivo)

    def activar(self, actual: UsuarioActual, usuario_id: int) -> DatosUsuario:
        exigir(actual, Permiso.USUARIOS)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            objetivo = self._obtener(sesion, usuario_id)
            if objetivo.activo:
                return _a_datos(objetivo)
            objetivo.activo = True
            objetivo.intentos_fallidos = 0
            objetivo.bloqueado_hasta = None
            auditoria.registrar(
                sesion, "usuario_activado", "usuarios", usuario_id=actual.id,
                entidad_id=objetivo.id, detalle={"usuario": objetivo.usuario},
                momento=self._reloj(),
            )
            sesion.commit()
            return _a_datos(objetivo)

    def restablecer_clave(
        self, actual: UsuarioActual, usuario_id: int, clave_temporal: str
    ) -> DatosUsuario:
        """Asigna una clave temporal, quita el bloqueo y obliga a cambiarla al entrar."""
        exigir(actual, Permiso.USUARIOS)
        claves.validar_clave(clave_temporal)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            objetivo = self._obtener(sesion, usuario_id)
            objetivo.hash_clave = claves.generar_hash(clave_temporal)
            objetivo.debe_cambiar_clave = True
            objetivo.intentos_fallidos = 0
            objetivo.bloqueado_hasta = None
            auditoria.registrar(
                sesion, "clave_restablecida", "usuarios", usuario_id=actual.id,
                entidad_id=objetivo.id, detalle={"usuario": objetivo.usuario},
                momento=self._reloj(),
            )
            sesion.commit()
            return _a_datos(objetivo)

    # --- auxiliares ----------------------------------------------------------
    @staticmethod
    def _obtener(sesion: Session, usuario_id: int) -> Usuario:
        objetivo = sesion.get(Usuario, usuario_id)
        if objetivo is None:
            raise ErrorValidacion("El usuario no existe.")
        return objetivo

    @staticmethod
    def _exigir_usuario_libre(sesion: Session, usuario: str) -> None:
        existe = sesion.scalar(select(Usuario.id).where(func.lower(Usuario.usuario) == usuario))
        if existe:
            raise ErrorValidacion(f"Ya existe un usuario «{usuario}».")

    @staticmethod
    def _exigir_otro_admin(sesion: Session, excepto_id: int) -> None:
        otros = sesion.scalar(
            select(func.count(Usuario.id)).where(
                Usuario.rol == ROL_ADMIN, Usuario.activo.is_(True), Usuario.id != excepto_id
            )
        )
        if not otros:
            raise ErrorValidacion("Debe quedar al menos un administrador activo.")
