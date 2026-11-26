"""Pruebas del módulo Reportes (sección 3.8): permisos de Recepción vs administrador,
clientes por vencer, vencidos, morosos, nuevos, renovaciones, bajas, ingresos por método,
usuario, plan y día, pagos anulados, cierre de caja, reportes de otros módulos y
exportación a Excel y PDF con totales."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria
from gimnasio.reportes.exportar import exportar_excel
from gimnasio.servicios.clientes import DatosCliente
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import DatosPago
from gimnasio.servicios.reportes import CATALOGO, DEFINICIONES, ParametrosReportes
from gimnasio.ui.reportes import periodo

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá
P = ParametrosReportes


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def _cliente(servicios, admin, documento, nombres, telefono="", sexo="F"):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento=documento, nombres=nombres, apellidos="Prueba",
        sexo=sexo, telefonos=[telefono] if telefono else [],
    )).id


@pytest.fixture
def escenario(servicios, admin, recepcion):
    """Cuatro clientes registrados hoy:

    - A: mensual del 01/11 al 30/11 pagado en efectivo (vence en 4 días).
    - B: mensual del 01/10 al 30/10 con abono de 50.000 por tarjeta (registró Recepción).
    - C: septiembre y octubre (la segunda es renovación), pagadas por transferencia.
    - D: sin membresía, inactivado por el admin.
    Además un pago "otro" de 10.000 anulado.
    """
    pagos = servicios.pagos
    mensual = servicios.planes.crear(admin, "Mensual", 30, 120_000).id
    a = _cliente(servicios, admin, "100001", "Ana", "3001111111")
    b = _cliente(servicios, admin, "100002", "Beatriz", "3002222222")
    c = _cliente(servicios, admin, "100003", "Carla", "3003333333", sexo="M")
    d = _cliente(servicios, admin, "100004", "Diana")
    pagos.registrar_membresia(admin, a, mensual, fecha_inicio=date(2026, 11, 1),
                              pago=DatosPago(120_000))
    memb_b = pagos.registrar_membresia(admin, b, mensual, fecha_inicio=date(2026, 10, 1))
    pagos.registrar_pago(recepcion, b, DatosPago(50_000, "tarjeta", "VOUCHER-1"),
                         membresia_id=memb_b.id)
    for inicio in (date(2026, 9, 1), date(2026, 10, 1)):
        pagos.registrar_membresia(admin, c, mensual, fecha_inicio=inicio,
                                  pago=DatosPago(120_000, "transferencia", "TRF-1"))
    anulado = pagos.registrar_pago(admin, a, DatosPago(10_000), concepto="otro")
    pagos.anular_pago(admin, anulado.id, "Cobrado por error")
    servicios.clientes.inactivar(admin, d, "Se mudó de ciudad")
    return {"a": a, "b": b, "c": c, "d": d, "mensual": mensual}


def _columna(rep, nombre):
    i = rep.encabezados.index(nombre)
    return [f[i] for f in rep.filas]


# --- catálogo y permisos -----------------------------------------------------------------

def test_catalogo_completo_seccion_3_8():
    claves = set(DEFINICIONES)
    for clave in ("clientes_por_vencer", "clientes_vencidos", "clientes_morosos",
                  "ingresos_metodo", "ingresos_usuario", "ingresos_plan", "ingresos_detalle",
                  "cierre_caja", "clientes_mensual", "clientes_bajas", "clientes_renovaciones",
                  "asistencia_dia", "casilleros_lista", "invitados_visitas"):
        assert clave in claves
    assert len(claves) == len(CATALOGO)  # sin claves repetidas


def test_recepcion_ve_solo_los_basicos(servicios, admin, recepcion):
    disponibles = {d.clave for d in servicios.reportes.disponibles(recepcion)}
    assert disponibles == {
        "clientes_por_vencer", "asistencia_dia", "casilleros_lista",
        "casilleros_vencidos", "casilleros_liberar", "casilleros_dia", "invitados_visitas",
    }
    assert len(servicios.reportes.disponibles(admin)) == len(CATALOGO)


@pytest.mark.parametrize("clave", [
    "ingresos_detalle", "ingresos_metodo", "ingresos_usuario", "ingresos_plan", "ingresos_dia",
    "pagos_anulados", "clientes_vencidos", "clientes_morosos", "clientes_mensual",
    "clientes_bajas", "asistencia_rango", "invitados_anfitriones",
    # Recepción ve su cierre en el módulo Pagos, con la clave de un administrador.
    "cierre_caja",
])
def test_recepcion_no_puede_generar_reportes_de_admin(servicios, recepcion, clave):
    """El permiso se valida en el servicio, no solo ocultando el reporte en pantalla."""
    with pytest.raises(ErrorPermiso):
        servicios.reportes.generar(recepcion, clave, P())
    with pytest.raises(ErrorPermiso):
        servicios.reportes.exportar(recepcion, clave, P(), "x.xlsx", "xlsx")


def test_recepcion_limitada_al_dia_de_hoy(servicios, admin, recepcion, escenario):
    rep = servicios.reportes
    ayer = HOY - timedelta(days=1)
    with pytest.raises(ErrorPermiso):
        rep.generar(recepcion, "asistencia_dia", P(desde=ayer))
    with pytest.raises(ErrorPermiso):
        rep.generar(recepcion, "invitados_visitas", P(desde=ayer, hasta=HOY))
    # Su propio cierre de hoy: solo sus pagos (servicio de Pagos, ver test_pagos).
    cierre = servicios.pagos.cierre_caja(recepcion)
    assert [f.usuario for f in cierre.filas] == ["rita"] and cierre.total == 50_000
    assert rep.usuarios(recepcion) == [(recepcion.id, "rita")]
    with pytest.raises(ErrorPermiso):
        rep.generar(None, "clientes_por_vencer", P())


def test_reporte_inexistente_y_rango_invalido(servicios, admin):
    rep = servicios.reportes
    with pytest.raises(ErrorValidacion):
        rep.generar(admin, "no_existe", P())
    with pytest.raises(ErrorValidacion):
        rep.generar(admin, "ingresos_metodo", P(desde=HOY, hasta=HOY - timedelta(days=1)))
    with pytest.raises(ErrorValidacion):
        rep.generar(admin, "ingresos_metodo", P(desde=date(2020, 1, 1), hasta=HOY))
    with pytest.raises(ErrorValidacion):
        rep.generar(admin, "ingresos_metodo", P(metodo="bitcoin"))
    with pytest.raises(ErrorValidacion):
        rep.exportar(admin, "ingresos_metodo", P(), "x.doc", "doc")


# --- clientes -----------------------------------------------------------------------------

def test_por_vencer_con_telefono_tambien_para_recepcion(servicios, recepcion, escenario):
    rep = servicios.reportes.generar(recepcion, "clientes_por_vencer", P(dias=5))
    assert _columna(rep, "Cliente") == ["Ana Prueba"]
    assert _columna(rep, "Teléfono") == ["3001111111"]
    assert _columna(rep, "Vence") == [date(2026, 11, 30)]
    assert _columna(rep, "Días restantes") == [4]
    assert _columna(rep, "Saldo") == [0]
    # Con 3 días ya no sale; sin indicar días usa el parámetro "por vencer" (5).
    assert servicios.reportes.generar(recepcion, "clientes_por_vencer", P(dias=3)).filas == []
    assert len(servicios.reportes.generar(recepcion, "clientes_por_vencer", P()).filas) == 1


def test_vencidos_con_dias_y_saldo(servicios, admin, escenario):
    rep = servicios.reportes.generar(admin, "clientes_vencidos", P(dias=0))
    assert sorted(_columna(rep, "Cliente")) == ["Beatriz Prueba", "Carla Prueba"]
    fila_b = next(f for f in rep.filas if f[1] == "Beatriz Prueba")
    assert fila_b[rep.encabezados.index("Días vencido")] == 27
    assert fila_b[rep.encabezados.index("Saldo")] == 70_000
    # Filtros: sexo y "vencidos en los últimos N días".
    assert _columna(servicios.reportes.generar(
        admin, "clientes_vencidos", P(dias=0, sexo="M")), "Cliente") == ["Carla Prueba"]
    assert servicios.reportes.generar(admin, "clientes_vencidos", P(dias=20)).filas == []
    # El cliente inactivo (D) no aparece aunque no tenga membresía vigente.
    assert "Diana Prueba" not in _columna(rep, "Cliente")


def test_morosos(servicios, admin, escenario):
    rep = servicios.reportes.generar(admin, "clientes_morosos", P())
    assert _columna(rep, "Cliente") == ["Beatriz Prueba"]
    assert rep.filas[0][rep.encabezados.index("Pagado")] == 50_000
    assert rep.totales[rep.encabezados.index("Saldo")] == 70_000
    assert rep.encabezados.index("Saldo") in rep.dinero


def test_nuevos_renovaciones_y_bajas_por_mes(servicios, admin, escenario):
    rep = servicios.reportes.generar(
        admin, "clientes_mensual", P(desde=date(2026, 9, 1), hasta=HOY))
    assert [f[0] for f in rep.filas] == ["Septiembre 2026", "Octubre 2026", "Noviembre 2026"]
    nov = rep.filas[2]
    assert nov[1:5] == (4, 1, 1, 0)  # nuevos, renovaciones (C), inactivados (D), vencidos
    octubre = rep.filas[1]
    assert octubre[4] == 2  # B y C vencieron el 30/10 y no renovaron
    assert rep.totales[1:5] == (4, 1, 1, 2)
    assert rep.totales[5] == 4 - 1 - 2


def test_detalles_de_nuevos_renovaciones_y_bajas(servicios, admin, escenario):
    rango = P(desde=date(2026, 9, 1), hasta=HOY)
    nuevos = servicios.reportes.generar(admin, "clientes_nuevos", rango)
    assert len(nuevos.filas) == 4
    primera = dict(zip(_columna(nuevos, "Cliente"), _columna(nuevos, "Primera membresía")))
    assert primera == {"Ana Prueba": "Mensual", "Beatriz Prueba": "Mensual",
                       "Carla Prueba": "Mensual", "Diana Prueba": "Sin membresía"}

    renov = servicios.reportes.generar(admin, "clientes_renovaciones", rango)
    assert _columna(renov, "Cliente") == ["Carla Prueba"]
    assert _columna(renov, "Inicio") == [date(2026, 10, 1)]
    assert renov.totales[renov.encabezados.index("Valor")] == 120_000

    bajas = servicios.reportes.generar(admin, "clientes_bajas", rango)
    tipos = dict(zip(_columna(bajas, "Cliente"), _columna(bajas, "Tipo de baja")))
    assert tipos == {"Diana Prueba": "Inactivado", "Beatriz Prueba": "Venció sin renovar",
                     "Carla Prueba": "Venció sin renovar"}
    detalle_d = next(f for f in bajas.filas if f[2] == "Diana Prueba")
    assert detalle_d[5] == "Se mudó de ciudad"
    # Si se renueva, B deja de ser baja.
    servicios.pagos.registrar_membresia(admin, escenario["b"], escenario["mensual"])
    bajas = servicios.reportes.generar(admin, "clientes_bajas", rango)
    assert "Beatriz Prueba" not in _columna(bajas, "Cliente")


# --- ingresos -----------------------------------------------------------------------------

def test_ingresos_por_metodo_sin_anulados(servicios, admin, escenario):
    rep = servicios.reportes.generar(admin, "ingresos_metodo", P(desde=HOY, hasta=HOY))
    totales = dict(zip(_columna(rep, "Método"), _columna(rep, "Total")))
    assert totales == {"Efectivo": 120_000, "Tarjeta": 50_000, "Transferencia": 240_000}
    assert rep.totales[1:3] == (4, 410_000)
    assert "1 anulados por $ 10.000 (no suman)" in rep.subtitulo
    assert sum(_columna(rep, "% del total")) == pytest.approx(100, abs=0.2)


def test_ingresos_por_usuario_plan_y_dia(servicios, admin, recepcion, escenario):
    rango = P(desde=HOY, hasta=HOY)
    por_usuario = servicios.reportes.generar(admin, "ingresos_usuario", rango)
    assert _columna(por_usuario, "Usuario") == ["admin", "rita"]
    assert _columna(por_usuario, "Total") == [360_000, 50_000]
    assert _columna(por_usuario, "Tarjeta") == [0, 50_000]

    servicios.pagos.registrar_pago(admin, escenario["a"], DatosPago(5_000), concepto="otro")
    por_plan = servicios.reportes.generar(admin, "ingresos_plan", rango)
    assert dict(zip(_columna(por_plan, "Plan o concepto"), _columna(por_plan, "Total"))) == {
        "Membresía Mensual": 410_000, "Otro": 5_000}

    por_dia = servicios.reportes.generar(admin, "ingresos_dia", P(desde=HOY - timedelta(1),
                                                                   hasta=HOY))
    assert _columna(por_dia, "Día") == [HOY]
    assert por_dia.totales[-1] == 415_000


def test_ingresos_detalle_con_filtros(servicios, admin, recepcion, escenario):
    rango = dict(desde=HOY, hasta=HOY)
    rep = servicios.reportes.generar(admin, "ingresos_detalle", P(**rango))
    assert len(rep.filas) == 4 and rep.totales[-1] == 410_000
    assert all(r.startswith("R-") or r for r in _columna(rep, "Recibo"))
    tarjeta = servicios.reportes.generar(admin, "ingresos_detalle", P(**rango, metodo="tarjeta"))
    assert _columna(tarjeta, "Referencia") == ["VOUCHER-1"]
    assert "tarjeta" in tarjeta.subtitulo
    de_rita = servicios.reportes.generar(
        admin, "ingresos_detalle", P(**rango, usuario_id=recepcion.id))
    assert _columna(de_rita, "Cliente") == ["Beatriz Prueba"]
    otro = servicios.reportes.generar(admin, "ingresos_detalle", P(**rango, concepto="otro"))
    assert otro.filas == []  # el único "otro" está anulado
    plan = servicios.reportes.generar(
        admin, "ingresos_detalle", P(**rango, plan_id=escenario["mensual"]))
    assert len(plan.filas) == 4
    ayer = servicios.reportes.generar(admin, "ingresos_detalle",
                                      P(desde=HOY - timedelta(1), hasta=HOY - timedelta(1)))
    assert ayer.filas == [] and ayer.totales[-1] == 0


def test_pagos_anulados_y_cierre_de_caja(servicios, admin, escenario):
    anulados = servicios.reportes.generar(admin, "pagos_anulados", P(desde=HOY, hasta=HOY))
    assert _columna(anulados, "Motivo") == ["Cobrado por error"]
    assert _columna(anulados, "Anuló") == ["admin"]
    assert anulados.totales[anulados.encabezados.index("Monto")] == 10_000
    cierre = servicios.reportes.generar(admin, "cierre_caja", P(desde=HOY))
    assert len(cierre.filas) == 5  # incluye el anulado, marcado
    assert _columna(cierre, "Estado").count("Anulado") == 1
    assert cierre.totales[cierre.encabezados.index("Monto")] == 410_000


# --- reportes de otros módulos ------------------------------------------------------------

def test_reportes_de_asistencia_casilleros_e_invitados(servicios, admin, recepcion, escenario):
    rep = servicios.reportes
    servicios.asistencia.registrar_ingreso(recepcion, "000001")
    dia = rep.generar(recepcion, "asistencia_dia", P(desde=HOY))
    assert _columna(dia, "Código") == ["000001"]
    ausentes = rep.generar(admin, "asistencia_ausentes", P(dias=30, incluir_nunca=True))
    assert "000001" not in _columna(ausentes, "Código")
    assert rep.generar(recepcion, "casilleros_lista", P()).filas == []
    assert rep.generar(recepcion, "casilleros_dia", P(desde=HOY)).filas == []
    assert rep.generar(recepcion, "invitados_visitas", P(desde=HOY, hasta=HOY)).filas == []
    with pytest.raises(ErrorValidacion):
        rep.generar(recepcion, "casilleros_lista", P(zona="sotano"))


# --- exportación --------------------------------------------------------------------------

def test_exportar_excel_y_pdf_queda_en_auditoria(servicios, admin, escenario, tmp_path,
                                                 fabrica):
    from openpyxl import load_workbook

    rango = P(desde=HOY, hasta=HOY)
    xlsx = servicios.reportes.exportar(admin, "ingresos_metodo", rango,
                                       tmp_path / "ingresos.xlsx", "xlsx")
    pdf = servicios.reportes.exportar(admin, "ingresos_metodo", rango,
                                      tmp_path / "ingresos.pdf", "pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    hoja = load_workbook(xlsx).active
    filas = list(hoja.iter_rows(values_only=True))
    assert filas[0][0] == "Ingresos por método de pago"
    assert filas[3] == ("Método", "Pagos", "Total", "% del total")
    assert filas[-1][:3] == ("Total", 4, 410_000)
    assert hoja.cell(row=hoja.max_row, column=1).font.bold
    assert hoja.cell(row=5, column=3).number_format == '"$" #,##0'
    with fabrica() as s:
        detalles = [json.loads(a.detalle_json) for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == "reporte_exportado"))]
    assert [d["formato"] for d in detalles] == ["xlsx", "pdf"]
    assert detalles[0]["reporte"] == "ingresos_metodo" and detalles[0]["filas"] == 3


def test_exportar_sin_filas_y_titulo_con_caracteres_raros(tmp_path):
    ruta = exportar_excel(tmp_path / "vacio.xlsx", "Asistencia de un cliente: 000001/2",
                          ("A", "B"), [], totales=("Total", 0))
    assert ruta.exists()


def test_periodos_rapidos():
    assert periodo("Este mes", HOY) == (date(2026, 11, 1), HOY)
    assert periodo("Mes anterior", HOY) == (date(2026, 10, 1), date(2026, 10, 31))
    assert periodo("Últimos 12 meses", HOY) == (date(2025, 12, 1), HOY)
    assert periodo("Últimos 12 meses", date(2026, 12, 5)) == (date(2026, 1, 1),
                                                               date(2026, 12, 5))
    assert periodo("Mes anterior", date(2027, 1, 10)) == (date(2026, 12, 1),
                                                           date(2026, 12, 31))
    assert periodo("Este año", HOY) == (date(2026, 1, 1), HOY)
    assert periodo("Últimos 30 días", HOY) == (HOY - timedelta(days=29), HOY)
