"""Pruebas de planes, membresías, pagos, saldos, anulaciones, recibos y cierre de caja."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria, Config, Membresia, Pago, Plan
from gimnasio.servicios.clientes import DatosCliente, Vigencia
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import (
    DatosPago, calcular_fecha_fin, calcular_inicio_renovacion, numero_recibo,
)

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


@pytest.fixture
def mensual(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


@pytest.fixture
def cliente(servicios, admin):
    ficha = servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="1020304050", nombres="Laura", apellidos="Ríos",
        sexo="F", telefonos=["3001234567"],
    ))
    return ficha.id


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


# --- reglas de fechas (RN-03 y RN-04) -------------------------------------------------

@pytest.mark.parametrize("inicio, dias, fin", [
    (date(2026, 11, 1), 30, date(2026, 11, 30)),
    (date(2026, 11, 26), 1, date(2026, 11, 26)),       # plan de un día: vence el mismo día
    (date(2026, 11, 20), 15, date(2026, 12, 4)),
    (date(2026, 12, 15), 30, date(2027, 1, 13)),        # cruza el año
    (date(2028, 2, 1), 29, date(2028, 2, 29)),          # año bisiesto
    (date(2026, 1, 1), 90, date(2026, 3, 31)),
])
def test_fecha_fin_inclusiva(inicio, dias, fin):
    assert calcular_fecha_fin(inicio, dias) == fin


def test_fecha_fin_rechaza_duracion_invalida():
    with pytest.raises(ErrorValidacion):
        calcular_fecha_fin(HOY, 0)


def test_inicio_renovacion():
    # Vigente: inicia el día siguiente a su fin.
    assert calcular_inicio_renovacion(HOY + timedelta(days=5), HOY) == HOY + timedelta(days=6)
    # Vence hoy (último día para entrar): la nueva inicia mañana.
    assert calcular_inicio_renovacion(HOY, HOY) == HOY + timedelta(days=1)
    # Vencido o sin membresía: hoy.
    assert calcular_inicio_renovacion(HOY - timedelta(days=1), HOY) == HOY
    assert calcular_inicio_renovacion(None, HOY) == HOY
    # Política configurable: iniciar hoy aunque siga vigente.
    assert calcular_inicio_renovacion(HOY + timedelta(days=5), HOY, "hoy") == HOY


def test_numero_recibo():
    assert numero_recibo("R-", 123) == "R-000123"


# --- planes ------------------------------------------------------------------------------

def test_planes_crud_y_permisos(servicios, admin, recepcion, fabrica):
    plan = servicios.planes.crear(admin, "  Mensual  ", 30, 120_000)
    assert plan.nombre == "Mensual" and plan.activo
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        servicios.planes.crear(admin, "mensual", 30, 100_000)
    with pytest.raises(ErrorValidacion):
        servicios.planes.crear(admin, "Raro", 0, 100)
    with pytest.raises(ErrorValidacion):
        servicios.planes.crear(admin, "Raro", 10, -1)
    with pytest.raises(ErrorPermiso):
        servicios.planes.crear(recepcion, "Semanal", 7, 40_000)
    with pytest.raises(ErrorPermiso):
        servicios.planes.editar(recepcion, plan.id, "Mensual", 30, 1)

    assert servicios.planes.editar(admin, plan.id, "Mensual", 30, 130_000) == ["precio"]
    assert servicios.planes.editar(admin, plan.id, "Mensual", 30, 130_000) == []
    servicios.planes.cambiar_activo(admin, plan.id, False)
    assert servicios.planes.listar(recepcion, solo_activos=True) == []
    assert servicios.planes.listar(recepcion)[0].precio == 130_000
    assert auditorias(fabrica, "plan_editado")[0]["precio"] == {"antes": 120_000, "despues": 130_000}
    assert len(auditorias(fabrica, "plan_desactivado")) == 1


def test_planes_de_ejemplo_solo_si_no_hay(servicios, admin):
    assert servicios.planes.crear_planes_ejemplo() == 4
    planes = servicios.planes.listar(admin)
    assert {p.nombre: p.duracion_dias for p in planes} == {
        "Mensual": 30, "Quincenal": 15, "Trimestral": 90, "Día": 1}
    assert all(not p.activo and p.precio == 0 for p in planes)
    assert servicios.planes.crear_planes_ejemplo() == 0


def test_editar_plan_no_cambia_membresias_existentes(servicios, admin, mensual, cliente):
    m = servicios.pagos.registrar_membresia(admin, cliente, mensual.id)
    servicios.planes.editar(admin, mensual.id, "Mensual", 31, 150_000)
    ficha = servicios.clientes.obtener_ficha(admin, cliente)
    assert ficha.membresias[0].precio_pactado == 120_000
    assert ficha.membresias[0].fecha_fin == m.fecha_fin == date(2026, 12, 25)


# --- membresías -------------------------------------------------------------------------

def test_primera_membresia_inicia_hoy(servicios, recepcion, mensual, cliente):
    m = servicios.pagos.registrar_membresia(
        recepcion, cliente, mensual.id, pago=DatosPago(120_000, "efectivo"))
    assert (m.fecha_inicio, m.fecha_fin) == (HOY, date(2026, 12, 25))
    assert m.saldo == 0 and m.pago.recibo == "R-000001" and m.pago.saldo_despues == 0
    ficha = servicios.clientes.obtener_ficha(recepcion, cliente)
    assert ficha.vigencia == Vigencia.VIGENTE and ficha.fecha_fin == date(2026, 12, 25)
    assert ficha.saldo_pendiente == 0


def test_renovacion_anticipada_inicia_al_dia_siguiente(servicios, recepcion, mensual, cliente):
    primera = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    propuesta = servicios.pagos.proponer_membresia(recepcion, cliente)
    assert propuesta.plan_id == mensual.id  # renovación rápida: el último plan
    assert propuesta.fecha_inicio == primera.fecha_fin + timedelta(days=1)
    assert propuesta.fecha_fin == date(2027, 1, 24)
    assert propuesta.fin_actual == primera.fecha_fin
    segunda = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    assert segunda.fecha_inicio == date(2026, 12, 26)
    assert servicios.clientes.obtener_ficha(recepcion, cliente).fecha_fin == date(2027, 1, 24)


def test_renovacion_de_cliente_vencido_inicia_hoy_o_la_fecha_elegida(
    servicios, admin, recepcion, mensual, cliente, reloj
):
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    reloj.avanzar(days=40)  # vencida desde el 25/12
    hoy = HOY + timedelta(days=40)
    assert servicios.pagos.proponer_membresia(recepcion, cliente).fecha_inicio == hoy
    elegida = hoy + timedelta(days=3)
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, fecha_inicio=elegida)
    assert m.fecha_inicio == elegida


def test_no_se_cruzan_membresias(servicios, recepcion, mensual, cliente):
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    with pytest.raises(ErrorValidacion, match="26/12/2026"):
        servicios.pagos.registrar_membresia(
            recepcion, cliente, mensual.id, fecha_inicio=HOY + timedelta(days=10))


def test_politica_iniciar_hoy(servicios, admin, recepcion, mensual, cliente):
    servicios.configuracion.guardar(admin, {"renovacion_anticipada": "hoy"})
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    assert m.fecha_inicio == HOY  # pierde los días restantes, sin error de cruce


def test_limites_de_fecha_de_inicio(servicios, admin, recepcion, mensual, cliente):
    with pytest.raises(ErrorPermiso):
        servicios.pagos.registrar_membresia(
            recepcion, cliente, mensual.id, fecha_inicio=HOY - timedelta(days=31))
    with pytest.raises(ErrorValidacion):
        servicios.pagos.registrar_membresia(
            admin, cliente, mensual.id, fecha_inicio=HOY + timedelta(days=91))
    m = servicios.pagos.registrar_membresia(
        admin, cliente, mensual.id, fecha_inicio=HOY - timedelta(days=31))
    assert m.fecha_fin == HOY - timedelta(days=2)


def test_descuento_solo_admin_con_motivo(servicios, admin, recepcion, mensual, cliente, fabrica):
    with pytest.raises(ErrorPermiso):
        servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, precio_pactado=100_000)
    with pytest.raises(ErrorValidacion, match="motivo"):
        servicios.pagos.registrar_membresia(admin, cliente, mensual.id, precio_pactado=100_000)
    m = servicios.pagos.registrar_membresia(
        admin, cliente, mensual.id, precio_pactado=100_000, motivo_descuento="Referido")
    assert m.precio_pactado == 100_000
    detalle = auditorias(fabrica, "membresia_registrada")[0]
    assert detalle["motivo_descuento"] == "Referido" and detalle["precio_plan"] == 120_000
    # Mismo precio del plan: recepción no necesita permiso ni motivo.
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, precio_pactado=120_000)


def test_no_se_registra_membresia_a_inactivo_ni_con_plan_inactivo(
    servicios, admin, recepcion, mensual, cliente
):
    otro = servicios.planes.crear(admin, "Viejo", 30, 90_000, activo=False)
    with pytest.raises(ErrorValidacion, match="desactivado"):
        servicios.pagos.registrar_membresia(recepcion, cliente, otro.id)
    servicios.clientes.inactivar(admin, cliente, "Se retiró")
    with pytest.raises(ErrorValidacion, match="inactivo"):
        servicios.pagos.registrar_membresia(admin, cliente, mensual.id)


# --- pagos y saldos ---------------------------------------------------------------------

def test_abonos_y_saldo(servicios, recepcion, mensual, cliente):
    m = servicios.pagos.registrar_membresia(
        recepcion, cliente, mensual.id, pago=DatosPago(50_000, "efectivo"))
    assert m.saldo == 70_000 and m.pago.saldo_despues == 70_000
    assert servicios.pagos.saldo_cliente(recepcion, cliente) == 70_000
    with pytest.raises(ErrorValidacion, match="supera el saldo"):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(80_000), membresia_id=m.id)
    abono = servicios.pagos.registrar_pago(
        recepcion, cliente, DatosPago(70_000, "transferencia", "NEQ-123"), membresia_id=m.id)
    assert abono.saldo_despues == 0 and abono.recibo == "R-000002"
    with pytest.raises(ErrorValidacion, match="paga por completo"):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1), membresia_id=m.id)
    ficha = servicios.clientes.obtener_ficha(recepcion, cliente)
    assert ficha.membresias[0].pagado == 120_000 and ficha.saldo_pendiente == 0
    assert {p.membresia_id for p in ficha.pagos} == {m.id}


def test_membresia_sin_pago_queda_con_saldo(servicios, recepcion, mensual, cliente):
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    assert m.pago is None and m.saldo == 120_000
    assert servicios.pagos.saldo_cliente(recepcion, cliente) == 120_000


def test_pago_inicial_no_supera_precio(servicios, recepcion, mensual, cliente):
    with pytest.raises(ErrorValidacion):
        servicios.pagos.registrar_membresia(
            recepcion, cliente, mensual.id, pago=DatosPago(130_000))


@pytest.mark.parametrize("datos, mensaje", [
    (DatosPago(0), "mayor que cero"),
    (DatosPago(-5), "mayor que cero"),
    (DatosPago(1000, "cheque"), "método"),
    (DatosPago(1000, "tarjeta", ""), "referencia"),
    (DatosPago(1000, "transferencia", "   "), "referencia"),
])
def test_validaciones_de_pago(servicios, recepcion, cliente, datos, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        servicios.pagos.registrar_pago(recepcion, cliente, datos, concepto="otro")


def test_pago_de_casillero_u_otro_sin_membresia(servicios, recepcion, mensual, cliente):
    p = servicios.pagos.registrar_pago(
        recepcion, cliente, DatosPago(20_000, "tarjeta", "APR-55"), concepto="casillero")
    assert p.saldo_despues is None
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    with pytest.raises(ErrorValidacion):
        servicios.pagos.registrar_pago(
            recepcion, cliente, DatosPago(1000), concepto="otro", membresia_id=m.id)
    with pytest.raises(ErrorValidacion):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1000), concepto="membresia")


def test_abono_a_membresia_de_otro_cliente(servicios, admin, recepcion, mensual, cliente):
    otro = servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="99999999", nombres="Otro", apellidos="Cliente", sexo="M"))
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id)
    with pytest.raises(ErrorValidacion, match="no pertenece"):
        servicios.pagos.registrar_pago(recepcion, otro.id, DatosPago(1000), membresia_id=m.id)


def test_consecutivo_respeta_configuracion_y_no_se_repite(
    servicios, admin, recepcion, cliente, fabrica
):
    servicios.configuracion.guardar(admin, {"recibo_siguiente": 500, "recibo_prefijo": "EN-"})
    a = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1000), concepto="otro")
    b = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1000), concepto="otro")
    assert (a.consecutivo, b.consecutivo, b.recibo) == (500, 501, "EN-000501")
    assert servicios.configuracion.obtener("recibo_siguiente") == 502
    # Aunque alguien dejara el parámetro atrás en la base, no se repite un número.
    with fabrica() as s:
        s.get(Config, "recibo_siguiente").valor = "10"
        s.commit()
    c = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1000), concepto="otro")
    assert c.consecutivo == 502


def test_auditoria_de_pago(servicios, recepcion, cliente, fabrica):
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(15_000), concepto="otro")
    detalle = auditorias(fabrica, "pago_registrado")[0]
    assert detalle == {"recibo": "R-000001", "cliente": "000001", "concepto": "otro",
                       "monto": 15_000, "metodo": "efectivo"}


# --- anulaciones ------------------------------------------------------------------------

def test_anular_pago_solo_admin_con_motivo(servicios, admin, recepcion, mensual, cliente, fabrica):
    m = servicios.pagos.registrar_membresia(
        recepcion, cliente, mensual.id, pago=DatosPago(120_000))
    with pytest.raises(ErrorPermiso):
        servicios.pagos.anular_pago(recepcion, m.pago.id, "Error")
    with pytest.raises(ErrorValidacion, match="motivo"):
        servicios.pagos.anular_pago(admin, m.pago.id, " ")
    servicios.pagos.anular_pago(admin, m.pago.id, "Se cobró dos veces")
    with pytest.raises(ErrorValidacion, match="ya está anulado"):
        servicios.pagos.anular_pago(admin, m.pago.id, "Otra vez")
    ficha = servicios.clientes.obtener_ficha(admin, cliente)
    assert ficha.pagos[0].anulado and ficha.pagos[0].motivo_anulacion == "Se cobró dos veces"
    assert ficha.saldo_pendiente == 120_000  # el pago anulado ya no cuenta
    with fabrica() as s:
        assert s.scalar(select(Pago).where(Pago.id == m.pago.id)) is not None  # no se borra
    assert auditorias(fabrica, "pago_anulado")[0]["motivo"] == "Se cobró dos veces"


def test_anular_membresia_anula_sus_pagos(servicios, admin, recepcion, mensual, cliente):
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, pago=DatosPago(60_000))
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(60_000), membresia_id=m.id)
    casillero = servicios.pagos.registrar_pago(
        recepcion, cliente, DatosPago(10_000), concepto="casillero")
    with pytest.raises(ErrorPermiso):
        servicios.pagos.anular_membresia(recepcion, m.id, "Error")
    assert servicios.pagos.anular_membresia(admin, m.id, "Plan equivocado") == 2
    ficha = servicios.clientes.obtener_ficha(admin, cliente)
    assert ficha.vigencia == Vigencia.SIN_MEMBRESIA and ficha.saldo_pendiente == 0
    assert ficha.membresias[0].estado == "anulada"
    assert ficha.membresias[0].motivo_anulacion == "Plan equivocado"
    estados = {p.id: p.anulado for p in ficha.pagos}
    assert estados[casillero.id] is False and sum(estados.values()) == 2
    with pytest.raises(ErrorValidacion, match="anulada"):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1000), membresia_id=m.id)
    # Tras anular, la renovación vuelve a proponer hoy.
    assert servicios.pagos.proponer_membresia(recepcion, cliente).fecha_inicio == HOY


def test_bd_exige_motivo_al_anular_membresia(sesion, datos_basicos):
    usuario, clientes, _ = datos_basicos
    plan = Plan(nombre="Mensual", duracion_dias=30, precio=1000)
    sesion.add(plan)
    sesion.flush()
    sesion.add(Membresia(cliente_id=clientes[0].id, plan_id=plan.id, fecha_inicio=HOY,
                         fecha_fin=HOY, precio_pactado=1000, estado="anulada"))
    with pytest.raises(IntegrityError):
        sesion.flush()


# --- cierre de caja ---------------------------------------------------------------------

def test_cierre_de_caja(servicios, admin, recepcion, mensual, cliente, reloj):
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, pago=DatosPago(120_000))
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(20_000, "tarjeta", "A1"),
                                   concepto="casillero")
    anulado = servicios.pagos.registrar_pago(admin, cliente, DatosPago(5_000, "transferencia", "T"),
                                             concepto="otro")
    servicios.pagos.registrar_pago(admin, cliente, DatosPago(8_000), concepto="otro")
    servicios.pagos.anular_pago(admin, anulado.id, "Duplicado")

    general = servicios.pagos.cierre_caja(admin)
    assert general.total == 148_000 and general.cantidad == 3
    assert general.por_metodo == {"efectivo": 128_000, "tarjeta": 20_000, "transferencia": 0}
    assert general.anulados_cantidad == 1 and general.anulados_monto == 5_000
    assert len(general.filas) == 4  # el anulado sigue visible
    por_usuario = {t.usuario: t.total for t in general.por_usuario}
    assert por_usuario == {"admin": 8_000, "rita": 140_000}

    propio = servicios.pagos.cierre_caja(recepcion)
    assert propio.total == 140_000 and propio.usuario_id == recepcion.id
    with pytest.raises(ErrorPermiso):
        servicios.pagos.cierre_caja(recepcion, usuario_id=admin.id)
    with pytest.raises(ErrorPermiso):
        servicios.pagos.cierre_caja(recepcion, HOY - timedelta(days=1))
    assert servicios.pagos.cierre_caja(admin, usuario_id=admin.id).total == 8_000

    # Otro día (de Bogotá) no mezcla pagos.
    reloj.avanzar(hours=14)  # 27/11 00:00 en Bogotá
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1_000), concepto="otro")
    assert servicios.pagos.cierre_caja(admin, HOY).total == 148_000
    assert servicios.pagos.cierre_caja(admin, HOY + timedelta(days=1)).total == 1_000


# --- recibo -----------------------------------------------------------------------------

def test_recibo_pdf(servicios, admin, recepcion, mensual, cliente, tmp_path, fabrica):
    servicios.configuracion.guardar(admin, {"gimnasio_nit": "900.123.456-7"})
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, pago=DatosPago(50_000))
    datos = servicios.pagos.datos_recibo(recepcion, m.pago.id)
    assert datos.recibo == "R-000001" and datos.saldo_despues == 70_000
    assert datos.gimnasio_nit == "900.123.456-7"
    assert "26/11/2026 al 25/12/2026" in datos.detalle
    ruta = servicios.pagos.generar_recibo(recepcion, m.pago.id)
    assert ruta == tmp_path / "recibos" / "R-000001.pdf"
    assert ruta.read_bytes().startswith(b"%PDF")
    # Un abono posterior no cambia el saldo que muestra el primer recibo.
    abono = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(70_000), membresia_id=m.id)
    assert servicios.pagos.datos_recibo(recepcion, m.pago.id).saldo_despues == 70_000
    assert servicios.pagos.datos_recibo(recepcion, abono.id).saldo_despues == 0
    # Un recibo anulado se puede reimprimir con la marca.
    servicios.pagos.anular_pago(admin, abono.id, "Error de digitación")
    destino = servicios.pagos.generar_recibo(admin, abono.id, tmp_path / "anulado.pdf")
    assert destino.exists() and servicios.pagos.datos_recibo(admin, abono.id).anulado
    assert len(auditorias(fabrica, "recibo_generado")) == 2


def test_recibo_con_logo(servicios, admin, recepcion, cliente, tmp_path):
    from PIL import Image

    logo = tmp_path / "origen_logo.png"
    Image.new("RGB", (200, 80), "navy").save(logo)
    servicios.configuracion.guardar_logo(admin, logo)
    p = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(5_000), concepto="otro")
    assert servicios.pagos.generar_recibo(recepcion, p.id).stat().st_size > 1000


def test_migracion_completa_motivo_de_anuladas_previas(url_bd):
    """La migración 0004 rellena el motivo de membresías anuladas antes de existir."""
    from alembic import command

    from gimnasio.db.engine import crear_motor
    from gimnasio.db.migraciones import configuracion_alembic

    cfg = configuracion_alembic(url_bd)
    command.downgrade(cfg, "0003")
    motor = crear_motor(url_bd)
    with motor.begin() as c:
        c.execute(text("INSERT INTO usuarios (nombre_completo, usuario, hash_clave, rol, activo,"
                       " intentos_fallidos, creado_en, debe_cambiar_clave) VALUES "
                       "('A', 'a', 'x', 'admin', 1, 0, '2026-01-01', 0)"))
        c.execute(text("INSERT INTO clientes (codigo, qr_token, tipo_documento, documento, nombres,"
                       " apellidos, sexo, estado, creado_en, actualizado_en, busqueda) VALUES "
                       "('000001', 'q', 'CC', '1', 'A', 'B', 'M', 'activo', '2026-01-01',"
                       " '2026-01-01', 'a b')"))
        c.execute(text("INSERT INTO planes (nombre, duracion_dias, precio, activo) VALUES ('M', 30, 1, 1)"))
        c.execute(text("INSERT INTO membresias (cliente_id, plan_id, fecha_inicio, fecha_fin,"
                       " precio_pactado, estado, creado_en) VALUES (1, 1, '2026-01-01',"
                       " '2026-01-30', 1, 'anulada', '2026-01-01')"))
    motor.dispose()
    command.upgrade(cfg, "head")
    motor = crear_motor(url_bd)
    with motor.connect() as c:
        assert c.execute(text("SELECT motivo_anulacion FROM membresias")).scalar()
    motor.dispose()


def test_recibo_de_mensualidad_muestra_datos_y_nueva_vigencia(
    servicios, admin, recepcion, mensual, cliente, reloj, monkeypatch
):
    """El recibo de una renovación lleva nombre, código, fecha del pago, la nueva
    vigencia y el número consecutivo."""
    servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, pago=DatosPago(120_000))
    reloj.avanzar(days=20)  # paga la renovación el 16/12/2026, antes de vencer
    m = servicios.pagos.registrar_membresia(recepcion, cliente, mensual.id, pago=DatosPago(120_000))
    datos = servicios.pagos.datos_recibo(recepcion, m.pago.id)
    assert (datos.vigencia_desde, datos.vigencia_hasta) == (date(2026, 12, 26), date(2027, 1, 24))
    # Se captura todo lo que se escribe en el PDF.
    from reportlab.pdfgen.canvas import Canvas

    escrito: list[str] = []
    for metodo in ("drawString", "drawRightString", "drawCentredString"):
        original = getattr(Canvas, metodo)

        def capturar(self, x, y, texto, *a, _original=original, **k):
            escrito.append(texto)
            return _original(self, x, y, texto, *a, **k)

        monkeypatch.setattr(Canvas, metodo, capturar)
    assert servicios.pagos.generar_recibo(recepcion, m.pago.id).read_bytes().startswith(b"%PDF")
    texto = "\n".join(escrito)
    for esperado in ("R-000002", "Laura Ríos", "000001", "Fecha de pago", "16/12/2026",
                     "NUEVA VIGENCIA", "Del 26/12/2026 al 24/01/2027"):
        assert esperado in texto, esperado
    # Pagos que no son de membresía no muestran vigencia.
    otro = servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(5_000), concepto="otro")
    assert servicios.pagos.datos_recibo(recepcion, otro.id).vigencia_hasta is None

