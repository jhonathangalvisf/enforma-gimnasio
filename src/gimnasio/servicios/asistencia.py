"""Recepción (sección 3.4) y Asistencia (sección 3.5).

Reglas:
- Cada paso del código queda guardado con su resultado (RF-R5): permitido, por vencer,
  vencido, inactivo o autorizado. Los rechazados (vencido o inactivo) se guardan, pero
  no cuentan como asistentes ni en los reportes, salvo que se filtre por ese resultado.
- Si el cliente ya ingresó hoy, según el parámetro `asistencia_duplicada` se avisa y se
  pide confirmar (por defecto), se bloquea o se registra sin avisar. Solo cuentan los
  ingresos efectivos (no los rechazados).
- "Ingreso autorizado" pide usuario y contraseña de un administrador y queda en la
  auditoría. "Renovar ahora" registra la membresía (Fase 3) y luego el ingreso.
- Cada asistencia guarda el casillero que tenía el cliente en ese momento (RN-11).
- Las asistencias se eliminan de forma lógica con motivo (RN-08). Recepción solo las
  del día; el administrador, cualquiera.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.formato import pesos
from gimnasio.modelos import (
    Asistencia, Casillero, CasilleroAsignacion, Cliente, Contacto, Membresia, Plan, Usuario,
    ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.alertas import AlertaActiva, alertas_activas
from gimnasio.servicios.clientes import NOMBRES_VIGENCIA, Vigencia, calcular_vigencia
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import saldo_pendiente_cliente
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, ServicioSesion, usuario_vigente

RESULTADOS = {
    "permitido": "Permitido",
    "por_vencer": "Por vencer",
    "vencido": "Vencido / sin membresía",
    "inactivo": "Cliente inactivo",
    "autorizado": "Autorizado por admin",
}
EFECTIVOS = ("permitido", "por_vencer", "autorizado")  # el cliente entró
RECHAZOS = ("vencido", "inactivo")  # se guardan, pero no entró

VERDE, AMARILLO, ROJO = "verde", "amarillo", "rojo"

# Estados del intento de ingreso.
REGISTRADO = "registrado"
RECHAZADO = "rechazado"
DUPLICADO_CONFIRMAR = "duplicado_confirmar"
DUPLICADO_BLOQUEADO = "duplicado_bloqueado"

LIMITE_CONSULTA = 500


# --- datos de salida --------------------------------------------------------------

@dataclass(frozen=True)
class TarjetaIngreso:
    """Lo que muestra la tarjeta grande de Recepción."""

    cliente_id: int
    codigo: str
    nombres: str
    apellidos: str
    foto: Path | None
    estado: str
    vigencia: Vigencia
    plan: str
    fecha_fin: date | None
    dias_restantes: int | None
    inicio_futuro: date | None  # tiene una membresía que aún no empieza
    casillero: str | None
    saldo_pendiente: int
    cumple_hoy: bool
    alertas: list[AlertaActiva]
    color: str  # verde / amarillo / rojo
    titulo: str
    mensaje: str
    resultado: str

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}"

    @property
    def permite_ingreso(self) -> bool:
        return self.resultado in EFECTIVOS

    @property
    def activo(self) -> bool:
        return self.estado == "activo"


@dataclass(frozen=True)
class ResultadoIngreso:
    tarjeta: TarjetaIngreso
    estado: str  # REGISTRADO, RECHAZADO, DUPLICADO_CONFIRMAR o DUPLICADO_BLOQUEADO
    asistencia_id: int | None = None
    ingreso_previo: datetime | None = None  # último ingreso efectivo de hoy (UTC)


@dataclass(frozen=True)
class FilaAsistencia:
    id: int
    fecha_hora: datetime  # UTC
    fecha: date
    cliente_id: int
    codigo: str
    nombre: str
    sexo: str
    plan: str
    resultado: str
    casillero: str | None
    usuario: str
    eliminada: bool = False
    motivo_eliminacion: str | None = None

    @property
    def efectiva(self) -> bool:
        return self.resultado in EFECTIVOS


@dataclass(frozen=True)
class ResumenDia:
    ultimos: list[FilaAsistencia]
    asistentes: int  # clientes distintos que entraron hoy
    ingresos: int  # ingresos efectivos (incluye repetidos)
    rechazados: int


@dataclass(frozen=True)
class FiltrosAsistencia:
    desde: date | None = None  # días de Bogotá, incluidos
    hasta: date | None = None
    cliente_id: int | None = None
    resultado: str | None = None  # uno exacto; None = solo ingresos efectivos
    incluir_rechazos: bool = False
    sexo: str | None = None
    plan_id: int | None = None
    incluir_eliminadas: bool = False  # solo admin


@dataclass(frozen=True)
class PaginaAsistencias:
    filas: list[FilaAsistencia]
    total: int


TIPOS_REPORTE = {
    "dia": "Asistencia del día",
    "rango": "Asistencia por rango de fechas",
    "cliente": "Asistencia de un cliente",
    "franja": "Asistencia por franja horaria",
    "ranking": "Ranking de asistencia",
    "ausentes": "Clientes que no vienen hace N días",
}


@dataclass(frozen=True)
class ParametrosReporte:
    tipo: str = "dia"
    desde: date | None = None
    hasta: date | None = None
    cliente_id: int | None = None
    dias: int = 30  # ausentes
    limite: int = 50  # ranking
    incluir_nunca: bool = False  # ausentes: también los que nunca han venido
    resultado: str | None = None
    sexo: str | None = None
    plan_id: int | None = None


@dataclass(frozen=True)
class Reporte:
    tipo: str
    titulo: str
    subtitulo: str
    encabezados: tuple[str, ...]
    filas: list[tuple]
    resumen: str = ""
    # Para la pantalla: identificador de asistencia por fila (si aplica).
    ids: list[int] = field(default_factory=list)


# --- auxiliares -------------------------------------------------------------------

def _motivo(texto: str) -> str:
    texto = " ".join((texto or "").split())
    if len(texto) < 3:
        raise ErrorValidacion("Escriba el motivo de la eliminación.")
    if len(texto) > 200:
        raise ErrorValidacion("El motivo admite máximo 200 caracteres.")
    return texto


def _plan_en_fecha():
    """Nombre del plan de la membresía (no anulada) que cubría el día de la asistencia."""
    return (
        select(Plan.nombre)
        .join(Membresia, Membresia.plan_id == Plan.id)
        .where(
            Membresia.cliente_id == Asistencia.cliente_id,
            Membresia.estado == "activa",
            Membresia.fecha_inicio <= Asistencia.fecha,
            Membresia.fecha_fin >= Asistencia.fecha,
        )
        .order_by(Membresia.fecha_fin.desc())
        .limit(1)
        .correlate(Asistencia)
        .scalar_subquery()
    )


def _casillero_actual():
    return (
        select(Casillero.numero)
        .join(CasilleroAsignacion, CasilleroAsignacion.casillero_id == Casillero.id)
        .where(CasilleroAsignacion.cliente_id == Cliente.id,
               CasilleroAsignacion.fecha_liberacion.is_(None))
        .limit(1)
        .correlate(Cliente)
        .scalar_subquery()
    )


def _desfase_horas() -> int:
    """Horas de diferencia entre Bogotá y UTC (−5; Colombia no tiene horario de verano)."""
    return int(cfg.ZONA_HORARIA.utcoffset(datetime.now()).total_seconds() // 3600)


def _hora_local(valor: datetime) -> str:
    return valor.astimezone(cfg.ZONA_HORARIA).strftime("%H:%M")


# --- servicio ---------------------------------------------------------------------

class ServicioAsistencia:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        sesiones: ServicioSesion,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._sesiones = sesiones
        self._carpeta = carpeta_datos
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    # --- Recepción ----------------------------------------------------------------
    def buscar_codigo(self, actual: UsuarioActual, texto: str) -> int:
        """Id del cliente con ese código (con o sin ceros a la izquierda) o QR."""
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        texto = (texto or "").strip()
        if not texto:
            raise ErrorValidacion("Escriba o lea el código del cliente.")
        with self._fabrica() as sesion:
            cliente_id = self._id_por_codigo(sesion, texto)
        if cliente_id is None:
            raise ErrorValidacion(f"No se encontró ningún cliente con el código «{texto[:30]}».")
        return cliente_id

    def tarjeta(self, actual: UsuarioActual, cliente_id: int) -> TarjetaIngreso:
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        with self._fabrica() as sesion:
            return self._tarjeta(sesion, self._cliente(sesion, cliente_id), self.hoy())

    def registrar_ingreso(
        self, actual: UsuarioActual, codigo: str, *, confirmar_duplicado: bool = False
    ) -> ResultadoIngreso:
        """Lo que pasa al digitar o leer un código y presionar Enter."""
        cliente_id = self.buscar_codigo(actual, codigo)
        return self.registrar_ingreso_cliente(
            actual, cliente_id, confirmar_duplicado=confirmar_duplicado
        )

    def registrar_ingreso_cliente(
        self, actual: UsuarioActual, cliente_id: int, *, confirmar_duplicado: bool = False
    ) -> ResultadoIngreso:
        """Registro por cliente ya elegido (lector, o manual por documento o nombre)."""
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        hoy = self.hoy()
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._cliente(sesion, cliente_id)
            tarjeta = self._tarjeta(sesion, cliente, hoy)
            previo = sesion.scalar(
                select(func.max(Asistencia.fecha_hora)).where(
                    Asistencia.cliente_id == cliente.id, Asistencia.fecha == hoy,
                    Asistencia.eliminada.is_(False), Asistencia.resultado.in_(EFECTIVOS),
                )
            )
            if previo is not None:
                previo = previo.replace(tzinfo=ahora.tzinfo) if previo.tzinfo is None else previo
            if tarjeta.permite_ingreso and previo is not None:
                politica = self._configuracion.obtener("asistencia_duplicada", sesion)
                if politica == "bloquear":
                    return ResultadoIngreso(tarjeta, DUPLICADO_BLOQUEADO, None, previo)
                if politica == "avisar" and not confirmar_duplicado:
                    return ResultadoIngreso(tarjeta, DUPLICADO_CONFIRMAR, None, previo)
            registro = Asistencia(
                cliente_id=cliente.id, fecha_hora=ahora, fecha=hoy,
                resultado=tarjeta.resultado, casillero_numero=tarjeta.casillero,
                usuario_id=actual.id,
            )
            sesion.add(registro)
            sesion.commit()
            estado = REGISTRADO if tarjeta.permite_ingreso else RECHAZADO
            return ResultadoIngreso(tarjeta, estado, registro.id, previo)

    def autorizar_ingreso(
        self, actual: UsuarioActual, asistencia_id: int, usuario_admin: str, clave_admin: str,
        motivo: str = "",
    ) -> ResultadoIngreso:
        """Convierte un ingreso rechazado de hoy en "autorizado" con la contraseña de un
        administrador. Queda en la auditoría a nombre del administrador."""
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        motivo = " ".join((motivo or "").split())[:200]
        with self._fabrica() as sesion:
            self._rechazo_de_hoy(sesion, asistencia_id)
        admin = self._sesiones.verificar_administrador(
            usuario_admin, clave_admin, f"autorizar ingreso (asistencia {asistencia_id})"
        )
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registro = self._rechazo_de_hoy(sesion, asistencia_id)
            cliente = self._cliente(sesion, registro.cliente_id)
            anterior = registro.resultado
            registro.resultado = "autorizado"
            auditoria.registrar(
                sesion, "ingreso_autorizado", "asistencias", usuario_id=admin.id,
                entidad_id=registro.id, momento=ahora,
                detalle={"cliente": cliente.codigo, "resultado_anterior": anterior,
                         "registrado_por": actual.usuario, "motivo": motivo or None},
            )
            sesion.commit()
            tarjeta = dataclasses.replace(
                self._tarjeta(sesion, cliente, self.hoy()), resultado="autorizado", color=VERDE,
                titulo="INGRESO AUTORIZADO",
                mensaje=f"Autorizado por {admin.nombre_completo}.",
            )
            return ResultadoIngreso(tarjeta, REGISTRADO, registro.id)

    def confirmar_tras_renovar(self, actual: UsuarioActual, asistencia_id: int) -> ResultadoIngreso:
        """Después de "Renovar ahora": si ya está vigente, el intento rechazado de hoy pasa
        a ser un ingreso permitido (o por vencer)."""
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registro = self._rechazo_de_hoy(sesion, asistencia_id)
            cliente = self._cliente(sesion, registro.cliente_id)
            tarjeta = self._tarjeta(sesion, cliente, self.hoy())
            if not tarjeta.permite_ingreso:
                raise ErrorValidacion(
                    "El cliente todavía no tiene una membresía vigente hoy. " + tarjeta.mensaje
                )
            anterior = registro.resultado
            registro.resultado = tarjeta.resultado
            registro.casillero_numero = tarjeta.casillero
            auditoria.registrar(
                sesion, "ingreso_tras_renovar", "asistencias", usuario_id=actual.id,
                entidad_id=registro.id, momento=ahora,
                detalle={"cliente": cliente.codigo, "resultado_anterior": anterior,
                         "resultado": tarjeta.resultado},
            )
            sesion.commit()
            return ResultadoIngreso(tarjeta, REGISTRADO, registro.id)

    def resumen_del_dia(self, actual: UsuarioActual, limite: int = 30) -> ResumenDia:
        """Últimos ingresos de hoy (incluye rechazados) y el contador de asistentes."""
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        hoy = self.hoy()
        base = (Asistencia.fecha == hoy, Asistencia.eliminada.is_(False))
        with self._fabrica() as sesion:
            asistentes = sesion.scalar(
                select(func.count(func.distinct(Asistencia.cliente_id)))
                .where(*base, Asistencia.resultado.in_(EFECTIVOS))
            )
            ingresos = sesion.scalar(
                select(func.count(Asistencia.id)).where(*base, Asistencia.resultado.in_(EFECTIVOS))
            )
            rechazados = sesion.scalar(
                select(func.count(Asistencia.id)).where(*base, Asistencia.resultado.in_(RECHAZOS))
            )
            ultimos = self._filas(sesion, list(base), desde=0, limite=limite)
        return ResumenDia(ultimos, asistentes or 0, ingresos or 0, rechazados or 0)

    # --- eliminación --------------------------------------------------------------
    def eliminar(self, actual: UsuarioActual, asistencia_id: int, motivo: str) -> None:
        exigir(actual, Permiso.ELIMINAR_ASISTENCIA_DEL_DIA)
        motivo = _motivo(motivo)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registro = sesion.get(Asistencia, asistencia_id)
            if registro is None:
                raise ErrorValidacion("El registro de asistencia no existe.")
            if registro.eliminada:
                raise ErrorValidacion("Ese registro de asistencia ya estaba eliminado.")
            if registro.fecha != self.hoy() and not actual.puede(
                Permiso.ELIMINAR_ASISTENCIA_CUALQUIERA
            ):
                raise ErrorPermiso(
                    "Recepción solo puede eliminar asistencias del día de hoy. "
                    "Pida al administrador las de otros días."
                )
            registro.eliminada = True
            registro.motivo_eliminacion = motivo
            registro.eliminada_por = actual.id
            registro.eliminada_en = ahora
            codigo = sesion.scalar(select(Cliente.codigo).where(Cliente.id == registro.cliente_id))
            auditoria.registrar(
                sesion, "asistencia_eliminada", "asistencias", usuario_id=actual.id,
                entidad_id=registro.id, momento=ahora,
                detalle={"cliente": codigo, "fecha": formato_fecha(registro.fecha),
                         "hora": _hora_local(registro.fecha_hora),
                         "resultado": registro.resultado, "motivo": motivo},
            )
            sesion.commit()

    # --- consultas ----------------------------------------------------------------
    def consultar(
        self, actual: UsuarioActual, filtros: FiltrosAsistencia = FiltrosAsistencia(),
        *, desde: int = 0, limite: int | None = LIMITE_CONSULTA,
    ) -> PaginaAsistencias:
        """Consulta por cliente, día, rango, resultado, sexo y plan (más reciente primero).

        Recepción puede consultar el día de hoy y el historial de un cliente; el
        administrador, cualquier rango.
        """
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        self._exigir_alcance(actual, filtros)
        condiciones = self._condiciones(filtros)
        with self._fabrica() as sesion:
            conteo = select(func.count(Asistencia.id))
            if filtros.sexo:  # el sexo es el único filtro que necesita la tabla de clientes
                conteo = conteo.join(Cliente, Cliente.id == Asistencia.cliente_id)
            total = sesion.scalar(conteo.where(*condiciones))
            filas = self._filas(sesion, condiciones, desde=desde, limite=limite)
        return PaginaAsistencias(filas, total or 0)

    def planes(self, actual: UsuarioActual) -> list[tuple[int, str]]:
        exigir(actual, Permiso.REGISTRAR_ASISTENCIA)
        with self._fabrica() as sesion:
            return [tuple(f) for f in sesion.execute(
                select(Plan.id, Plan.nombre).order_by(Plan.activo.desc(), Plan.nombre)
            )]

    # --- reportes (RF-S4) -----------------------------------------------------------
    def reporte(self, actual: UsuarioActual, p: ParametrosReporte) -> Reporte:
        if p.tipo not in TIPOS_REPORTE:
            raise ErrorValidacion("Tipo de reporte no válido.")
        hoy = self.hoy()
        if p.tipo == "dia":
            exigir(actual, Permiso.REPORTES_BASICOS)
            dia = p.desde or hoy
            if dia != hoy and not actual.puede(Permiso.REPORTES_TODOS):
                raise ErrorPermiso("Recepción solo puede ver el reporte de asistencia de hoy.")
            desde = hasta = dia
        else:
            exigir(actual, Permiso.REPORTES_TODOS)
            desde, hasta = p.desde or hoy, p.hasta or p.desde or hoy
        if desde > hasta:
            raise ErrorValidacion("La fecha inicial no puede ser posterior a la final.")
        nombre_gimnasio = self._configuracion.obtener("gimnasio_nombre")
        generado = f"generado el {formato_fecha(hoy)}"
        periodo = (formato_fecha(desde) if desde == hasta
                   else f"del {formato_fecha(desde)} al {formato_fecha(hasta)}")

        if p.tipo in ("dia", "rango", "cliente"):
            if p.tipo == "cliente" and not p.cliente_id:
                raise ErrorValidacion("Elija el cliente.")
            filtros = FiltrosAsistencia(
                desde=desde, hasta=hasta,
                cliente_id=p.cliente_id if p.tipo == "cliente" else None,
                resultado=p.resultado, sexo=p.sexo, plan_id=p.plan_id,
            )
            if p.tipo == "cliente" and not p.desde:
                filtros = dataclasses.replace(filtros, desde=None, hasta=None)
                periodo = "todo el historial"
            pagina = self.consultar(actual, filtros, limite=None)
            filas = [
                (f.fecha, _hora_local(f.fecha_hora), f.codigo, f.nombre, f.plan,
                 RESULTADOS.get(f.resultado, f.resultado), f.casillero or "", f.usuario)
                for f in pagina.filas
            ]
            titulo = TIPOS_REPORTE[p.tipo]
            if p.tipo == "cliente" and pagina.filas:
                titulo += f": {pagina.filas[0].codigo} {pagina.filas[0].nombre}"
            distintos = len({f.cliente_id for f in pagina.filas})
            resumen = f"{len(filas)} ingresos · {distintos} clientes distintos"
            return Reporte(
                p.tipo, titulo, f"{nombre_gimnasio} · {periodo} · {resumen} · {generado}",
                ("Fecha", "Hora", "Código", "Cliente", "Plan", "Resultado", "Casillero",
                 "Registró"),
                filas, resumen, [f.id for f in pagina.filas],
            )

        if p.tipo == "franja":
            return self._reporte_franja(desde, hasta, p, nombre_gimnasio, periodo, generado)
        if p.tipo == "ranking":
            return self._reporte_ranking(desde, hasta, p, nombre_gimnasio, periodo, generado)
        return self._reporte_ausentes(hoy, p, nombre_gimnasio, generado)

    def exportar(
        self, actual: UsuarioActual, p: ParametrosReporte, ruta: Path | str, formato: str
    ) -> Path:
        """Exporta el reporte a Excel ("xlsx") o PDF ("pdf"). Queda en la auditoría."""
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        rep = self.reporte(actual, p)
        if formato == "xlsx":
            ruta = exp.exportar_excel(ruta, rep.titulo, rep.encabezados, rep.filas)
        else:
            ruta = exp.exportar_pdf(ruta, rep.titulo, rep.subtitulo, rep.encabezados, rep.filas)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "asistencias_exportadas", "asistencias", usuario_id=actual.id,
                momento=self._reloj(),
                detalle={"reporte": rep.tipo, "formato": formato, "filas": len(rep.filas)},
            )
            sesion.commit()
        return Path(ruta)

    def carpeta_reportes(self) -> Path:
        carpeta = (self._carpeta or cfg.carpeta_datos()) / "reportes"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    def _reporte_franja(self, desde, hasta, p, nombre_gimnasio, periodo, generado) -> Reporte:
        hora = func.strftime("%H", Asistencia.fecha_hora, f"{_desfase_horas()} hours")
        condiciones = self._condiciones(FiltrosAsistencia(
            desde=desde, hasta=hasta, resultado=p.resultado, sexo=p.sexo, plan_id=p.plan_id,
        ))
        with self._fabrica() as sesion:
            conteo = dict(sesion.execute(
                select(hora, func.count(Asistencia.id))
                .join(Cliente, Cliente.id == Asistencia.cliente_id)
                .where(*condiciones).group_by(hora)
            ).all())
        total = sum(conteo.values())
        dias = (hasta - desde).days + 1
        filas = []
        for h in sorted(conteo):
            n = conteo[h]
            filas.append((
                f"{h}:00 – {h}:59", n, round(n / dias, 1),
                f"{(100 * n / total):.1f} %".replace(".", ",") if total else "0 %",
            ))
        resumen = f"{total} ingresos en {dias} día(s)"
        return Reporte(
            "franja", TIPOS_REPORTE["franja"],
            f"{nombre_gimnasio} · {periodo} · {resumen} · {generado}",
            ("Franja horaria", "Ingresos", "Promedio por día", "Porcentaje"), filas, resumen,
        )

    def _reporte_ranking(self, desde, hasta, p, nombre_gimnasio, periodo, generado) -> Reporte:
        limite = max(1, min(int(p.limite or 50), 1000))
        condiciones = self._condiciones(FiltrosAsistencia(
            desde=desde, hasta=hasta, sexo=p.sexo, plan_id=p.plan_id,
        ))
        cantidad = func.count(Asistencia.id).label("cantidad")
        with self._fabrica() as sesion:
            filas_bd = sesion.execute(
                select(Cliente.codigo, Cliente.nombres, Cliente.apellidos, cantidad,
                       func.max(Asistencia.fecha).label("ultima"),
                       _casillero_actual().label("casillero"))
                .join(Cliente, Cliente.id == Asistencia.cliente_id)
                .where(*condiciones)
                .group_by(Cliente.id)
                .order_by(cantidad.desc(), Cliente.apellidos, Cliente.nombres)
                .limit(limite)
            ).all()
        filas = [
            (i, r.codigo, f"{r.nombres} {r.apellidos}", r.cantidad,
             date.fromisoformat(r.ultima) if isinstance(r.ultima, str) else r.ultima,
             r.casillero or "")
            for i, r in enumerate(filas_bd, start=1)
        ]
        resumen = f"Los {len(filas)} clientes que más asistieron"
        return Reporte(
            "ranking", TIPOS_REPORTE["ranking"],
            f"{nombre_gimnasio} · {periodo} · {resumen} · {generado}",
            ("Puesto", "Código", "Cliente", "Asistencias", "Última asistencia",
             "Casillero actual"), filas, resumen,
        )

    def _reporte_ausentes(self, hoy, p, nombre_gimnasio, generado) -> Reporte:
        dias = int(p.dias or 0)
        if not 1 <= dias <= 3650:
            raise ErrorValidacion("Escriba un número de días entre 1 y 3650.")
        limite_fecha = hoy - timedelta(days=dias)
        ultima = (
            select(func.max(Asistencia.fecha))
            .where(Asistencia.cliente_id == Cliente.id, Asistencia.eliminada.is_(False),
                   Asistencia.resultado.in_(EFECTIVOS))
            .correlate(Cliente).scalar_subquery()
        )
        fin = (
            select(func.max(Membresia.fecha_fin))
            .where(Membresia.cliente_id == Cliente.id, Membresia.estado == "activa")
            .correlate(Cliente).scalar_subquery()
        )
        telefono = (
            select(Contacto.valor)
            .where(Contacto.cliente_id == Cliente.id, Contacto.tipo == "telefono")
            .order_by(Contacto.principal.desc(), Contacto.id).limit(1)
            .correlate(Cliente).scalar_subquery()
        )
        condicion = ultima <= limite_fecha
        if p.incluir_nunca:
            condicion = condicion | ultima.is_(None)
        condiciones = [Cliente.estado == "activo", condicion]
        if p.sexo:
            condiciones.append(Cliente.sexo == p.sexo)
        dias_por_vencer = self._configuracion.obtener("dias_por_vencer")
        with self._fabrica() as sesion:
            filas_bd = sesion.execute(
                select(Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                       telefono.label("telefono"), ultima.label("ultima"), fin.label("fin"),
                       _casillero_actual().label("casillero"))
                .where(*condiciones)
                .order_by(ultima.desc().nulls_last(), Cliente.apellidos)
            ).all()
        filas = []
        for r in filas_bd:
            ult = date.fromisoformat(r.ultima) if isinstance(r.ultima, str) else r.ultima
            fin_r = date.fromisoformat(r.fin) if isinstance(r.fin, str) else r.fin
            vigencia, _ = calcular_vigencia(fin_r, hoy, dias_por_vencer)
            filas.append((
                r.codigo, f"{r.nombres} {r.apellidos}", r.telefono or "",
                ult if ult else "Nunca", (hoy - ult).days if ult else "",
                NOMBRES_VIGENCIA[vigencia], r.casillero or "",
            ))
        resumen = f"{len(filas)} clientes activos sin venir hace {dias} días o más"
        return Reporte(
            "ausentes", f"Clientes que no vienen hace {dias} días",
            f"{nombre_gimnasio} · {resumen} · {generado}",
            ("Código", "Cliente", "Teléfono", "Última asistencia", "Días sin venir",
             "Vigencia", "Casillero"), filas, resumen,
        )

    # --- auxiliares ---------------------------------------------------------------
    @staticmethod
    def _id_por_codigo(sesion: Session, texto: str) -> int | None:
        condicion = Cliente.qr_token == texto
        if texto.isdigit() and len(texto) <= 6:
            condicion = condicion | (Cliente.codigo == texto.zfill(6))
        return sesion.scalar(select(Cliente.id).where(condicion).limit(1))

    @staticmethod
    def _cliente(sesion: Session, cliente_id: int) -> Cliente:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise ErrorValidacion("El cliente no existe.")
        return cliente

    def _rechazo_de_hoy(self, sesion: Session, asistencia_id: int) -> Asistencia:
        registro = sesion.get(Asistencia, asistencia_id)
        if registro is None or registro.eliminada:
            raise ErrorValidacion("El registro de ingreso no existe.")
        if registro.fecha != self.hoy():
            raise ErrorValidacion("Solo se pueden resolver los ingresos de hoy.")
        if registro.resultado not in RECHAZOS:
            raise ErrorValidacion("Ese ingreso ya estaba permitido.")
        return registro

    def _tarjeta(self, sesion: Session, cliente: Cliente, hoy: date) -> TarjetaIngreso:
        membresias = sesion.execute(
            select(Membresia, Plan.nombre).join(Plan, Plan.id == Membresia.plan_id)
            .where(Membresia.cliente_id == cliente.id, Membresia.estado == "activa")
            .order_by(Membresia.fecha_fin.desc(), Membresia.id.desc())
        ).all()
        fin = membresias[0][0].fecha_fin if membresias else None
        vigente_hoy = next(
            ((m, n) for m, n in membresias if m.fecha_inicio <= hoy <= m.fecha_fin), None
        )
        futuras = [m for m, _ in membresias if m.fecha_inicio > hoy]
        inicio_futuro = min(m.fecha_inicio for m in futuras) if futuras and not vigente_hoy else None
        dias_por_vencer = self._configuracion.obtener("dias_por_vencer", sesion)
        vigencia, dias = calcular_vigencia(fin, hoy, dias_por_vencer)
        if inicio_futuro is not None:
            plan = next(n for m, n in membresias if m.fecha_inicio == inicio_futuro)
        elif vigente_hoy is not None:
            plan = vigente_hoy[1]
        else:
            plan = membresias[0][1] if membresias else ""

        casillero = sesion.scalar(
            select(Casillero.numero)
            .join(CasilleroAsignacion, CasilleroAsignacion.casillero_id == Casillero.id)
            .where(CasilleroAsignacion.cliente_id == cliente.id,
                   CasilleroAsignacion.fecha_liberacion.is_(None))
        )
        saldo = saldo_pendiente_cliente(sesion, cliente.id)
        nacimiento = cliente.fecha_nacimiento
        cumple = bool(nacimiento and (nacimiento.month, nacimiento.day) == (hoy.month, hoy.day))
        foto = None
        if cliente.foto_ruta:
            ruta = (self._carpeta or cfg.carpeta_datos()) / "fotos" / cliente.foto_ruta
            foto = ruta if ruta.exists() else None

        # Color, título, mensaje y resultado.
        if cliente.estado != "activo":
            color, resultado, titulo = ROJO, "inactivo", "CLIENTE INACTIVO"
            mensaje = "No puede ingresar. Consulte con el administrador."
        elif inicio_futuro is not None:
            color, resultado, titulo = ROJO, "vencido", "SU PLAN AÚN NO INICIA"
            mensaje = f"Su plan {plan} inicia el {formato_fecha(inicio_futuro)}."
        elif vigencia == Vigencia.SIN_MEMBRESIA:
            color, resultado, titulo = ROJO, "vencido", "SIN MEMBRESÍA"
            mensaje = "No tiene ninguna membresía registrada."
        elif vigencia == Vigencia.VENCIDA:
            color, resultado, titulo = ROJO, "vencido", "MEMBRESÍA VENCIDA"
            hace = -dias
            mensaje = (f"Tu plan venció el {formato_fecha(fin)} "
                       f"(hace {hace} {'día' if hace == 1 else 'días'}).")
        elif vigencia == Vigencia.POR_VENCER:
            color, resultado, titulo = AMARILLO, "por_vencer", "POR VENCER"
            if dias == 0:
                mensaje = f"Tu plan vence hoy, {formato_fecha(fin)}."
            else:
                mensaje = (f"Tu plan vence el {formato_fecha(fin)} "
                           f"(falta{'' if dias == 1 else 'n'} {dias} {'día' if dias == 1 else 'días'}).")
        else:
            color, resultado, titulo = VERDE, "permitido", "BIENVENIDO"
            mensaje = f"Plan vigente hasta el {formato_fecha(fin)} ({dias} días)."
        if color == VERDE and saldo:
            color, titulo = AMARILLO, "BIENVENIDO · SALDO PENDIENTE"
        if saldo and resultado in EFECTIVOS:
            mensaje += f" Saldo pendiente: {pesos(saldo)}."

        return TarjetaIngreso(
            cliente_id=cliente.id, codigo=cliente.codigo, nombres=cliente.nombres,
            apellidos=cliente.apellidos, foto=foto, estado=cliente.estado, vigencia=vigencia,
            plan=plan, fecha_fin=fin, dias_restantes=dias, inicio_futuro=inicio_futuro,
            casillero=casillero, saldo_pendiente=saldo, cumple_hoy=cumple,
            alertas=alertas_activas(sesion, cliente.id, hoy), color=color, titulo=titulo,
            mensaje=mensaje, resultado=resultado,
        )

    def _exigir_alcance(self, actual: UsuarioActual, filtros: FiltrosAsistencia) -> None:
        if actual.puede(Permiso.REPORTES_TODOS):
            return
        if filtros.incluir_eliminadas:
            raise ErrorPermiso("Solo el administrador puede ver las asistencias eliminadas.")
        hoy = self.hoy()
        if filtros.cliente_id is None and not (filtros.desde == hoy and filtros.hasta == hoy):
            raise ErrorPermiso(
                "Recepción puede consultar la asistencia de hoy o el historial de un cliente. "
                "Los demás periodos los consulta el administrador."
            )

    @staticmethod
    def _condiciones(filtros: FiltrosAsistencia) -> list[ColumnElement[bool]]:
        condiciones: list[ColumnElement[bool]] = []
        if not filtros.incluir_eliminadas:
            condiciones.append(Asistencia.eliminada.is_(False))
        if filtros.desde:
            condiciones.append(Asistencia.fecha >= filtros.desde)
        if filtros.hasta:
            condiciones.append(Asistencia.fecha <= filtros.hasta)
        if filtros.cliente_id:
            condiciones.append(Asistencia.cliente_id == filtros.cliente_id)
        if filtros.resultado:
            if filtros.resultado not in RESULTADOS:
                raise ErrorValidacion("Resultado no válido.")
            condiciones.append(Asistencia.resultado == filtros.resultado)
        elif not filtros.incluir_rechazos:
            condiciones.append(Asistencia.resultado.in_(EFECTIVOS))
        if filtros.sexo:
            condiciones.append(Cliente.sexo == filtros.sexo)
        if filtros.plan_id:
            condiciones.append(exists().where(
                Membresia.cliente_id == Asistencia.cliente_id,
                Membresia.estado == "activa",
                Membresia.plan_id == filtros.plan_id,
                and_(Membresia.fecha_inicio <= Asistencia.fecha,
                     Membresia.fecha_fin >= Asistencia.fecha),
            ))
        return condiciones

    @staticmethod
    def _filas(
        sesion: Session, condiciones: list, *, desde: int, limite: int | None
    ) -> list[FilaAsistencia]:
        consulta = (
            select(Asistencia, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                   Cliente.sexo, Usuario.usuario, _plan_en_fecha().label("plan"))
            .join(Cliente, Cliente.id == Asistencia.cliente_id)
            .outerjoin(Usuario, Usuario.id == Asistencia.usuario_id)
            .where(*condiciones)
            # Primero por día: así SQLite recorre el índice de fecha y solo ordena por
            # hora dentro de cada día (con 30 días: ~35 ms en lugar de ~400 ms).
            .order_by(Asistencia.fecha.desc(), Asistencia.fecha_hora.desc(), Asistencia.id.desc())
            .offset(desde)
        )
        if limite is not None:
            consulta = consulta.limit(limite)
        return [
            FilaAsistencia(
                id=a.id, fecha_hora=a.fecha_hora, fecha=a.fecha, cliente_id=a.cliente_id,
                codigo=codigo, nombre=f"{nombres} {apellidos}", sexo=sexo, plan=plan or "",
                resultado=a.resultado, casillero=a.casillero_numero, usuario=usuario or "—",
                eliminada=a.eliminada, motivo_eliminacion=a.motivo_eliminacion,
            )
            for a, codigo, nombres, apellidos, sexo, usuario, plan in sesion.execute(consulta)
        ]
