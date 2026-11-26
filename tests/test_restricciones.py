"""Restricciones de la base de datos (CHECK, UNIQUE y claves foráneas)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from gimnasio.modelos import Asistencia, Membresia, Pago, Plan, ahora_utc
from tests.conftest import nuevo_cliente


def falla_al_guardar(sesion, *objetos, patron="constraint failed"):
    sesion.add_all(objetos)
    with pytest.raises(IntegrityError, match=patron):
        sesion.commit()
    sesion.rollback()


@pytest.mark.parametrize("codigo", ["12345", "1234567", "12A456", "abcdef"])
def test_codigo_debe_tener_6_digitos(sesion, codigo):
    with pytest.raises(IntegrityError, match="CHECK"):
        nuevo_cliente(sesion, 1, codigo=codigo)
    sesion.rollback()


def test_codigo_con_ceros_a_la_izquierda_es_valido(sesion):
    assert nuevo_cliente(sesion, 7).codigo == "000007"


def test_documento_y_codigo_unicos(sesion, datos_basicos):
    with pytest.raises(IntegrityError, match="UNIQUE"):
        nuevo_cliente(sesion, 99, documento=datos_basicos[1][0].documento)
    sesion.rollback()
    with pytest.raises(IntegrityError, match="UNIQUE"):
        nuevo_cliente(sesion, 98, codigo="000001")
    sesion.rollback()


def test_sexo_invalido(sesion):
    with pytest.raises(IntegrityError, match="CHECK"):
        nuevo_cliente(sesion, 1, sexo="X")
    sesion.rollback()


def _pago(cliente, usuario, **campos):
    datos = dict(consecutivo=1, cliente_id=cliente.id, concepto="membresia", monto=120000,
                 metodo="efectivo", usuario_id=usuario.id)
    datos.update(campos)
    return Pago(**datos)


def test_tarjeta_y_transferencia_exigen_referencia(sesion, datos_basicos):
    usuario, (c1, _, _), _ = datos_basicos
    for metodo in ("tarjeta", "transferencia"):
        falla_al_guardar(sesion, _pago(c1, usuario, metodo=metodo), patron="CHECK")
        falla_al_guardar(sesion, _pago(c1, usuario, metodo=metodo, referencia="  "), patron="CHECK")
    sesion.add(_pago(c1, usuario, metodo="tarjeta", referencia="TAR-123"))
    sesion.commit()


def test_pago_anulado_exige_motivo_y_monto_positivo(sesion, datos_basicos):
    usuario, (c1, _, _), _ = datos_basicos
    falla_al_guardar(sesion, _pago(c1, usuario, anulado=True), patron="CHECK")
    falla_al_guardar(sesion, _pago(c1, usuario, monto=0), patron="CHECK")


def test_consecutivo_de_recibo_unico(sesion, datos_basicos):
    usuario, (c1, c2, _), _ = datos_basicos
    sesion.add(_pago(c1, usuario))
    sesion.commit()
    falla_al_guardar(sesion, _pago(c2, usuario), patron="UNIQUE")


def test_membresia_fin_no_anterior_al_inicio(sesion, datos_basicos):
    usuario, (c1, _, _), _ = datos_basicos
    plan = Plan(nombre="Mensual", duracion_dias=30, precio=120000)
    sesion.add(plan)
    sesion.flush()
    falla_al_guardar(sesion, Membresia(
        cliente_id=c1.id, plan_id=plan.id, fecha_inicio=date(2026, 2, 1),
        fecha_fin=date(2026, 1, 31), precio_pactado=120000,
    ), patron="CHECK")


def test_asistencia_eliminada_exige_motivo(sesion, datos_basicos):
    usuario, (c1, _, _), _ = datos_basicos
    falla_al_guardar(sesion, Asistencia(
        cliente_id=c1.id, fecha=date.today(), resultado="permitido", usuario_id=usuario.id,
        eliminada=True,
    ), patron="CHECK")


def test_claves_foraneas_activas(sesion, datos_basicos):
    usuario, _, _ = datos_basicos
    falla_al_guardar(sesion, Asistencia(
        cliente_id=9999, fecha=date.today(), resultado="permitido", usuario_id=usuario.id,
    ), patron="FOREIGN KEY")


def test_fechas_se_guardan_en_utc(sesion, datos_basicos):
    from gimnasio.config import ZONA_HORARIA

    usuario, (c1, _, _), _ = datos_basicos
    local = datetime(2026, 3, 10, 19, 30, tzinfo=ZONA_HORARIA)  # 7:30 p. m. en Bogotá
    sesion.add(Asistencia(cliente_id=c1.id, fecha_hora=local, fecha=local.date(),
                          resultado="permitido", usuario_id=usuario.id))
    sesion.commit()
    sesion.expire_all()
    guardada = sesion.query(Asistencia).one().fecha_hora
    assert guardada == datetime(2026, 3, 11, 0, 30, tzinfo=timezone.utc)
    assert guardada.tzinfo is timezone.utc


def test_fecha_sin_zona_horaria_se_rechaza(sesion, datos_basicos):
    usuario, (c1, _, _), _ = datos_basicos
    sesion.add(Asistencia(cliente_id=c1.id, fecha_hora=datetime(2026, 1, 1, 8, 0),
                          fecha=date(2026, 1, 1), resultado="permitido", usuario_id=usuario.id))
    with pytest.raises(Exception, match="zona horaria"):
        sesion.commit()
    sesion.rollback()
    assert ahora_utc().tzinfo is timezone.utc
