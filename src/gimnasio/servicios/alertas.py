"""Alertas manuales (RF-R7): notas a un cliente que aparecen en Recepción al ingresar
hasta que se marcan como resueltas. Las crean el administrador o recepción.

Las alertas no se borran: se resuelven y quedan en la ficha y en la auditoría.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.modelos import Alerta, Cliente, ahora_utc
from gimnasio.servicios import auditoria
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente

NIVELES = {"info": "Información", "advertencia": "Advertencia", "critica": "Crítica"}
ORDEN_NIVEL = {"critica": 0, "advertencia": 1, "info": 2}
LARGO_MAXIMO = 300


@dataclass(frozen=True)
class AlertaActiva:
    id: int
    mensaje: str
    nivel: str
    fecha_inicio: date
    fecha_fin: date | None


def alertas_activas(sesion: Session, cliente_id: int, hoy: date) -> list[AlertaActiva]:
    """Alertas sin resolver cuya vigencia incluye hoy, las críticas primero."""
    filas = sesion.scalars(
        select(Alerta).where(
            Alerta.cliente_id == cliente_id,
            Alerta.activa.is_(True),
            Alerta.fecha_inicio <= hoy,
            or_(Alerta.fecha_fin.is_(None), Alerta.fecha_fin >= hoy),
        ).order_by(Alerta.creada_en.desc())
    ).all()
    return sorted(
        (AlertaActiva(a.id, a.mensaje, a.nivel, a.fecha_inicio, a.fecha_fin) for a in filas),
        key=lambda a: ORDEN_NIVEL.get(a.nivel, 9),
    )


class ServicioAlertas:
    def __init__(self, fabrica: sessionmaker[Session], reloj: Reloj = ahora_utc):
        self._fabrica = fabrica
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    def crear(
        self, actual: UsuarioActual, cliente_id: int, mensaje: str, nivel: str = "info",
        *, fecha_inicio: date | None = None, fecha_fin: date | None = None,
    ) -> int:
        exigir(actual, Permiso.GESTIONAR_ALERTAS)
        mensaje = " ".join((mensaje or "").split())
        if len(mensaje) < 3:
            raise ErrorValidacion("Escriba el mensaje de la alerta.")
        if len(mensaje) > LARGO_MAXIMO:
            raise ErrorValidacion(f"El mensaje admite máximo {LARGO_MAXIMO} caracteres.")
        if nivel not in NIVELES:
            raise ErrorValidacion("Elija el nivel de la alerta.")
        hoy = self.hoy()
        fecha_inicio = fecha_inicio or hoy
        if fecha_fin is not None and fecha_fin < fecha_inicio:
            raise ErrorValidacion("La fecha final no puede ser anterior a la inicial.")
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = sesion.get(Cliente, cliente_id)
            if cliente is None:
                raise ErrorValidacion("El cliente no existe.")
            alerta = Alerta(
                cliente_id=cliente.id, mensaje=mensaje, nivel=nivel, activa=True,
                fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, creada_por=actual.id,
                creada_en=ahora,
            )
            sesion.add(alerta)
            sesion.flush()
            auditoria.registrar(
                sesion, "alerta_creada", "alertas", usuario_id=actual.id,
                entidad_id=alerta.id, momento=ahora,
                detalle={"cliente": cliente.codigo, "nivel": nivel, "mensaje": mensaje},
            )
            sesion.commit()
            return alerta.id

    def resolver(self, actual: UsuarioActual, alerta_id: int) -> None:
        exigir(actual, Permiso.GESTIONAR_ALERTAS)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            alerta = sesion.get(Alerta, alerta_id)
            if alerta is None:
                raise ErrorValidacion("La alerta no existe.")
            if not alerta.activa:
                raise ErrorValidacion("La alerta ya estaba resuelta.")
            alerta.activa = False
            alerta.resuelta_por = actual.id
            alerta.resuelta_en = ahora
            codigo = sesion.scalar(select(Cliente.codigo).where(Cliente.id == alerta.cliente_id))
            auditoria.registrar(
                sesion, "alerta_resuelta", "alertas", usuario_id=actual.id,
                entidad_id=alerta.id, momento=ahora,
                detalle={"cliente": codigo, "mensaje": alerta.mensaje},
            )
            sesion.commit()

    def activas(self, actual: UsuarioActual, cliente_id: int) -> list[AlertaActiva]:
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            return alertas_activas(sesion, cliente_id, self.hoy())
