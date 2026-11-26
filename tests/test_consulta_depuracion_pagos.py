"""Consultas de pagos por cliente y fecha, y depuración (borrado) de pagos antiguos."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria, Membresia, Pago
from gimnasio.servicios.clientes import DatosCliente, Vigencia
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import DatosPago, FiltrosPagos

HOY = date(2026, 11, 26)
CLAVE_COPIAS = "copias-Enforma-2026"
CLAVE_SEGURIDAD = "SoloJhonathan99"


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


@pytest.fixture
def mensual(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 100_000)


def nuevo(servicios, admin, documento, nombres):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento=documento, nombres=nombres, apellidos="Prueba",
        sexo="F")).id


@pytest.fixture
def historial(servicios, admin, recepcion, mensual, reloj):
    """Dos clientes que pagan cada mes desde hace 90 días (reloj vuelve a hoy)."""
    a = nuevo(servicios, admin, "11111111", "Ana")
    b = nuevo(servicios, admin, "22222222", "Beto")
    inicio = reloj.ahora
    reloj.avanzar(days=-90)
    for _ in range(3):
        servicios.pagos.registrar_membresia(recepcion, a, mensual.id, fecha_inicio=servicios.pagos.hoy(),
                                            pago=DatosPago(100_000))
        servicios.pagos.registrar_membresia(recepcion, b, mensual.id, fecha_inicio=servicios.pagos.hoy(),
                                            pago=DatosPago(100_000, "tarjeta", "T1"))
        reloj.avanzar(days=30)
    reloj.ahora = inicio
    return a, b


# --- consultas -----------------------------------------------------------------------

def test_consulta_por_cliente_y_por_fecha(servicios, admin, recepcion, historial):
    a, b = historial
    todo = servicios.pagos.consultar_pagos(admin, FiltrosPagos())
    assert todo.cantidad == 6 and todo.total == 600_000
    assert todo.filas[0].fecha_hora >= todo.filas[-1].fecha_hora  # más reciente primero
    de_a = servicios.pagos.consultar_pagos(recepcion, FiltrosPagos(cliente_id=a))
    assert de_a.cantidad == 3 and {f.cliente_codigo for f in de_a.filas} == {"000001"}
    assert "Mensual:" in de_a.filas[0].detalle
    ultimo_mes = servicios.pagos.consultar_pagos(
        admin, FiltrosPagos(desde=HOY - timedelta(days=31), hasta=HOY))
    assert ultimo_mes.cantidad == 2
    tarjeta = servicios.pagos.consultar_pagos(admin, FiltrosPagos(metodo="tarjeta"))
    assert tarjeta.cantidad == 3


def test_recepcion_solo_consulta_un_cliente(servicios, recepcion, historial):
    with pytest.raises(ErrorPermiso):
        servicios.pagos.consultar_pagos(recepcion, FiltrosPagos(desde=HOY, hasta=HOY))


def test_consulta_valida_fechas(servicios, admin):
    with pytest.raises(ErrorValidacion):
        servicios.pagos.consultar_pagos(admin, FiltrosPagos(desde=HOY, hasta=HOY - timedelta(days=1)))


def test_consulta_muestra_anulados_sin_sumarlos(servicios, admin, historial):
    primero = servicios.pagos.consultar_pagos(admin, FiltrosPagos()).filas[0]
    servicios.pagos.anular_pago(admin, primero.pago_id, "Error")
    c = servicios.pagos.consultar_pagos(admin, FiltrosPagos())
    assert c.cantidad == 5 and c.total == 500_000 and c.anulados_cantidad == 1
    assert len(c.filas) == 6
    assert len(servicios.pagos.consultar_pagos(admin, FiltrosPagos(incluir_anulados=False)).filas) == 5


def test_consulta_limite(servicios, admin, historial):
    c = servicios.pagos.consultar_pagos(admin, FiltrosPagos(), limite=4)
    assert len(c.filas) == 4 and c.truncada and c.cantidad == 6


def test_exportar_consulta(servicios, admin, recepcion, historial, tmp_path, fabrica):
    a, _ = historial
    ruta = servicios.pagos.exportar_consulta(recepcion, FiltrosPagos(cliente_id=a),
                                             tmp_path / "pagos.xlsx", "xlsx")
    hoja = load_workbook(ruta).active
    textos = [c for fila in hoja.iter_rows(values_only=True) for c in fila if c]
    assert "Consulta de pagos" in textos and 300_000 in textos
    pdf = servicios.pagos.exportar_consulta(admin, FiltrosPagos(), tmp_path / "p.pdf", "pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    with fabrica() as s:
        assert s.scalar(select(func.count(Auditoria.id)).where(
            Auditoria.accion == "pagos_exportados")) == 2


# --- clave de seguridad ------------------------------------------------------------------

def test_clave_de_seguridad(servicios, admin, recepcion, fabrica):
    d = servicios.depuracion
    assert not d.tiene_clave(admin)
    with pytest.raises(ErrorPermiso):
        d.tiene_clave(recepcion)
    with pytest.raises(ErrorPermiso, match="contraseña del administrador"):
        d.configurar_clave(admin, "mala", CLAVE_SEGURIDAD, CLAVE_SEGURIDAD)
    with pytest.raises(ErrorValidacion, match="distinta"):
        d.configurar_clave(admin, "ClaveSegura1", "ClaveSegura1", "ClaveSegura1")
    with pytest.raises(ErrorValidacion, match="coinciden"):
        d.configurar_clave(admin, "ClaveSegura1", CLAVE_SEGURIDAD, "otra")
    d.configurar_clave(admin, "ClaveSegura1", CLAVE_SEGURIDAD, CLAVE_SEGURIDAD)
    assert d.tiene_clave(admin)
    d.comprobar_clave(admin, CLAVE_SEGURIDAD)
    with pytest.raises(ErrorPermiso):
        d.comprobar_clave(admin, "ClaveSegura1")  # la contraseña de login no sirve
    # Para cambiarla hace falta la clave de seguridad actual, no la contraseña.
    with pytest.raises(ErrorPermiso):
        d.configurar_clave(admin, "ClaveSegura1", "NuevaClave123", "NuevaClave123")
    d.configurar_clave(admin, CLAVE_SEGURIDAD, "NuevaClave123", "NuevaClave123")
    with fabrica() as s:
        detalle = [a.detalle_json or "" for a in s.scalars(select(Auditoria))]
    assert not any(CLAVE_SEGURIDAD in x or "NuevaClave123" in x for x in detalle)


def test_bloqueo_por_intentos(servicios, admin, reloj):
    d = servicios.depuracion
    d.configurar_clave(admin, "ClaveSegura1", CLAVE_SEGURIDAD, CLAVE_SEGURIDAD)
    for _ in range(5):
        with pytest.raises(ErrorPermiso):
            d.comprobar_clave(admin, "mala")
    with pytest.raises(ErrorPermiso, match="Demasiados intentos"):
        d.comprobar_clave(admin, CLAVE_SEGURIDAD)
    reloj.avanzar(minutes=16)
    d.comprobar_clave(admin, CLAVE_SEGURIDAD)


# --- depuración --------------------------------------------------------------------------

@pytest.fixture
def listo(servicios, admin, historial):
    servicios.backups.configurar_clave(admin, CLAVE_COPIAS, CLAVE_COPIAS)
    servicios.depuracion.configurar_clave(admin, "ClaveSegura1", CLAVE_SEGURIDAD, CLAVE_SEGURIDAD)
    return historial


def test_depurar_borra_hasta_la_fecha_elegida(servicios, admin, listo, fabrica, tmp_path):
    a, b = listo
    corte = HOY - timedelta(days=45)  # cubre solo el primer mes (hace 90 días)
    vista = servicios.depuracion.vista_previa(admin, CLAVE_SEGURIDAD, corte)
    assert (vista.pagos, vista.membresias, vista.monto_validos) == (2, 2, 200_000)
    antes = servicios.clientes.obtener_ficha(admin, a)

    r = servicios.depuracion.depurar(admin, CLAVE_SEGURIDAD, corte, "Aligerar historial")
    assert r.excel.exists() and r.excel.parent == tmp_path / "depuraciones"
    assert r.copia_seguridad  # se hizo la copia cifrada antes
    hoja = load_workbook(r.excel).active
    assert sum(1 for fila in hoja.iter_rows(values_only=True) if fila[1] and str(fila[1]).startswith("R-")) == 2

    with fabrica() as s:
        assert s.scalar(select(func.count(Pago.id))) == 4
        assert s.scalar(select(func.count(Membresia.id))) == 4
        detalle = json.loads(s.scalar(select(Auditoria.detalle_json).where(
            Auditoria.accion == "pagos_depurados")))
    assert detalle["pagos_borrados"] == 2 and detalle["corte"] == "12/10/2026"
    # La vigencia y el saldo del cliente no cambian.
    despues = servicios.clientes.obtener_ficha(admin, a)
    assert (despues.vigencia, despues.fecha_fin, despues.saldo_pendiente) == (
        antes.vigencia, antes.fecha_fin, antes.saldo_pendiente)
    # La secuencia de recibos sigue sin repetir números.
    nuevo_pago = servicios.pagos.registrar_pago(admin, a, DatosPago(1000), concepto="otro")
    assert nuevo_pago.consecutivo == 7


def test_nunca_borra_la_ultima_membresia_ni_su_pago(servicios, admin, listo, fabrica):
    # Un corte de ayer abarca todo, pero la última membresía de cada cliente se queda.
    vista = servicios.depuracion.vista_previa(admin, CLAVE_SEGURIDAD, HOY - timedelta(days=1))
    assert vista.pagos == 4 and vista.pagos_conservados == 2
    servicios.depuracion.depurar(admin, CLAVE_SEGURIDAD, HOY - timedelta(days=1), "Limpieza")
    for cid in listo:
        ficha = servicios.clientes.obtener_ficha(admin, cid)
        assert ficha.vigencia != Vigencia.SIN_MEMBRESIA and len(ficha.membresias) == 1
        assert ficha.saldo_pendiente == 0 and len(ficha.pagos) == 1


def test_depurar_exige_admin_clave_y_fecha_pasada(servicios, admin, recepcion, listo):
    d = servicios.depuracion
    with pytest.raises(ErrorPermiso):
        d.depurar(recepcion, CLAVE_SEGURIDAD, HOY - timedelta(days=60), "x" * 5)
    with pytest.raises(ErrorPermiso):
        d.depurar(admin, "ClaveSegura1", HOY - timedelta(days=60), "Motivo")
    with pytest.raises(ErrorValidacion, match="anterior a hoy"):
        d.depurar(admin, CLAVE_SEGURIDAD, HOY, "Motivo")
    with pytest.raises(ErrorValidacion, match="motivo"):
        d.depurar(admin, CLAVE_SEGURIDAD, HOY - timedelta(days=60), "")
    with pytest.raises(ErrorValidacion, match="No hay pagos"):
        d.depurar(admin, CLAVE_SEGURIDAD, HOY - timedelta(days=200), "Motivo")


def test_si_falla_la_copia_no_se_borra_nada(servicios, admin, historial, fabrica):
    # Sin contraseña de copias de seguridad la copia falla.
    servicios.depuracion.configurar_clave(admin, "ClaveSegura1", CLAVE_SEGURIDAD, CLAVE_SEGURIDAD)
    with pytest.raises(Exception, match="contraseña de las copias|copia de seguridad"):
        servicios.depuracion.depurar(admin, CLAVE_SEGURIDAD, HOY - timedelta(days=45), "Motivo")
    with fabrica() as s:
        assert s.scalar(select(func.count(Pago.id))) == 6
