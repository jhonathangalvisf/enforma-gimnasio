"""Mensualidad y casillero pagados juntos: un solo recibo con un solo número.
Solo casillero: su propio recibo con el siguiente consecutivo."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import CasilleroAsignacion, Membresia, Pago
from gimnasio.servicios.casilleros import CasilleroEnRecibo
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.pagos import DatosPago
from tests.test_servicio_casilleros import HOY, cliente


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


@pytest.fixture
def plan(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


@pytest.fixture
def libres(servicios, admin):
    servicios.casilleros.crear_rango(admin, 1, 3, "mujeres")
    return {n: i for i, n, _ in servicios.casilleros.libres(admin)}


def pagos(fabrica):
    with fabrica() as s:
        return [(p.consecutivo, p.concepto, p.monto, p.metodo) for p in
                s.scalars(select(Pago).order_by(Pago.consecutivo, Pago.id))]


def test_mensualidad_y_casillero_nuevo_en_un_solo_recibo(servicios, recepcion, admin, plan,
                                                         libres, fabrica):
    c = cliente(servicios, admin)
    r = servicios.casilleros.mensualidad_con_casillero(
        recepcion, c.id, plan.id, pago=DatosPago(120_000, "transferencia", "NEQ-1"),
        casillero=CasilleroEnRecibo(monto=20_000, casillero_id=libres["002"], dias=30),
    )
    assert r.recibo == "R-000001"
    assert r.membresia.fecha_fin == HOY + timedelta(days=29)
    assert r.casillero.numero == "002" and r.casillero.vence == HOY + timedelta(days=29)
    # Los dos pagos comparten el número de recibo y el método.
    assert pagos(fabrica) == [(1, "membresia", 120_000, "transferencia"),
                              (1, "casillero", 20_000, "transferencia")]
    datos = servicios.pagos.datos_recibo(recepcion, r.pago_id)
    assert datos.recibo == "R-000001" and datos.monto == 140_000
    assert [(l.concepto, l.monto) for l in datos.lineas] == [
        ("Membresía", 120_000), ("Casillero", 20_000)]
    assert datos.lineas[1].detalle == "Casillero 002"
    assert datos.vigencia_hasta == r.membresia.fecha_fin and datos.saldo_despues == 0
    # Desde el pago del casillero se abre el mismo recibo.
    with fabrica() as s:
        id_casillero = s.scalar(select(Pago.id).where(Pago.concepto == "casillero"))
    assert servicios.pagos.datos_recibo(recepcion, id_casillero).monto == 140_000
    # El PDF sale con los dos conceptos.
    ruta = servicios.pagos.generar_recibo(recepcion, r.pago_id)
    assert ruta.name == "R-000001.pdf" and ruta.stat().st_size > 0


def test_solo_casillero_lleva_el_siguiente_consecutivo(servicios, recepcion, admin, plan, libres,
                                                       fabrica):
    a = cliente(servicios, admin, 1)
    b = cliente(servicios, admin, 2)
    servicios.casilleros.mensualidad_con_casillero(
        recepcion, a.id, plan.id, pago=DatosPago(120_000),
        casillero=CasilleroEnRecibo(monto=20_000, casillero_id=libres["001"]))
    solo = servicios.casilleros.asignar(recepcion, libres["003"], b.id, pago=DatosPago(20_000))
    assert solo.pago.recibo == "R-000002"
    otra = servicios.pagos.registrar_membresia(recepcion, b.id, plan.id, pago=DatosPago(120_000))
    assert otra.pago.recibo == "R-000003"
    datos = servicios.pagos.datos_recibo(recepcion, solo.pago.id)
    assert datos.lineas == [] and datos.monto == 20_000 and datos.detalle == "Casillero 003"


def test_renovar_casillero_con_la_mensualidad(servicios, recepcion, admin, plan, libres, fabrica):
    c = cliente(servicios, admin)
    asignado = servicios.casilleros.asignar(recepcion, libres["001"], c.id, dias=10,
                                            pago=DatosPago(10_000))
    r = servicios.casilleros.mensualidad_con_casillero(
        recepcion, c.id, plan.id, pago=DatosPago(120_000),
        casillero=CasilleroEnRecibo(monto=20_000, asignacion_id=asignado.asignacion_id, dias=30))
    assert r.recibo == "R-000002"
    assert r.casillero.vence_anterior == HOY + timedelta(days=9)
    assert r.casillero.vence == HOY + timedelta(days=39)
    assert [p[:2] for p in pagos(fabrica)] == [(1, "casillero"), (2, "membresia"),
                                               (2, "casillero")]


def test_si_algo_falla_no_se_guarda_nada(servicios, recepcion, admin, plan, libres, fabrica):
    c = cliente(servicios, admin)
    otro = cliente(servicios, admin, 2)
    servicios.casilleros.asignar(recepcion, libres["001"], otro.id)
    # Casillero ocupado: tampoco queda la membresía ni su pago.
    with pytest.raises(ErrorValidacion, match="ya está asignado"):
        servicios.casilleros.mensualidad_con_casillero(
            recepcion, c.id, plan.id, pago=DatosPago(120_000),
            casillero=CasilleroEnRecibo(monto=20_000, casillero_id=libres["001"]))
    with pytest.raises(ErrorValidacion, match="mayor que cero"):
        servicios.casilleros.mensualidad_con_casillero(
            recepcion, c.id, plan.id, pago=DatosPago(120_000),
            casillero=CasilleroEnRecibo(monto=0, casillero_id=libres["002"]))
    with fabrica() as s:
        assert s.scalar(select(Membresia.id)) is None
        assert s.scalar(select(Pago.id)) is None
        assert len(list(s.scalars(select(CasilleroAsignacion)))) == 1
    # El consecutivo no se gastó.
    r = servicios.casilleros.mensualidad_con_casillero(
        recepcion, c.id, plan.id, pago=DatosPago(120_000),
        casillero=CasilleroEnRecibo(monto=20_000, casillero_id=libres["002"]))
    assert r.recibo == "R-000001"


def test_validaciones(servicios, recepcion, admin, plan, libres):
    c = cliente(servicios, admin)
    otro = cliente(servicios, admin, 2)
    ajeno = servicios.casilleros.asignar(recepcion, libres["001"], otro.id)
    con = dict(pago=DatosPago(120_000))
    with pytest.raises(ErrorValidacion, match="Elija el casillero"):
        servicios.casilleros.mensualidad_con_casillero(
            recepcion, c.id, plan.id, casillero=CasilleroEnRecibo(monto=1), **con)
    with pytest.raises(ErrorValidacion, match="no es de este cliente"):
        servicios.casilleros.mensualidad_con_casillero(
            recepcion, c.id, plan.id, **con,
            casillero=CasilleroEnRecibo(monto=1, asignacion_id=ajeno.asignacion_id))
    with pytest.raises(ErrorValidacion, match="pago de la mensualidad"):
        servicios.casilleros.mensualidad_con_casillero(
            recepcion, c.id, plan.id, pago=None,
            casillero=CasilleroEnRecibo(monto=1, casillero_id=libres["002"]))


def test_anular_un_renglon_deja_el_otro(servicios, recepcion, admin, plan, libres, fabrica):
    c = cliente(servicios, admin)
    r = servicios.casilleros.mensualidad_con_casillero(
        recepcion, c.id, plan.id, pago=DatosPago(120_000),
        casillero=CasilleroEnRecibo(monto=20_000, casillero_id=libres["001"]))
    with fabrica() as s:
        id_casillero = s.scalar(select(Pago.id).where(Pago.concepto == "casillero"))
    servicios.pagos.anular_pago(admin, id_casillero, "Se cobró de más")
    datos = servicios.pagos.datos_recibo(recepcion, r.pago_id)
    assert not datos.anulado and datos.monto == 120_000
    assert [l.anulado for l in datos.lineas] == [False, True]
    servicios.pagos.anular_pago(admin, r.pago_id, "Error de digitación")
    datos = servicios.pagos.datos_recibo(recepcion, r.pago_id)
    assert datos.anulado and datos.monto == 140_000
    caja = servicios.pagos.cierre_caja(admin, HOY)
    assert caja.total == 0 and caja.anulados_cantidad == 2
