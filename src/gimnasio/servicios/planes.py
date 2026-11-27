"""Planes (RF-P1): nombre, duración en días, precio y activo.

Solo el administrador los crea y edita. Los planes no se borran: se desactivan y
dejan de ofrecerse, pero las membresías ya registradas los conservan. Cambiar el
precio o la duración no modifica las membresías que ya existen (guardan su
precio pactado y sus fechas).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio.modelos import Plan
from gimnasio.servicios import auditoria
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import usuario_vigente
from gimnasio.texto import normalizar

DURACION_MAXIMA = 3660  # 10 años
PRECIO_MAXIMO = 99_999_999

# Planes del gimnasio. Se crean activos y con precio simbólico de $1 cuando la base no
# tiene ningún plan activo para vender: en el recibo importa qué plan eligió el cliente
# (decisión del gimnasio). El precio se cambia en Configuración → Planes. Un plan con
# precio $0 no se puede vender.
PLANES_EJEMPLO: tuple[tuple[str, int], ...] = (
    ("Mensual", 30), ("Quincena", 15), ("Trimestre", 90), ("Semestre", 180),
    ("Año", 365), ("Semana", 7),
)
PRECIO_PREDETERMINADO = 1
# Plan de las membresías traídas del programa anterior (no se vende).
PLAN_PROGRAMA_ANTERIOR = "Programa anterior"


@dataclass(frozen=True)
class DatosPlan:
    id: int
    nombre: str
    duracion_dias: int
    precio: int
    activo: bool

    @property
    def descripcion(self) -> str:
        dias = "1 día" if self.duracion_dias == 1 else f"{self.duracion_dias} días"
        return f"{self.nombre} ({dias})"


def _a_datos(plan: Plan) -> DatosPlan:
    return DatosPlan(plan.id, plan.nombre, plan.duracion_dias, plan.precio, plan.activo)


def _validar(nombre: str, duracion_dias, precio) -> tuple[str, int, int]:
    nombre = " ".join((nombre or "").split())
    if len(nombre) < 2:
        raise ErrorValidacion("Escriba el nombre del plan.")
    if len(nombre) > 60:
        raise ErrorValidacion("El nombre del plan admite máximo 60 caracteres.")
    try:
        duracion_dias, precio = int(duracion_dias), int(precio)
    except (TypeError, ValueError):
        raise ErrorValidacion("La duración y el precio deben ser números enteros.") from None
    if not 1 <= duracion_dias <= DURACION_MAXIMA:
        raise ErrorValidacion(f"La duración debe estar entre 1 y {DURACION_MAXIMA} días.")
    if not 0 <= precio <= PRECIO_MAXIMO:
        raise ErrorValidacion("El precio no es válido (pesos sin decimales).")
    return nombre, duracion_dias, precio


class ServicioPlanes:
    def __init__(self, fabrica: sessionmaker[Session]):
        self._fabrica = fabrica

    def listar(self, actual: UsuarioActual, solo_activos: bool = False) -> list[DatosPlan]:
        """Recepción los necesita para elegir el plan al registrar una membresía."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        consulta = select(Plan).order_by(Plan.activo.desc(), Plan.duracion_dias, Plan.nombre)
        if solo_activos:
            consulta = consulta.where(Plan.activo.is_(True))
        with self._fabrica() as sesion:
            return [_a_datos(p) for p in sesion.scalars(consulta)]

    def crear(
        self, actual: UsuarioActual, nombre: str, duracion_dias: int, precio: int,
        activo: bool = True,
    ) -> DatosPlan:
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        nombre, duracion_dias, precio = _validar(nombre, duracion_dias, precio)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            self._exigir_nombre_libre(sesion, nombre)
            plan = Plan(nombre=nombre, duracion_dias=duracion_dias, precio=precio, activo=activo)
            sesion.add(plan)
            sesion.flush()
            auditoria.registrar(
                sesion, "plan_creado", "planes", usuario_id=actual.id, entidad_id=plan.id,
                detalle={"nombre": nombre, "duracion_dias": duracion_dias, "precio": precio,
                         "activo": activo},
            )
            sesion.commit()
            return _a_datos(plan)

    def editar(
        self, actual: UsuarioActual, plan_id: int, nombre: str, duracion_dias: int, precio: int
    ) -> list[str]:
        """Devuelve los campos que cambiaron. No toca las membresías ya registradas."""
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        nombre, duracion_dias, precio = _validar(nombre, duracion_dias, precio)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            plan = self._obtener(sesion, plan_id)
            cambios = {}
            for campo, nuevo in (("nombre", nombre), ("duracion_dias", duracion_dias),
                                 ("precio", precio)):
                anterior = getattr(plan, campo)
                if anterior != nuevo:
                    cambios[campo] = {"antes": anterior, "despues": nuevo}
            if not cambios:
                return []
            if "nombre" in cambios:
                self._exigir_nombre_libre(sesion, nombre, excepto_id=plan.id)
            plan.nombre, plan.duracion_dias, plan.precio = nombre, duracion_dias, precio
            auditoria.registrar(
                sesion, "plan_editado", "planes", usuario_id=actual.id, entidad_id=plan.id,
                detalle=cambios,
            )
            sesion.commit()
            return list(cambios)

    def cambiar_activo(self, actual: UsuarioActual, plan_id: int, activo: bool) -> None:
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            plan = self._obtener(sesion, plan_id)
            if plan.activo == activo:
                return
            plan.activo = activo
            auditoria.registrar(
                sesion, "plan_activado" if activo else "plan_desactivado", "planes",
                usuario_id=actual.id, entidad_id=plan.id, detalle={"nombre": plan.nombre},
            )
            sesion.commit()

    def crear_planes_ejemplo(self) -> int:
        """Al arrancar: si no hay ningún plan activo para vender, deja listos los planes
        del gimnasio (Mensual, Quincena, Trimestre, Semestre, Año y Semana): crea los que
        falten y activa los que existan con ese nombre. Los que no tienen precio quedan
        en $1 (el administrador lo cambia cuando quiera).

        Devuelve cuántos creó o activó (0 si ya había planes activos).
        """
        with self._fabrica() as sesion:
            planes = list(sesion.scalars(select(Plan)))
            vendibles = [p for p in planes
                         if p.activo and normalizar(p.nombre) != normalizar(PLAN_PROGRAMA_ANTERIOR)]
            if vendibles:
                return 0
            por_nombre = {normalizar(p.nombre): p for p in planes}
            cambios = []
            for nombre, dias in PLANES_EJEMPLO:
                existente = por_nombre.get(normalizar(nombre))
                if existente is None:
                    sesion.add(Plan(nombre=nombre, duracion_dias=dias, precio=PRECIO_PREDETERMINADO,
                                    activo=True))
                    cambios.append(nombre)
                elif not existente.activo:
                    existente.activo = True
                    existente.precio = existente.precio or PRECIO_PREDETERMINADO
                    cambios.append(existente.nombre)
            if not cambios:
                return 0
            auditoria.registrar(sesion, "planes_ejemplo_creados", "planes",
                                detalle={"planes": cambios})
            sesion.commit()
            return len(cambios)

    # --- apoyo ----------------------------------------------------------------
    @staticmethod
    def _obtener(sesion: Session, plan_id: int) -> Plan:
        plan = sesion.get(Plan, plan_id)
        if plan is None:
            raise ErrorValidacion("El plan no existe.")
        return plan

    @staticmethod
    def _exigir_nombre_libre(sesion: Session, nombre: str, excepto_id: int | None = None) -> None:
        clave = normalizar(nombre)
        for plan_id, existente in sesion.execute(select(Plan.id, Plan.nombre)):
            if plan_id != excepto_id and normalizar(existente) == clave:
                raise ErrorValidacion(f"Ya existe un plan llamado «{existente}».")
