"""Módulo Reportes (sección 3.8): un catálogo único con todos los reportes del sistema.

- Clientes: por vencer (con teléfono), vencidos, morosos, nuevos, renovaciones, bajas
  y el resumen mensual de nuevos, renovaciones y bajas.
- Ingresos: detalle, por día, por método, por usuario, por plan, pagos anulados y
  cierre de caja.
- Asistencia, casilleros e invitados: reutilizan los reportes de sus módulos.

Permisos (decisión del dueño, Fase 7): Recepción ve la asistencia de hoy, los
casilleros, las visitas de invitados de hoy, su propio cierre de caja del día y los
clientes por vencer. Todo lo demás, en especial los ingresos, solo el administrador.
La verificación se hace aquí y en los servicios de cada módulo, no en la pantalla.

Todos se exportan a Excel y PDF (queda en la auditoría) y se imprimen desde el PDF.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.modelos import (
    Auditoria, Casillero, CasilleroAsignacion, Cliente, Membresia, Pago, Plan, Usuario,
    ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.asistencia import (
    ParametrosReporte, ServicioAsistencia, _desfase_horas,
)
from gimnasio.servicios.auditoria import inicio_dia_utc
from gimnasio.servicios.casilleros import (
    ESTADOS as ESTADOS_CASILLERO, SITUACIONES, ZONAS, FiltrosCasilleros, ServicioCasilleros,
)
from gimnasio.servicios.clientes import ESTADOS as ESTADOS_CLIENTE, SEXOS, _Expresiones
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.invitados import ParametrosReporteInvitados, ServicioInvitados
from gimnasio.servicios.pagos import CONCEPTOS, METODOS, ServicioPagos, numero_recibo
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")
RANGO_MAXIMO_DIAS = 3 * 366  # evita consultas enormes por error al escribir una fecha


# --- catálogo ---------------------------------------------------------------------

@dataclass(frozen=True)
class DefinicionReporte:
    clave: str
    grupo: str
    titulo: str
    descripcion: str
    # Filtros que usa: dia, rango, dias, cliente, anfitrion, plan, sexo, metodo, usuario,
    # concepto, limite, nunca, estado_casillero, zona, sexo_ocupante, situacion.
    filtros: tuple[str, ...] = ()
    recepcion: bool = False  # Recepción puede abrirlo (con los límites de su módulo)
    nota_recepcion: str = ""  # qué límite tiene Recepción, para mostrarlo en pantalla
    solo_hoy_recepcion: bool = False  # Recepción solo lo ve para el día de hoy


_FILTROS_PAGOS = ("rango", "metodo", "usuario", "concepto", "plan")

CATALOGO: tuple[DefinicionReporte, ...] = (
    # Clientes
    DefinicionReporte(
        "clientes_por_vencer", "Clientes", "Clientes por vencer",
        "Clientes activos cuya membresía vence en los próximos N días, con teléfono para "
        "llamarlos.", ("dias", "plan", "sexo"), recepcion=True),
    DefinicionReporte(
        "clientes_vencidos", "Clientes", "Clientes vencidos",
        "Clientes activos con la membresía vencida (sin renovar), con días de vencido, "
        "teléfono y saldo. N = vencidos en los últimos N días (0 = todos).",
        ("dias", "plan", "sexo")),
    DefinicionReporte(
        "clientes_morosos", "Clientes", "Clientes morosos (saldo pendiente)",
        "Membresías no anuladas con saldo por pagar (abonos incompletos).", ("plan", "sexo")),
    DefinicionReporte(
        "clientes_mensual", "Clientes", "Nuevos, renovaciones y bajas por mes",
        "Por cada mes: clientes nuevos, renovaciones, clientes inactivados y clientes "
        "activos que se vencieron y no renovaron.", ("rango",)),
    DefinicionReporte(
        "clientes_nuevos", "Clientes", "Clientes nuevos (detalle)",
        "Clientes registrados en el periodo, con su primera membresía.", ("rango", "sexo")),
    DefinicionReporte(
        "clientes_renovaciones", "Clientes", "Renovaciones (detalle)",
        "Membresías vendidas en el periodo a clientes que ya habían tenido otra.",
        ("rango", "plan")),
    DefinicionReporte(
        "clientes_bajas", "Clientes", "Bajas (detalle)",
        "Clientes inactivados en el periodo (con el motivo) y clientes activos cuya última "
        "membresía venció en el periodo sin renovar.", ("rango",)),
    # Ingresos
    DefinicionReporte(
        "ingresos_detalle", "Ingresos", "Ingresos: detalle de pagos",
        "Todos los pagos del periodo. Los anulados no suman.", _FILTROS_PAGOS),
    DefinicionReporte(
        "ingresos_dia", "Ingresos", "Ingresos por día",
        "Total de cada día, separado por método de pago.", _FILTROS_PAGOS),
    DefinicionReporte(
        "ingresos_metodo", "Ingresos", "Ingresos por método de pago",
        "Efectivo, tarjeta y transferencia en el periodo.", _FILTROS_PAGOS),
    DefinicionReporte(
        "ingresos_usuario", "Ingresos", "Ingresos por usuario",
        "Lo que recibió cada usuario, separado por método de pago.", _FILTROS_PAGOS),
    DefinicionReporte(
        "ingresos_plan", "Ingresos", "Ingresos por plan",
        "Membresías por plan, casilleros y otros conceptos.", _FILTROS_PAGOS),
    DefinicionReporte(
        "pagos_anulados", "Ingresos", "Pagos anulados",
        "Pagos del periodo que se anularon, con quién y por qué.", ("rango", "usuario")),
    DefinicionReporte(
        "cierre_caja", "Ingresos", "Cierre de caja",
        "Pagos de un día con totales por método y por usuario.", ("dia", "usuario"),
        recepcion=True, nota_recepcion="Recepción ve solo su propio cierre de hoy.",
        solo_hoy_recepcion=True),
    # Asistencia
    DefinicionReporte(
        "asistencia_dia", "Asistencia", "Asistencia del día",
        "Ingresos de un día con el casillero que tenía cada cliente.", ("dia", "sexo", "plan"),
        recepcion=True, nota_recepcion="Recepción ve solo la asistencia de hoy.",
        solo_hoy_recepcion=True),
    DefinicionReporte(
        "asistencia_rango", "Asistencia", "Asistencia por rango de fechas",
        "Ingresos de un periodo con el casillero que tenía cada cliente.",
        ("rango", "sexo", "plan")),
    DefinicionReporte(
        "asistencia_cliente", "Asistencia", "Asistencia de un cliente",
        "Ingresos de un cliente en el periodo.", ("cliente", "rango")),
    DefinicionReporte(
        "asistencia_franja", "Asistencia", "Asistencia por franja horaria",
        "Ingresos por hora del día (hora de Bogotá).", ("rango", "sexo", "plan")),
    DefinicionReporte(
        "asistencia_ranking", "Asistencia", "Ranking de asistencia",
        "Clientes que más vinieron en el periodo.", ("rango", "limite", "sexo", "plan")),
    DefinicionReporte(
        "asistencia_ausentes", "Asistencia", "Clientes que no vienen hace N días",
        "Clientes activos sin ingresos en los últimos N días, con teléfono.",
        ("dias", "nunca", "sexo")),
    # Casilleros
    DefinicionReporte(
        "casilleros_lista", "Casilleros", "Casilleros",
        "Lista de casilleros por estado, zona, sexo de quien lo ocupa y situación.",
        ("estado_casillero", "zona", "sexo_ocupante", "situacion"), recepcion=True),
    DefinicionReporte(
        "casilleros_vencidos", "Casilleros", "Casilleros vencidos",
        "Casilleros ocupados con el pago vencido, con días de vencido.", ("zona",),
        recepcion=True),
    DefinicionReporte(
        "casilleros_liberar", "Casilleros", "Casilleros sugeridos para liberar",
        "Cliente inactivo o casillero vencido hace más de los días configurados.", ("zona",),
        recepcion=True),
    DefinicionReporte(
        "casilleros_dia", "Casilleros", "Casilleros asignados y liberados por día",
        "Movimientos de casilleros de una fecha.", ("dia",), recepcion=True),
    # Invitados
    DefinicionReporte(
        "invitados_visitas", "Invitados", "Visitas de invitados",
        "Visitas del periodo, opcionalmente solo las de un cliente anfitrión.",
        ("rango", "anfitrion"), recepcion=True,
        nota_recepcion="Recepción ve solo las visitas de hoy.", solo_hoy_recepcion=True),
    DefinicionReporte(
        "invitados_por_invitado", "Invitados", "Visitas por invitado",
        "Cuántas veces vino cada invitado en el periodo y en total.", ("rango",)),
    DefinicionReporte(
        "invitados_anfitriones", "Invitados", "Invitados por cliente anfitrión",
        "Clientes que trajeron invitados en el periodo.", ("rango",)),
)
DEFINICIONES = {d.clave: d for d in CATALOGO}
GRUPOS = tuple(dict.fromkeys(d.grupo for d in CATALOGO))

_ASISTENCIA = {"asistencia_dia": "dia", "asistencia_rango": "rango",
               "asistencia_cliente": "cliente", "asistencia_franja": "franja",
               "asistencia_ranking": "ranking", "asistencia_ausentes": "ausentes"}
_INVITADOS = {"invitados_visitas": "visitas", "invitados_por_invitado": "invitados",
              "invitados_anfitriones": "anfitriones"}


# --- parámetros y resultado -------------------------------------------------------

@dataclass(frozen=True)
class ParametrosReportes:
    desde: date | None = None  # días de Bogotá, incluidos ("dia" usa solo `desde`)
    hasta: date | None = None
    dias: int | None = None  # por vencer / vencidos / ausentes
    cliente_id: int | None = None
    anfitrion_id: int | None = None
    plan_id: int | None = None
    sexo: str | None = None
    metodo: str | None = None
    usuario_id: int | None = None
    concepto: str | None = None
    limite: int = 50
    incluir_nunca: bool = False
    estado_casillero: str | None = None
    zona: str | None = None
    sexo_ocupante: str | None = None
    situacion: str | None = None


@dataclass(frozen=True)
class ResultadoReporte:
    clave: str
    titulo: str
    subtitulo: str
    encabezados: tuple[str, ...]
    filas: list[tuple]
    totales: tuple | None = None  # fila de totales (misma cantidad de columnas)
    dinero: frozenset[int] = field(default_factory=frozenset)  # columnas en pesos
    resumen: str = ""


# --- servicio ---------------------------------------------------------------------

class ServicioReportes:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        pagos: ServicioPagos,
        asistencia: ServicioAsistencia,
        casilleros: ServicioCasilleros,
        invitados: ServicioInvitados,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._pagos = pagos
        self._asistencia = asistencia
        self._casilleros = casilleros
        self._invitados = invitados
        self._carpeta = carpeta_datos
        self._reloj = reloj

    # --- catálogo y listas para los filtros -------------------------------------------
    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    def disponibles(self, actual: UsuarioActual) -> list[DefinicionReporte]:
        """Reportes que puede abrir el usuario, en el orden del catálogo."""
        exigir(actual, Permiso.REPORTES_BASICOS)
        todos = actual.puede(Permiso.REPORTES_TODOS)
        return [d for d in CATALOGO if todos or d.recepcion]

    def planes(self, actual: UsuarioActual) -> list[tuple[int, str]]:
        exigir(actual, Permiso.REPORTES_BASICOS)
        with self._fabrica() as sesion:
            return [tuple(f) for f in sesion.execute(
                select(Plan.id, Plan.nombre).order_by(Plan.activo.desc(), Plan.nombre))]

    def usuarios(self, actual: UsuarioActual) -> list[tuple[int, str]]:
        """Usuarios para el filtro. Recepción solo se ve a sí misma."""
        exigir(actual, Permiso.REPORTES_BASICOS)
        if not actual.puede(Permiso.REPORTES_TODOS):
            return [(actual.id, actual.usuario)]
        with self._fabrica() as sesion:
            return [tuple(f) for f in sesion.execute(
                select(Usuario.id, Usuario.usuario).order_by(Usuario.usuario))]

    def buscar_codigo(self, actual: UsuarioActual, codigo: str) -> int:
        return self._asistencia.buscar_codigo(actual, codigo)

    # --- generar ----------------------------------------------------------------------
    def generar(
        self, actual: UsuarioActual, clave: str, p: ParametrosReportes | None = None
    ) -> ResultadoReporte:
        definicion = DEFINICIONES.get(clave)
        if definicion is None:
            raise ErrorValidacion("El reporte no existe.")
        exigir(actual, Permiso.REPORTES_BASICOS)
        if not definicion.recepcion:
            exigir(actual, Permiso.REPORTES_TODOS)
        p = p or ParametrosReportes()
        if "rango" in definicion.filtros:
            p = self._validar_rango(p)

        if clave in _ASISTENCIA:
            return self._de_asistencia(actual, clave, p)
        if clave in _INVITADOS:
            return self._de_invitados(actual, clave, p)
        if clave.startswith("casilleros_"):
            return self._de_casilleros(actual, clave, p)
        if clave == "cierre_caja":
            return self._cierre_caja(actual, p)
        if clave in ("clientes_por_vencer", "clientes_vencidos"):
            return self._vencimientos(clave, p)
        if clave == "clientes_morosos":
            return self._morosos(p)
        if clave == "clientes_mensual":
            return self._mensual(p)
        if clave == "clientes_nuevos":
            return self._nuevos(p)
        if clave == "clientes_renovaciones":
            return self._renovaciones(p)
        if clave == "clientes_bajas":
            return self._bajas(p)
        if clave == "pagos_anulados":
            return self._anulados(p)
        return self._ingresos(clave, p)

    def exportar(
        self, actual: UsuarioActual, clave: str, p: ParametrosReportes | None,
        ruta: Path | str, formato: str,
    ) -> Path:
        """Exporta a Excel ("xlsx") o PDF ("pdf"). Queda en la auditoría."""
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        rep = self.generar(actual, clave, p)
        if formato == "xlsx":
            destino = exp.exportar_excel(
                ruta, rep.titulo, rep.encabezados, rep.filas, totales=rep.totales,
                dinero=rep.dinero, subtitulo=rep.subtitulo)
        else:
            destino = exp.exportar_pdf(
                ruta, rep.titulo, rep.subtitulo, rep.encabezados, rep.filas,
                totales=rep.totales, dinero=rep.dinero)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "reporte_exportado", "reportes", usuario_id=actual.id,
                momento=self._reloj(),
                detalle={"reporte": clave, "formato": formato, "filas": len(rep.filas)},
            )
            sesion.commit()
        return Path(destino)

    def carpeta_reportes(self) -> Path:
        carpeta = (self._carpeta or cfg.carpeta_datos()) / "reportes"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    # --- auxiliares comunes -------------------------------------------------------------
    def _validar_rango(self, p: ParametrosReportes) -> ParametrosReportes:
        hoy = self.hoy()
        desde = p.desde or hoy
        hasta = p.hasta or desde
        if desde > hasta:
            raise ErrorValidacion("La fecha inicial no puede ser posterior a la final.")
        if (hasta - desde).days > RANGO_MAXIMO_DIAS:
            raise ErrorValidacion("El periodo no puede ser mayor a tres años.")
        return dataclasses.replace(p, desde=desde, hasta=hasta)

    def _encabezado(self, periodo: str, partes: list[str]) -> str:
        nombre = self._configuracion.obtener("gimnasio_nombre") or "Enforma"
        generado = self._reloj().astimezone(cfg.ZONA_HORARIA).strftime("%d/%m/%Y %H:%M")
        return " · ".join([nombre, *([periodo] if periodo else []), *partes,
                           f"generado el {generado}"])

    @staticmethod
    def _periodo(desde: date, hasta: date) -> str:
        return (formato_fecha(desde) if desde == hasta
                else f"del {formato_fecha(desde)} al {formato_fecha(hasta)}")

    def _filtros_texto(self, p: ParametrosReportes, usados: tuple[str, ...]) -> list[str]:
        partes = []
        with self._fabrica() as sesion:
            if "plan" in usados and p.plan_id:
                partes.append(f"plan {sesion.get(Plan, p.plan_id).nombre}")
            if "usuario" in usados and p.usuario_id:
                partes.append(f"usuario {sesion.get(Usuario, p.usuario_id).usuario}")
        if "sexo" in usados and p.sexo:
            partes.append(f"sexo {SEXOS.get(p.sexo, p.sexo).lower()}")
        if "metodo" in usados and p.metodo:
            partes.append(METODOS.get(p.metodo, p.metodo).lower())
        if "concepto" in usados and p.concepto:
            partes.append(f"concepto {CONCEPTOS.get(p.concepto, p.concepto).lower()}")
        return partes

    @staticmethod
    def _casilleros_activos(sesion: Session) -> dict[int, str]:
        return dict(sesion.execute(
            select(CasilleroAsignacion.cliente_id, Casillero.numero)
            .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
            .where(CasilleroAsignacion.fecha_liberacion.is_(None))
        ).all())

    @staticmethod
    def _saldos_clientes(sesion: Session, ids: list[int]) -> dict[int, int]:
        """Saldo pendiente de cada cliente (membresías no anuladas)."""
        if not ids:
            return {}
        saldos: dict[int, int] = defaultdict(int)
        for cliente_id, saldo in sesion.execute(
            select(Membresia.cliente_id, _saldo_membresia())
            .where(Membresia.cliente_id.in_(ids), Membresia.estado == "activa")
        ):
            if saldo > 0:
                saldos[cliente_id] += int(saldo)
        return saldos

    # --- clientes ---------------------------------------------------------------------
    def _vencimientos(self, clave: str, p: ParametrosReportes) -> ResultadoReporte:
        hoy = self.hoy()
        por_vencer = clave == "clientes_por_vencer"
        dias = p.dias if p.dias is not None else (
            self._configuracion.obtener("dias_por_vencer") if por_vencer else 0)
        if dias < 0 or dias > 3650:
            raise ErrorValidacion("Los días deben estar entre 0 y 3.650.")
        expr = _Expresiones()
        condiciones = [Cliente.estado == "activo"]
        if por_vencer:
            condiciones += [expr.fin >= hoy, expr.fin <= hoy + timedelta(days=dias)]
            orden = expr.fin.asc()
        else:
            condiciones.append(expr.fin < hoy)
            if dias:
                condiciones.append(expr.fin >= hoy - timedelta(days=dias))
            orden = expr.fin.desc()
        if p.sexo:
            condiciones.append(Cliente.sexo == p.sexo)
        if p.plan_id:
            condiciones.append(expr.plan_id == p.plan_id)
        with self._fabrica() as sesion:
            datos = sesion.execute(
                select(Cliente.id, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                       expr.telefono.label("telefono"), expr.plan.label("plan"),
                       expr.fin.label("fin"))
                .where(*condiciones).order_by(orden, Cliente.apellidos, Cliente.nombres)
            ).all()
            saldos = self._saldos_clientes(sesion, [r.id for r in datos])
            casilleros = self._casilleros_activos(sesion)
        filas = []
        for r in datos:
            fin = _como_fecha(r.fin)
            restantes = (fin - hoy).days
            filas.append((
                r.codigo, f"{r.nombres} {r.apellidos}", r.telefono or "", r.plan or "", fin,
                restantes if por_vencer else -restantes, saldos.get(r.id, 0),
                casilleros.get(r.id, ""),
            ))
        partes = self._filtros_texto(p, ("plan", "sexo"))
        if por_vencer:
            titulo = f"Clientes por vencer en los próximos {dias} días"
            if dias == 0:
                titulo = "Clientes que vencen hoy"
            columnas = ("Código", "Cliente", "Teléfono", "Plan", "Vence", "Días restantes",
                        "Saldo", "Casillero")
        else:
            titulo = ("Clientes vencidos" if not dias
                      else f"Clientes vencidos en los últimos {dias} días")
            columnas = ("Código", "Cliente", "Teléfono", "Plan", "Venció", "Días vencido",
                        "Saldo", "Casillero")
        resumen = f"{_n(len(filas))} clientes"
        con_saldo = sum(1 for f in filas if f[6])
        if con_saldo:
            resumen += f" · {con_saldo} con saldo pendiente"
        return ResultadoReporte(
            clave, titulo, self._encabezado(f"al {formato_fecha(hoy)}", [resumen, *partes]),
            columnas, filas, dinero=frozenset({6}), resumen=resumen,
        )

    def _morosos(self, p: ParametrosReportes) -> ResultadoReporte:
        pagado = _pagado_membresia()
        saldo = Membresia.precio_pactado - pagado
        expr = _Expresiones()
        condiciones = [Membresia.estado == "activa", saldo > 0]
        if p.plan_id:
            condiciones.append(Membresia.plan_id == p.plan_id)
        if p.sexo:
            condiciones.append(Cliente.sexo == p.sexo)
        with self._fabrica() as sesion:
            datos = sesion.execute(
                select(Cliente.codigo, Cliente.nombres, Cliente.apellidos, Cliente.estado,
                       expr.telefono.label("telefono"), Plan.nombre.label("plan"),
                       Membresia.fecha_inicio, Membresia.fecha_fin, Membresia.precio_pactado,
                       pagado.label("pagado"))
                .join(Cliente, Cliente.id == Membresia.cliente_id)
                .join(Plan, Plan.id == Membresia.plan_id)
                .where(*condiciones)
                .order_by(Cliente.apellidos, Cliente.nombres, Membresia.fecha_inicio)
            ).all()
        filas = [
            (r.codigo, f"{r.nombres} {r.apellidos}", r.telefono or "",
             ESTADOS_CLIENTE.get(r.estado, r.estado), r.plan, _como_fecha(r.fecha_inicio),
             _como_fecha(r.fecha_fin), r.precio_pactado, int(r.pagado),
             r.precio_pactado - int(r.pagado))
            for r in datos
        ]
        total = sum(f[9] for f in filas)
        clientes = len({f[0] for f in filas})
        resumen = f"{_n(clientes)} clientes · {_n(len(filas))} membresías · saldo total {_pesos(total)}"
        return ResultadoReporte(
            "clientes_morosos", "Clientes morosos (saldo pendiente)",
            self._encabezado(f"al {formato_fecha(self.hoy())}",
                             [resumen, *self._filtros_texto(p, ("plan", "sexo"))]),
            ("Código", "Cliente", "Teléfono", "Estado", "Plan", "Inicio", "Fin", "Valor",
             "Pagado", "Saldo"),
            filas,
            totales=("Total", "", "", "", "", "", "", sum(f[7] for f in filas),
                     sum(f[8] for f in filas), total),
            dinero=frozenset({7, 8, 9}), resumen=resumen,
        )

    def _condiciones_movimiento(self, desde: date, hasta: date):
        """Condiciones de nuevos, renovaciones, inactivados y vencidos sin renovar."""
        inicio, fin = inicio_dia_utc(desde), inicio_dia_utc(hasta + timedelta(days=1))
        nuevos = [Cliente.creado_en >= inicio, Cliente.creado_en < fin]
        renovaciones = [Membresia.estado == "activa", Membresia.creado_en >= inicio,
                        Membresia.creado_en < fin, _es_renovacion()]
        inactivados = [Auditoria.accion == "cliente_inactivado",
                       Auditoria.entidad == "clientes",
                       Auditoria.fecha_hora >= inicio, Auditoria.fecha_hora < fin]
        # Vencidos sin renovar: clientes activos cuya última membresía terminó en el
        # periodo (y antes de hoy). Los inactivados se cuentan aparte.
        ultima_fin = _Expresiones().fin
        tope = min(hasta, self.hoy() - timedelta(days=1))
        vencidos = [Cliente.estado == "activo", ultima_fin >= desde, ultima_fin <= tope]
        return nuevos, renovaciones, inactivados, vencidos, ultima_fin, tope >= desde

    def _mensual(self, p: ParametrosReportes) -> ResultadoReporte:
        c_nuevos, c_renov, c_inact, c_venc, ultima_fin, hay_vencidos = (
            self._condiciones_movimiento(p.desde, p.hasta))
        desfase = f"{_desfase_horas()} hours"
        conteos: list[dict[str, int]] = []
        with self._fabrica() as sesion:
            for columna, condiciones, mes in (
                (Cliente.id, c_nuevos, func.strftime("%Y-%m", Cliente.creado_en, desfase)),
                (Membresia.id, c_renov, func.strftime("%Y-%m", Membresia.creado_en, desfase)),
                (Auditoria.id, c_inact, func.strftime("%Y-%m", Auditoria.fecha_hora, desfase)),
            ):
                conteos.append(dict(sesion.execute(
                    select(mes, func.count(columna)).where(*condiciones).group_by(mes)).all()))
            mes_fin = func.strftime("%Y-%m", ultima_fin)
            conteos.append(dict(sesion.execute(
                select(mes_fin, func.count(Cliente.id)).where(*c_venc).group_by(mes_fin)
            ).all()) if hay_vencidos else {})
        filas = []
        actual = date(p.desde.year, p.desde.month, 1)
        while actual <= p.hasta:
            llave = f"{actual:%Y-%m}"
            n, ren, ina, ven = (c.get(llave, 0) for c in conteos)
            filas.append((f"{MESES[actual.month - 1].capitalize()} {actual.year}",
                          n, ren, ina, ven, n - ina - ven))
            actual = (actual + timedelta(days=32)).replace(day=1)
        totales = ("Total", *[sum(f[i] for f in filas) for i in range(1, 6)])
        resumen = (f"{_n(totales[1])} nuevos · {_n(totales[2])} renovaciones · "
                   f"{_n(totales[3] + totales[4])} bajas")
        return ResultadoReporte(
            "clientes_mensual", "Nuevos, renovaciones y bajas por mes",
            self._encabezado(self._periodo(p.desde, p.hasta), [resumen]),
            ("Mes", "Clientes nuevos", "Renovaciones", "Bajas: inactivados",
             "Bajas: vencidos sin renovar", "Balance (nuevos − bajas)"),
            filas, totales=totales, resumen=resumen,
        )

    def _nuevos(self, p: ParametrosReportes) -> ResultadoReporte:
        expr = _Expresiones()
        condiciones = self._condiciones_movimiento(p.desde, p.hasta)[0]
        if p.sexo:
            condiciones.append(Cliente.sexo == p.sexo)
        with self._fabrica() as sesion:
            datos = sesion.execute(
                select(Cliente.creado_en, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                       Cliente.sexo, expr.telefono.label("telefono"),
                       _primer_plan().label("plan"), Usuario.usuario.label("registro"))
                .outerjoin(Usuario, Usuario.id == Cliente.creado_por)
                .where(*condiciones).order_by(Cliente.creado_en)
            ).all()
        filas = [
            (_dia_local(r.creado_en), r.codigo, f"{r.nombres} {r.apellidos}",
             SEXOS.get(r.sexo, r.sexo), r.telefono or "", r.plan or "Sin membresía",
             r.registro or "")
            for r in datos
        ]
        sin = sum(1 for f in filas if f[5] == "Sin membresía")
        resumen = f"{_n(len(filas))} clientes nuevos · {_n(sin)} sin membresía"
        return ResultadoReporte(
            "clientes_nuevos", "Clientes nuevos",
            self._encabezado(self._periodo(p.desde, p.hasta),
                             [resumen, *self._filtros_texto(p, ("sexo",))]),
            ("Registro", "Código", "Cliente", "Sexo", "Teléfono", "Primera membresía",
             "Registró"),
            filas, resumen=resumen,
        )

    def _renovaciones(self, p: ParametrosReportes) -> ResultadoReporte:
        condiciones = list(self._condiciones_movimiento(p.desde, p.hasta)[1])
        if p.plan_id:
            condiciones.append(Membresia.plan_id == p.plan_id)
        with self._fabrica() as sesion:
            datos = sesion.execute(
                select(Membresia.creado_en, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                       Plan.nombre.label("plan"), Membresia.fecha_inicio, Membresia.fecha_fin,
                       Membresia.precio_pactado, Usuario.usuario.label("registro"))
                .join(Cliente, Cliente.id == Membresia.cliente_id)
                .join(Plan, Plan.id == Membresia.plan_id)
                .outerjoin(Usuario, Usuario.id == Membresia.creado_por)
                .where(*condiciones).order_by(Membresia.creado_en, Membresia.id)
            ).all()
        filas = [
            (_dia_local(r.creado_en), r.codigo, f"{r.nombres} {r.apellidos}", r.plan,
             _como_fecha(r.fecha_inicio), _como_fecha(r.fecha_fin), r.precio_pactado,
             r.registro or "")
            for r in datos
        ]
        total = sum(f[6] for f in filas)
        resumen = f"{_n(len(filas))} renovaciones · {_n(len({f[1] for f in filas}))} clientes"
        return ResultadoReporte(
            "clientes_renovaciones", "Renovaciones",
            self._encabezado(self._periodo(p.desde, p.hasta),
                             [resumen, *self._filtros_texto(p, ("plan",))]),
            ("Fecha", "Código", "Cliente", "Plan", "Inicio", "Fin", "Valor", "Registró"),
            filas, totales=("Total", "", "", "", "", "", total, ""),
            dinero=frozenset({6}), resumen=resumen,
        )

    def _bajas(self, p: ParametrosReportes) -> ResultadoReporte:
        expr = _Expresiones()
        _, _, c_inact, c_venc, ultima_fin, hay_vencidos = self._condiciones_movimiento(
            p.desde, p.hasta)
        with self._fabrica() as sesion:
            inactivados = sesion.execute(
                select(Auditoria.fecha_hora, Auditoria.detalle_json, Cliente.codigo,
                       Cliente.nombres, Cliente.apellidos, expr.telefono.label("telefono"))
                .join(Cliente, Cliente.id == Auditoria.entidad_id)
                .where(*c_inact).order_by(Auditoria.fecha_hora)
            ).all()
            vencidos = sesion.execute(
                select(Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                       ultima_fin.label("fin"), expr.telefono.label("telefono"),
                       expr.plan.label("plan"))
                .where(*c_venc).order_by(ultima_fin)
            ).all() if hay_vencidos else []
        filas = []
        for r in inactivados:
            motivo = ""
            if r.detalle_json:
                try:
                    motivo = json.loads(r.detalle_json).get("motivo", "")
                except (ValueError, AttributeError):
                    motivo = ""
            filas.append((_dia_local(r.fecha_hora), r.codigo, f"{r.nombres} {r.apellidos}",
                          r.telefono or "", "Inactivado", motivo))
        for r in vencidos:
            filas.append((_como_fecha(r.fin), r.codigo, f"{r.nombres} {r.apellidos}",
                          r.telefono or "", "Venció sin renovar",
                          f"Último plan: {r.plan or '—'}"))
        filas.sort(key=lambda f: (f[0], f[1]))
        resumen = (f"{_n(len(inactivados))} inactivados · "
                   f"{_n(len(vencidos))} vencidos sin renovar")
        return ResultadoReporte(
            "clientes_bajas", "Bajas de clientes",
            self._encabezado(self._periodo(p.desde, p.hasta), [resumen]),
            ("Fecha", "Código", "Cliente", "Teléfono", "Tipo de baja", "Detalle"),
            filas, resumen=resumen,
        )

    # --- ingresos ---------------------------------------------------------------------
    def _consultar_pagos(self, sesion: Session, p: ParametrosReportes, anulados: bool):
        anulo = aliased(Usuario)
        consulta = (
            select(Pago.id, Pago.consecutivo, Pago.fecha_hora, Pago.concepto, Pago.metodo,
                   Pago.referencia, Pago.monto, Pago.motivo_anulacion, Pago.anulado_en,
                   Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                   Usuario.usuario.label("usuario"), Plan.nombre.label("plan"),
                   anulo.usuario.label("anulo"))
            .join(Cliente, Cliente.id == Pago.cliente_id)
            .join(Usuario, Usuario.id == Pago.usuario_id)
            .outerjoin(Membresia, Membresia.id == Pago.membresia_id)
            .outerjoin(Plan, Plan.id == Membresia.plan_id)
            .outerjoin(anulo, anulo.id == Pago.anulado_por)
            .where(*self._condiciones_pagos(p, anulados))
            .order_by(Pago.fecha_hora, Pago.id)
        )
        return sesion.execute(consulta).all()

    def _agregar_pagos(self, sesion: Session, p: ParametrosReportes, clave: str) -> list:
        """Pagos válidos agrupados en la base (evita traer miles de filas).

        Solo une las tablas que el reporte necesita: con un año de pagos, cada unión
        de más cuesta cerca de 100 ms.
        """
        por_plan = clave == "ingresos_plan"
        if clave == "ingresos_dia":
            llave = func.date(Pago.fecha_hora, f"{_desfase_horas()} hours")
        elif clave == "ingresos_usuario":
            llave = Pago.usuario_id
        else:
            llave = Pago.concepto
        plan = Membresia.plan_id if por_plan else Pago.concepto
        consulta = (
            select(llave.label("llave"), Pago.concepto, plan.label("plan"), Pago.metodo,
                   Pago.anulado, func.count(Pago.id).label("cantidad"),
                   func.sum(Pago.monto).label("total"))
            # Válidos y anulados en una sola pasada; los anulados solo van al resumen.
            .where(*self._condiciones_pagos(p, anulados=None))
            .group_by(llave, Pago.concepto, plan, Pago.metodo, Pago.anulado)
        )
        if por_plan or p.plan_id:
            consulta = consulta.outerjoin(Membresia, Membresia.id == Pago.membresia_id)
        filas = sesion.execute(consulta).all()
        nombres: dict[int, str] = {}
        if por_plan:
            nombres = dict(sesion.execute(select(Plan.id, Plan.nombre)).all())
        elif clave == "ingresos_usuario":
            nombres = dict(sesion.execute(select(Usuario.id, Usuario.usuario)).all())
        return [
            _Agregado(
                llave=nombres.get(r.llave, str(r.llave)) if clave == "ingresos_usuario"
                else r.llave,
                concepto=r.concepto, plan=nombres.get(r.plan) if por_plan else None,
                metodo=r.metodo, cantidad=r.cantidad, total=int(r.total or 0),
                anulado=bool(r.anulado),
            )
            for r in filas
        ]

    @staticmethod
    def _condiciones_pagos(p: ParametrosReportes, anulados: bool | None) -> list:
        """`anulados`: True solo anulados, False solo válidos, None todos."""
        condiciones = [Pago.fecha_hora >= inicio_dia_utc(p.desde),
                       Pago.fecha_hora < inicio_dia_utc(p.hasta + timedelta(days=1))]
        if anulados is not None:
            condiciones.append(Pago.anulado.is_(anulados))
        if p.metodo:
            condiciones.append(Pago.metodo == p.metodo)
        if p.usuario_id:
            condiciones.append(Pago.usuario_id == p.usuario_id)
        if p.concepto:
            condiciones.append(Pago.concepto == p.concepto)
        if p.plan_id:
            condiciones.append(Membresia.plan_id == p.plan_id)
        return condiciones

    def _ingresos(self, clave: str, p: ParametrosReportes) -> ResultadoReporte:
        if p.metodo and p.metodo not in METODOS:
            raise ErrorValidacion("Método de pago no válido.")
        if p.concepto and p.concepto not in CONCEPTOS:
            raise ErrorValidacion("Concepto no válido.")
        detalle = clave == "ingresos_detalle"
        with self._fabrica() as sesion:
            if detalle:
                pagos = self._consultar_pagos(sesion, p, anulados=False)
                anulados = sesion.execute(
                    select(func.count(Pago.id), func.coalesce(func.sum(Pago.monto), 0))
                    .outerjoin(Membresia, Membresia.id == Pago.membresia_id)
                    .where(*self._condiciones_pagos(p, anulados=True))
                ).one()
            else:
                agregados = self._agregar_pagos(sesion, p, clave)
                pagos = [a for a in agregados if not a.anulado]
                anulados = (sum(a.cantidad for a in agregados if a.anulado),
                            sum(a.total for a in agregados if a.anulado))
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
        if detalle:
            total, cantidad = sum(r.monto for r in pagos), len(pagos)
        else:
            total = sum(int(r.total) for r in pagos)
            cantidad = sum(r.cantidad for r in pagos)
        resumen = f"{_n(cantidad)} pagos · total {_pesos(total)}"
        if anulados[0]:
            resumen += f" · {_n(anulados[0])} anulados por {_pesos(int(anulados[1]))} (no suman)"
        subtitulo = self._encabezado(self._periodo(p.desde, p.hasta),
                                     [resumen, *self._filtros_texto(p, _FILTROS_PAGOS)])
        metodos = list(METODOS)
        definicion = DEFINICIONES[clave]

        if detalle:
            filas = [
                (r.fecha_hora, numero_recibo(prefijo, r.consecutivo), r.codigo,
                 f"{r.nombres} {r.apellidos}", CONCEPTOS.get(r.concepto, r.concepto),
                 r.plan or "", METODOS.get(r.metodo, r.metodo), r.referencia or "",
                 r.usuario, r.monto)
                for r in pagos
            ]
            return ResultadoReporte(
                clave, definicion.titulo, subtitulo,
                ("Fecha y hora", "Recibo", "Código", "Cliente", "Concepto", "Plan", "Método",
                 "Referencia", "Registró", "Monto"),
                filas, totales=("Total", "", "", "", "", "", "", "", "", total),
                dinero=frozenset({9}), resumen=resumen,
            )

        if clave in ("ingresos_dia", "ingresos_usuario"):
            grupos: dict[object, dict[str, int]] = {}
            cantidades: dict[object, int] = defaultdict(int)
            for r in pagos:
                llave = _como_fecha(r.llave) if clave == "ingresos_dia" else r.llave
                grupos.setdefault(llave, defaultdict(int))[r.metodo] += int(r.total)
                cantidades[llave] += r.cantidad
            filas = [
                (llave, cantidades[llave], *[g.get(m, 0) for m in metodos],
                 sum(g.values()))
                for llave, g in sorted(grupos.items(), key=lambda x: x[0])
            ]
            totales = ("Total", cantidad,
                       *[sum(f[2 + i] for f in filas) for i in range(len(metodos))], total)
            return ResultadoReporte(
                clave, definicion.titulo, subtitulo,
                ("Día" if clave == "ingresos_dia" else "Usuario", "Pagos",
                 *[METODOS[m] for m in metodos], "Total"),
                filas, totales=totales,
                dinero=frozenset(range(2, 3 + len(metodos))), resumen=resumen,
            )

        # Por método o por plan: cantidad, total y porcentaje.
        sumas: dict[str, int] = defaultdict(int)
        cantidades = defaultdict(int)
        for r in pagos:
            if clave == "ingresos_metodo":
                llave = METODOS.get(r.metodo, r.metodo)
            elif r.concepto == "membresia":
                llave = f"Membresía {r.plan}" if r.plan else "Membresía"
            else:
                llave = CONCEPTOS.get(r.concepto, r.concepto)
            sumas[llave] += int(r.total)
            cantidades[llave] += r.cantidad
        if clave == "ingresos_metodo":
            for m in metodos:  # siempre los tres métodos, aunque sea en cero
                sumas.setdefault(METODOS[m], 0)
            orden = [METODOS[m] for m in metodos]
            llaves = orden + [k for k in sumas if k not in orden]
        else:
            llaves = sorted(sumas, key=lambda k: (-sumas[k], k))
        filas = [
            (k, cantidades.get(k, 0), sumas[k],
             round(sumas[k] * 100 / total, 1) if total else 0.0)
            for k in llaves
        ]
        return ResultadoReporte(
            clave, definicion.titulo, subtitulo,
            ("Método" if clave == "ingresos_metodo" else "Plan o concepto", "Pagos", "Total",
             "% del total"),
            filas, totales=("Total", cantidad, total, 100.0 if total else 0.0),
            dinero=frozenset({2}), resumen=resumen,
        )

    def _anulados(self, p: ParametrosReportes) -> ResultadoReporte:
        with self._fabrica() as sesion:
            pagos = self._consultar_pagos(sesion, ParametrosReportes(
                desde=p.desde, hasta=p.hasta, usuario_id=p.usuario_id), anulados=True)
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
        filas = [
            (r.fecha_hora, numero_recibo(prefijo, r.consecutivo), r.codigo,
             f"{r.nombres} {r.apellidos}", CONCEPTOS.get(r.concepto, r.concepto),
             METODOS.get(r.metodo, r.metodo), r.usuario, r.monto, r.anulado_en,
             r.anulo or "", r.motivo_anulacion or "")
            for r in pagos
        ]
        total = sum(f[7] for f in filas)
        resumen = f"{_n(len(filas))} pagos anulados por {_pesos(total)}"
        return ResultadoReporte(
            "pagos_anulados", "Pagos anulados",
            self._encabezado(self._periodo(p.desde, p.hasta),
                             [resumen, *self._filtros_texto(p, ("usuario",))]),
            ("Fecha del pago", "Recibo", "Código", "Cliente", "Concepto", "Método",
             "Registró", "Monto", "Anulado el", "Anuló", "Motivo"),
            filas, totales=("Total", "", "", "", "", "", "", total, "", "", ""),
            dinero=frozenset({7}), resumen=resumen,
        )

    def _cierre_caja(self, actual: UsuarioActual, p: ParametrosReportes) -> ResultadoReporte:
        cierre = self._pagos.cierre_caja(actual, p.desde or self.hoy(), p.usuario_id)
        filas = [
            (f.fecha_hora.astimezone(cfg.ZONA_HORARIA).strftime("%H:%M"), f.recibo,
             f.cliente_codigo, f.cliente_nombre, CONCEPTOS.get(f.concepto, f.concepto),
             METODOS.get(f.metodo, f.metodo), f.referencia, f.usuario,
             f.monto, "Anulado" if f.anulado else "")
            for f in cierre.filas
        ]
        por_metodo = " · ".join(f"{METODOS[m]} {_pesos(v)}" for m, v in cierre.por_metodo.items())
        resumen = f"{_n(cierre.cantidad)} pagos · total {_pesos(cierre.total)} · {por_metodo}"
        if cierre.anulados_cantidad:
            resumen += (f" · {cierre.anulados_cantidad} anulados por "
                        f"{_pesos(cierre.anulados_monto)} (no suman)")
        partes = [resumen]
        if cierre.usuario_id:
            with self._fabrica() as sesion:
                usuario = sesion.get(Usuario, cierre.usuario_id)
                partes.append(f"usuario {usuario.usuario if usuario else cierre.usuario_id}")
        return ResultadoReporte(
            "cierre_caja", f"Cierre de caja del {formato_fecha(cierre.dia)}",
            self._encabezado("", partes),
            ("Hora", "Recibo", "Código", "Cliente", "Concepto", "Método", "Referencia",
             "Registró", "Monto", "Estado"),
            filas, totales=("Total", "", "", "", "", "", "", "", cierre.total, ""),
            dinero=frozenset({8}), resumen=resumen,
        )

    # --- reportes de otros módulos ------------------------------------------------------
    def _de_asistencia(self, actual, clave, p: ParametrosReportes) -> ResultadoReporte:
        tipo = _ASISTENCIA[clave]
        rep = self._asistencia.reporte(actual, ParametrosReporte(
            tipo=tipo, desde=p.desde, hasta=p.hasta, cliente_id=p.cliente_id,
            dias=p.dias if p.dias is not None else 30, limite=p.limite,
            incluir_nunca=p.incluir_nunca, sexo=p.sexo,
            plan_id=p.plan_id if tipo != "ausentes" else None,
        ))
        return ResultadoReporte(clave, rep.titulo, rep.subtitulo, rep.encabezados, rep.filas,
                                resumen=rep.resumen)

    def _de_invitados(self, actual, clave, p: ParametrosReportes) -> ResultadoReporte:
        rep = self._invitados.reporte(actual, ParametrosReporteInvitados(
            tipo=_INVITADOS[clave], desde=p.desde, hasta=p.hasta,
            anfitrion_id=p.anfitrion_id if clave == "invitados_visitas" else None,
        ))
        return ResultadoReporte(clave, rep.titulo, rep.subtitulo, rep.encabezados, rep.filas,
                                resumen=rep.resumen)

    def _de_casilleros(self, actual, clave, p: ParametrosReportes) -> ResultadoReporte:
        if clave == "casilleros_dia":
            listado = self._casilleros.listado(actual, "dia", dia=p.desde or self.hoy())
        else:
            if p.estado_casillero and p.estado_casillero not in ESTADOS_CASILLERO:
                raise ErrorValidacion("Estado de casillero no válido.")
            if p.zona and p.zona not in ZONAS:
                raise ErrorValidacion("Zona no válida.")
            situacion = {"casilleros_vencidos": "vencidos",
                         "casilleros_liberar": "sugerido_liberar"}.get(clave, p.situacion)
            if situacion and situacion not in SITUACIONES:
                raise ErrorValidacion("Situación no válida.")
            filtros = FiltrosCasilleros(
                estado=p.estado_casillero if clave == "casilleros_lista" else None,
                zona=p.zona,
                sexo_cliente=p.sexo_ocupante if clave == "casilleros_lista" else None,
                situacion=situacion,
            )
            listado = self._casilleros.listado(actual, "estado", filtros)
        return ResultadoReporte(clave, listado.titulo, listado.subtitulo, listado.encabezados,
                                listado.filas, resumen=f"{len(listado.filas)} filas")


# --- funciones auxiliares -------------------------------------------------------------

@dataclass(frozen=True)
class _Agregado:
    llave: object
    concepto: str
    plan: str | None
    metodo: str
    cantidad: int
    total: int
    anulado: bool = False


def _pagado_membresia():
    """Lo pagado (sin anulados) de la membresía de la fila. Usa ix_pagos_membresia_id."""
    return (
        select(func.coalesce(func.sum(Pago.monto), 0))
        .where(Pago.membresia_id == Membresia.id, Pago.anulado.is_(False))
        .correlate(Membresia)
        .scalar_subquery()
    )


def _es_renovacion():
    """La membresía de la fila no es la primera (no anulada) de su cliente."""
    anterior = aliased(Membresia)
    return exists().where(
        anterior.cliente_id == Membresia.cliente_id,
        anterior.estado == "activa",
        or_(anterior.fecha_inicio < Membresia.fecha_inicio,
            and_(anterior.fecha_inicio == Membresia.fecha_inicio, anterior.id < Membresia.id)),
    ).correlate(Membresia)


def _primer_plan():
    """Plan de la primera membresía (no anulada) del cliente de la fila."""
    return (
        select(Plan.nombre)
        .join(Membresia, Membresia.plan_id == Plan.id)
        .where(Membresia.cliente_id == Cliente.id, Membresia.estado == "activa")
        .order_by(Membresia.fecha_inicio, Membresia.id)
        .limit(1)
        .correlate(Cliente)
        .scalar_subquery()
    )


def _saldo_membresia():
    return Membresia.precio_pactado - _pagado_membresia()


def _como_fecha(valor) -> date | None:
    if valor is None or isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _dia_local(valor: datetime) -> date:
    return valor.astimezone(cfg.ZONA_HORARIA).date()


def _n(valor: int) -> str:
    """5977 -> '5.977'."""
    return f"{int(valor):,}".replace(",", ".")


def _pesos(valor: int) -> str:
    from gimnasio.formato import pesos

    return pesos(valor)
