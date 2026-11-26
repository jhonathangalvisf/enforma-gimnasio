"""RN-06: un cliente ↔ un casillero activo, reforzado por la base de datos.

Se prueba con el ORM y también con SQL directo, para demostrar que la regla no
depende del código de la aplicación (criterio de aceptación 2).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from gimnasio.modelos import CasilleroAsignacion, ahora_utc


def asignar(sesion, casillero, cliente, usuario, cuando=None):
    asignacion = CasilleroAsignacion(
        casillero_id=casillero.id, cliente_id=cliente.id, asignado_por=usuario.id,
        fecha_asignacion=cuando or ahora_utc(),
    )
    sesion.add(asignacion)
    sesion.commit()
    return asignacion


def liberar(sesion, asignacion, usuario, motivo="Solicitud del cliente"):
    asignacion.fecha_liberacion = ahora_utc()
    asignacion.liberado_por = usuario.id
    asignacion.motivo_liberacion = motivo
    sesion.commit()


def test_cliente_no_puede_tener_dos_casilleros_activos(sesion, datos_basicos):
    usuario, (c1, _, _), (k1, k2, _) = datos_basicos
    asignar(sesion, k1, c1, usuario)
    with pytest.raises(IntegrityError, match="UNIQUE"):
        asignar(sesion, k2, c1, usuario)
    sesion.rollback()


def test_casillero_no_puede_tener_dos_clientes_activos(sesion, datos_basicos):
    usuario, (c1, c2, _), (k1, _, _) = datos_basicos
    asignar(sesion, k1, c1, usuario)
    with pytest.raises(IntegrityError, match="UNIQUE"):
        asignar(sesion, k1, c2, usuario)
    sesion.rollback()


def test_la_regla_se_cumple_con_sql_directo(motor, datos_basicos):
    """Aunque alguien escriba en la base sin pasar por la aplicación, falla."""
    _, (c1, c2, _), (k1, k2, _) = datos_basicos
    sql = text(
        "INSERT INTO casillero_asignaciones (casillero_id, cliente_id, fecha_asignacion) "
        "VALUES (:k, :c, '2026-01-01 10:00:00')"
    )
    with motor.begin() as cx:
        cx.execute(sql, {"k": k1.id, "c": c1.id})
    with pytest.raises(IntegrityError, match="casillero_asignaciones.cliente_id"):
        with motor.begin() as cx:
            cx.execute(sql, {"k": k2.id, "c": c1.id})
    with pytest.raises(IntegrityError, match="casillero_asignaciones.casillero_id"):
        with motor.begin() as cx:
            cx.execute(sql, {"k": k1.id, "c": c2.id})


def test_liberar_permite_reasignar_y_conserva_historial(sesion, datos_basicos):
    usuario, (c1, c2, _), (k1, k2, _) = datos_basicos
    primera = asignar(sesion, k1, c1, usuario, cuando=ahora_utc() - timedelta(days=30))
    liberar(sesion, primera, usuario)

    asignar(sesion, k1, c2, usuario)  # el casillero liberado se puede dar a otro
    asignar(sesion, k2, c1, usuario)  # y el cliente puede recibir otro casillero

    historial_k1 = sesion.query(CasilleroAsignacion).filter_by(casillero_id=k1.id).count()
    assert historial_k1 == 2
    activas = sesion.query(CasilleroAsignacion).filter(
        CasilleroAsignacion.fecha_liberacion.is_(None)
    ).count()
    assert activas == 2


def test_varias_asignaciones_liberadas_del_mismo_cliente_son_validas(sesion, datos_basicos):
    usuario, (c1, _, _), (k1, k2, k3) = datos_basicos
    for k in (k1, k2):
        liberar(sesion, asignar(sesion, k, c1, usuario), usuario, "Cambio de casillero")
    asignar(sesion, k3, c1, usuario)
    assert sesion.query(CasilleroAsignacion).filter_by(cliente_id=c1.id).count() == 3


def test_liberacion_no_puede_ser_anterior_a_la_asignacion(sesion, datos_basicos):
    usuario, (c1, _, _), (k1, _, _) = datos_basicos
    asignacion = asignar(sesion, k1, c1, usuario)
    asignacion.fecha_liberacion = asignacion.fecha_asignacion - timedelta(days=1)
    with pytest.raises(IntegrityError, match="CHECK"):
        sesion.commit()
    sesion.rollback()
