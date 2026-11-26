"""Registro y consulta de la auditoría de acciones sensibles (sección 5.1 y 7).

Nunca se guardan contraseñas ni hashes en el detalle. Para clientes, más adelante,
solo se registran los campos cambiados (no copias completas de datos personales).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio.config import ZONA_HORARIA
from gimnasio.modelos import Auditoria, Usuario, ahora_utc
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir

# Acciones conocidas y su descripción para el visor.
ACCIONES = {
    "login_exitoso": "Inicio de sesión",
    "login_fallido": "Intento fallido de inicio de sesión",
    "usuario_bloqueado": "Usuario bloqueado por intentos fallidos",
    "logout": "Cierre de sesión",
    "cierre_por_inactividad": "Cierre de sesión por inactividad",
    "usuario_creado": "Usuario creado",
    "usuario_editado": "Usuario editado",
    "usuario_desactivado": "Usuario desactivado",
    "usuario_activado": "Usuario activado",
    "clave_restablecida": "Contraseña restablecida por el administrador",
    "clave_cambiada": "Contraseña cambiada por el usuario",
    "configuracion_cambiada": "Configuración cambiada",
    "cliente_registrado": "Cliente registrado",
    "cliente_modificado": "Cliente modificado",
    "cliente_foto_cambiada": "Foto de cliente cambiada",
    "cliente_inactivado": "Cliente inactivado",
    "cliente_activado": "Cliente activado",
    "casillero_creado": "Casillero creado",
    "casilleros_creados": "Casilleros creados en lote",
    "casillero_editado": "Casillero editado",
    "casillero_mantenimiento": "Casillero en mantenimiento",
    "casillero_habilitado": "Casillero habilitado tras mantenimiento",
    "casillero_asignado": "Casillero asignado",
    "casillero_renovado": "Casillero renovado",
    "casillero_vencimiento_corregido": "Vencimiento de casillero corregido",
    "casillero_trasladado": "Cliente cambiado de casillero",
    "casillero_liberado": "Casillero liberado",
    "casilleros_exportados": "Lista de casilleros exportada",
    "clientes_exportados": "Lista de clientes exportada",
    "plan_creado": "Plan creado",
    "plan_editado": "Plan editado",
    "plan_activado": "Plan activado",
    "plan_desactivado": "Plan desactivado",
    "planes_ejemplo_creados": "Planes de ejemplo creados",
    "membresia_registrada": "Membresía registrada",
    "membresia_anulada": "Membresía anulada",
    "pago_registrado": "Pago registrado",
    "pago_anulado": "Pago anulado",
    "recibo_generado": "Recibo generado o reimpreso",
    "autorizacion_fallida": "Autorización de administrador fallida",
    "ingreso_autorizado": "Ingreso autorizado por el administrador",
    "ingreso_tras_renovar": "Ingreso permitido tras renovar en Recepción",
    "asistencia_eliminada": "Asistencia eliminada",
    "alerta_creada": "Alerta creada",
    "alerta_resuelta": "Alerta resuelta",
    "asistencias_exportadas": "Reporte de asistencia exportado",
    "invitado_registrado": "Invitado registrado",
    "invitado_modificado": "Invitado modificado",
    "invitado_visita_autorizada": "Visita de invitado autorizada por encima del límite",
    "invitado_visita_eliminada": "Visita de invitado eliminada",
    "invitados_exportados": "Reporte de invitados exportado",
    "backup_creado": "Copia de seguridad creada",
    "backup_fallido": "Copia de seguridad fallida",
    "backup_restaurado": "Copia de seguridad restaurada",
    "backup_copiado_externo": "Copia llevada a otro disco",
    "backup_clave_configurada": "Contraseña de copias configurada",
    "backup_clave_cambiada": "Contraseña de copias cambiada",
}

_CAMPOS_PROHIBIDOS = {"clave", "hash_clave", "contrasena", "password"}
LIMITE_CONSULTA = 1000


def registrar(
    sesion: Session,
    accion: str,
    entidad: str,
    *,
    usuario_id: int | None = None,
    entidad_id: int | None = None,
    detalle: dict | None = None,
    momento: datetime | None = None,
) -> Auditoria:
    """Agrega un registro a la sesión actual. Se guarda con el mismo commit de la acción."""
    limpio = None
    if detalle:
        limpio = {k: v for k, v in detalle.items() if k.lower() not in _CAMPOS_PROHIBIDOS}
    registro = Auditoria(
        fecha_hora=momento or ahora_utc(),
        usuario_id=usuario_id,
        accion=accion,
        entidad=entidad,
        entidad_id=entidad_id,
        detalle_json=json.dumps(limpio, ensure_ascii=False, default=str) if limpio else None,
    )
    sesion.add(registro)
    return registro


@dataclass(frozen=True)
class FilaAuditoria:
    id: int
    fecha_hora: datetime  # UTC
    usuario: str
    accion: str
    descripcion: str
    entidad: str
    entidad_id: int | None
    detalle: str


def inicio_dia_utc(dia: date) -> datetime:
    """Medianoche de Bogotá de ese día, expresada en UTC."""
    return datetime.combine(dia, time.min, tzinfo=ZONA_HORARIA).astimezone(
        ahora_utc().tzinfo
    )


class ServicioAuditoria:
    def __init__(self, fabrica: sessionmaker[Session]):
        self._fabrica = fabrica

    def consultar(
        self,
        actual: UsuarioActual,
        *,
        desde: date | None = None,
        hasta: date | None = None,
        usuario_id: int | None = None,
        accion: str | None = None,
        texto: str | None = None,
        limite: int = LIMITE_CONSULTA,
    ) -> list[FilaAuditoria]:
        """Fechas `desde`/`hasta` en días de Bogotá, ambos incluidos. Más reciente primero."""
        exigir(actual, Permiso.AUDITORIA)
        consulta = (
            select(Auditoria, Usuario.usuario)
            .outerjoin(Usuario, Usuario.id == Auditoria.usuario_id)
            .order_by(Auditoria.fecha_hora.desc(), Auditoria.id.desc())
            .limit(limite)
        )
        if desde:
            consulta = consulta.where(Auditoria.fecha_hora >= inicio_dia_utc(desde))
        if hasta:
            consulta = consulta.where(
                Auditoria.fecha_hora < inicio_dia_utc(hasta + timedelta(days=1))
            )
        if usuario_id:
            consulta = consulta.where(Auditoria.usuario_id == usuario_id)
        if accion:
            consulta = consulta.where(Auditoria.accion == accion)
        if texto:
            patron = f"%{texto.strip().lower()}%"
            consulta = consulta.where(
                func.lower(Auditoria.entidad).like(patron)
                | func.lower(func.coalesce(Auditoria.detalle_json, "")).like(patron)
            )
        with self._fabrica() as sesion:
            return [
                FilaAuditoria(
                    id=reg.id,
                    fecha_hora=reg.fecha_hora,
                    usuario=nombre or "—",
                    accion=reg.accion,
                    descripcion=ACCIONES.get(reg.accion, reg.accion),
                    entidad=reg.entidad,
                    entidad_id=reg.entidad_id,
                    detalle=_detalle_legible(reg.detalle_json),
                )
                for reg, nombre in sesion.execute(consulta)
            ]


def _detalle_legible(detalle_json: str | None) -> str:
    if not detalle_json:
        return ""
    try:
        datos = json.loads(detalle_json)
    except ValueError:
        return detalle_json
    if isinstance(datos, dict):
        return "; ".join(f"{k}: {_valor_legible(v)}" for k, v in datos.items())
    return str(datos)


def _valor_legible(valor) -> str:
    if isinstance(valor, dict) and set(valor) == {"antes", "despues"}:
        antes = valor["antes"] if valor["antes"] not in ("", None) else "(vacío)"
        despues = valor["despues"] if valor["despues"] not in ("", None) else "(vacío)"
        return f"{antes} → {despues}"
    return str(valor)
