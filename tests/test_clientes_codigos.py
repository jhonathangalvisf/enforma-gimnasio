"""Códigos consecutivos y manuales, cédula ya registrada, vigencia a mano y resumen."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria, Membresia
from gimnasio.servicios.clientes import (
    ErrorDocumentoRegistrado, FiltrosClientes, Vigencia, normalizar_codigo,
)
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from tests.test_clientes import HOY, datos, membresia

_doc = iter(range(70_000_000, 70_100_000))


def nuevo(clientes, actual, codigo=None, **cambios):
    cambios.setdefault("documento", str(next(_doc)))
    return clientes.registrar(actual, datos(**cambios), codigo=codigo)


@pytest.fixture
def clientes(servicios):
    return servicios.clientes


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


# --- códigos ------------------------------------------------------------------------

def test_codigo_manual_no_mueve_el_consecutivo(clientes, admin, servicios):
    for _ in range(3):
        nuevo(clientes, admin)
    assert clientes.codigo_sugerido(admin) == "000004"
    antiguo = nuevo(clientes, admin, codigo="5000")  # cliente antiguo con su código
    assert antiguo.codigo == "005000"
    assert clientes.codigo_sugerido(admin) == "000004"  # sigue en el consecutivo
    assert nuevo(clientes, admin).codigo == "000004"
    assert nuevo(clientes, admin, codigo="000005").codigo == "000005"  # = sugerido
    assert clientes.codigo_sugerido(admin) == "000006"
    assert servicios.configuracion.obtener("codigo_siguiente") == 6


def test_consecutivo_salta_codigos_dados_a_mano(clientes, admin, servicios):
    nuevo(clientes, admin)  # 000001
    for codigo in ("2", "3", "5"):
        nuevo(clientes, admin, codigo=codigo)
    assert clientes.codigo_sugerido(admin) == "000004"
    assert nuevo(clientes, admin).codigo == "000004"
    assert clientes.codigo_sugerido(admin) == "000006"  # salta el 5
    servicios.configuracion.guardar(admin, {"codigo_siguiente": 2})  # el admin lo ajusta
    assert clientes.codigo_sugerido(admin) == "000006"  # 2..5 ocupados


def test_sin_consecutivo_guardado_sigue_al_mas_alto(clientes, admin, sesion):
    from tests.conftest import nuevo_cliente

    nuevo_cliente(sesion, 41)
    sesion.commit()
    assert clientes.codigo_sugerido(admin) == "000042"


def test_codigo_manual_solo_admin_unico_y_valido(clientes, admin, recepcion, fabrica):
    nuevo(clientes, admin)
    with pytest.raises(ErrorPermiso, match="Solo el administrador"):
        nuevo(clientes, recepcion, codigo="777")
    assert nuevo(clientes, recepcion, codigo="000002").codigo == "000002"  # el sugerido sí
    with pytest.raises(ErrorValidacion, match="ya es de"):
        nuevo(clientes, admin, codigo="1")
    for malo in ("abc", "1234567", "0", "-5"):
        with pytest.raises(ErrorValidacion, match="1 a 6 dígitos"):
            nuevo(clientes, admin, codigo=malo)
    nuevo(clientes, admin, codigo="900")
    assert auditorias(fabrica, "cliente_registrado")[-1] == {
        "codigo": "000900", "codigo_manual": True}


def test_normalizar_codigo():
    assert normalizar_codigo(" 42 ") == "000042"
    assert normalizar_codigo("999999") == "999999"


def test_cambiar_codigo_conserva_historial(clientes, admin, recepcion, fabrica):
    c = nuevo(clientes, admin)
    otro = nuevo(clientes, admin)
    membresia(fabrica, c.id, HOY, HOY + timedelta(days=29))
    with pytest.raises(ErrorPermiso):
        clientes.cambiar_codigo(recepcion, c.id, "5000")
    with pytest.raises(ErrorValidacion, match="ya es de"):
        clientes.cambiar_codigo(admin, c.id, otro.codigo)
    assert clientes.cambiar_codigo(admin, c.id, "5000") == "005000"
    ficha = clientes.obtener_ficha(admin, c.id)
    assert ficha.codigo == "005000" and len(ficha.membresias) == 1
    assert [f.id for f in clientes.buscar_rapido(admin, "5000")] == [c.id]
    assert clientes.buscar_rapido(admin, "1") == []  # el código viejo ya no sirve
    assert auditorias(fabrica, "cliente_codigo_cambiado")[0]["codigo"] == {
        "antes": "000001", "despues": "005000"}
    assert clientes.codigo_sugerido(admin) == "000003"


# --- cédula ya registrada ------------------------------------------------------------

def test_cedula_registrada_devuelve_el_codigo_antiguo(clientes, admin):
    c = nuevo(clientes, admin, documento="11223344")
    clientes.inactivar(admin, c.id, "Se retiró")
    with pytest.raises(ErrorDocumentoRegistrado) as error:
        nuevo(clientes, admin, documento="11.223.344", nombres="Otra")
    assert (error.value.cliente_id, error.value.codigo, error.value.activo) == (
        c.id, "000001", False)
    assert clientes.buscar(admin).total == 1  # no se creó otro
    clientes.activar(admin, error.value.cliente_id)  # se reactiva el antiguo
    assert clientes.obtener_ficha(admin, c.id).activo
    assert clientes.codigo_sugerido(admin) == "000002"


# --- vigencia a mano -------------------------------------------------------------------

def test_cambiar_vigencia_ajusta_la_ultima_membresia(clientes, admin, recepcion, fabrica):
    c = nuevo(clientes, admin)
    membresia(fabrica, c.id, HOY - timedelta(days=40), HOY - timedelta(days=11))
    assert clientes.obtener_ficha(admin, c.id).vigencia == Vigencia.VENCIDA
    nueva = HOY + timedelta(days=20)
    with pytest.raises(ErrorPermiso):
        clientes.cambiar_vigencia(recepcion, c.id, nueva, "Cortesía")
    with pytest.raises(ErrorValidacion, match="motivo"):
        clientes.cambiar_vigencia(admin, c.id, nueva, "")
    clientes.cambiar_vigencia(admin, c.id, nueva, "Compensación por cierre")
    ficha = clientes.obtener_ficha(admin, c.id)
    assert (ficha.vigencia, ficha.fecha_fin) == (Vigencia.VIGENTE, nueva)
    detalle = auditorias(fabrica, "cliente_vigencia_cambiada")[0]
    assert detalle["vence"]["despues"] == nueva.strftime("%d/%m/%Y")
    assert detalle["motivo"] == "Compensación por cierre"
    with fabrica() as s:
        assert s.scalar(select(Membresia.fecha_fin)) == nueva
    # Acortar también se puede, pero no antes del inicio de la membresía.
    clientes.cambiar_vigencia(admin, c.id, HOY - timedelta(days=1), "Error de digitación")
    assert clientes.obtener_ficha(admin, c.id).vigencia == Vigencia.VENCIDA
    with pytest.raises(ErrorValidacion, match="no puede ser anterior"):
        clientes.cambiar_vigencia(admin, c.id, HOY - timedelta(days=60), "x" * 5)


def test_asignar_vigencia_sin_membresia_pide_plan(clientes, admin, fabrica):
    c = nuevo(clientes, admin)
    plan_id = membresia(fabrica, nuevo(clientes, admin).id, HOY, HOY)  # crea el plan
    with pytest.raises(ErrorValidacion, match="elija el plan"):
        clientes.cambiar_vigencia(admin, c.id, HOY + timedelta(days=10), "Cliente antiguo")
    clientes.cambiar_vigencia(admin, c.id, HOY + timedelta(days=10), "Cliente antiguo",
                              plan_id=plan_id)
    ficha = clientes.obtener_ficha(admin, c.id)
    assert ficha.vigencia == Vigencia.VIGENTE
    m = ficha.membresias[0]
    assert (m.fecha_inicio, m.precio_pactado) == (HOY, 0)
    assert "Cliente antiguo" in m.motivo_descuento


# --- resumen "al día" -----------------------------------------------------------------

def test_resumen_y_filtro_al_dia(clientes, admin, fabrica):
    vigente, por_vencer, vencido, sin, inactivo = (nuevo(clientes, admin) for _ in range(5))
    membresia(fabrica, vigente.id, HOY, HOY + timedelta(days=29))
    membresia(fabrica, por_vencer.id, HOY - timedelta(days=27), HOY + timedelta(days=2))
    membresia(fabrica, vencido.id, HOY - timedelta(days=40), HOY - timedelta(days=11))
    membresia(fabrica, inactivo.id, HOY, HOY + timedelta(days=29))
    clientes.inactivar(admin, inactivo.id, "Se retiró")
    r = clientes.resumen(admin)
    assert (r.al_dia, r.por_vencer, r.vencidos, r.sin_membresia, r.inactivos, r.total) == (
        2, 1, 1, 1, 1, 5)
    al_dia = clientes.buscar(admin, FiltrosClientes(al_dia=True, estado="activo"))
    assert {f.id for f in al_dia.filas} == {vigente.id, por_vencer.id}
    assert sin.id not in {f.id for f in al_dia.filas}


def test_resumen_base_vacia(clientes, recepcion):
    r = clientes.resumen(recepcion)
    assert r.total == 0 and r.al_dia == 0
