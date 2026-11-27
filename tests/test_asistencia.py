"""Pruebas de Recepción y Asistencia: tarjeta verde, amarilla y roja, duplicados,
ingreso autorizado, renovar ahora, alertas, eliminación lógica, consultas y reportes."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Asistencia, Auditoria, Casillero, CasilleroAsignacion, Cliente
from gimnasio.servicios.asistencia import (
    AMARILLO, DUPLICADO_BLOQUEADO, DUPLICADO_CONFIRMAR, RECHAZADO, REGISTRADO, ROJO, VERDE,
    FiltrosAsistencia, ParametrosReporte,
)
from gimnasio.servicios.clientes import DatosCliente
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import DatosPago
from tests.conftest import CLAVE_PRUEBA, dejar_saldo_antiguo

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


@pytest.fixture
def mensual(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


def registrar_cliente(servicios, admin, n=1, **campos):
    datos = dict(tipo_documento="CC", documento=f"10203040{n:02d}", nombres="Laura",
                 apellidos=f"Ríos {n}", sexo="F", telefonos=[f"30012345{n:02d}"],
                 fecha_nacimiento=date(1990, 3, 15))
    datos.update(campos)
    return servicios.clientes.registrar(admin, DatosCliente(**datos))


@pytest.fixture
def cliente(servicios, admin):
    return registrar_cliente(servicios, admin)


def membresia(servicios, admin, cliente_id, plan, inicio, pagar=True):
    pago = DatosPago(plan.precio, "efectivo") if pagar else None
    return servicios.pagos.registrar_membresia(admin, cliente_id, plan.id,
                                               fecha_inicio=inicio, pago=pago)


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


def asignar_casillero(fabrica, cliente_id, numero="015"):
    with fabrica() as s:
        casillero = Casillero(numero=numero, zona="mixto", estado="ocupado")
        s.add(casillero)
        s.flush()
        asignacion = CasilleroAsignacion(
            casillero_id=casillero.id, cliente_id=cliente_id,
            fecha_asignacion=datetime(2026, 11, 1, tzinfo=timezone.utc))
        s.add(asignacion)
        s.commit()
        return asignacion.id


# --- tarjeta de Recepción ------------------------------------------------------------

def test_verde_registra_ingreso_con_casillero(servicios, recepcion, admin, cliente, mensual,
                                              fabrica):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    asignar_casillero(fabrica, cliente.id)
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    assert r.estado == REGISTRADO and r.asistencia_id
    t = r.tarjeta
    assert t.color == VERDE and t.titulo == "BIENVENIDO" and t.resultado == "permitido"
    assert t.casillero == "015" and t.plan == "Mensual" and t.dias_restantes == 29
    with fabrica() as s:
        a = s.get(Asistencia, r.asistencia_id)
        assert a.casillero_numero == "015" and a.fecha == HOY and a.usuario_id == recepcion.id


def test_codigo_sin_ceros_y_qr(servicios, recepcion, admin, cliente, mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    assert servicios.asistencia.buscar_codigo(recepcion, str(int(cliente.codigo))) == cliente.id
    assert servicios.asistencia.buscar_codigo(recepcion, f"  {cliente.qr_token} ") == cliente.id
    with pytest.raises(ErrorValidacion, match="No se encontró"):
        servicios.asistencia.buscar_codigo(recepcion, "999999")
    with pytest.raises(ErrorValidacion):
        servicios.asistencia.buscar_codigo(recepcion, "   ")


@pytest.mark.parametrize("dias_atras, mensaje", [
    (25, "Tu plan vence el 30/11/2026 (faltan 4 días)."),
    (28, "Tu plan vence el 27/11/2026 (falta 1 día)."),
    (29, "Tu plan vence hoy, 26/11/2026."),
])
def test_amarillo_por_vencer(servicios, recepcion, admin, cliente, mensual, dias_atras, mensaje):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=dias_atras))
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    assert r.estado == REGISTRADO
    assert r.tarjeta.color == AMARILLO and r.tarjeta.resultado == "por_vencer"
    assert r.tarjeta.mensaje == mensaje


def test_umbral_por_vencer_configurable(servicios, recepcion, admin, cliente, mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=20))  # faltan 9
    assert servicios.asistencia.tarjeta(recepcion, cliente.id).color == VERDE
    servicios.configuracion.guardar(admin, {"dias_por_vencer": 10})
    assert servicios.asistencia.tarjeta(recepcion, cliente.id).color == AMARILLO


def test_saldo_pendiente_entra_con_aviso_amarillo(servicios, recepcion, admin, cliente, mensual,
                                                  fabrica):
    m = servicios.pagos.registrar_membresia(admin, cliente.id, mensual.id,
                                            pago=DatosPago(120_000, "efectivo"))
    dejar_saldo_antiguo(fabrica, m.pago.id, 50_000)  # saldo de antes de quitar los abonos
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    assert r.estado == REGISTRADO and r.tarjeta.resultado == "permitido"
    assert r.tarjeta.color == AMARILLO and "SALDO PENDIENTE" in r.tarjeta.titulo
    assert r.tarjeta.saldo_pendiente == 70_000 and "$ 70.000" in r.tarjeta.mensaje


def test_rojo_vencido_se_guarda_como_rechazo(servicios, recepcion, admin, cliente, mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=40))
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    assert r.estado == RECHAZADO and r.asistencia_id
    assert r.tarjeta.color == ROJO and r.tarjeta.resultado == "vencido"
    assert r.tarjeta.mensaje == "Tu plan venció el 15/11/2026 (hace 11 días)."
    resumen = servicios.asistencia.resumen_del_dia(recepcion)
    assert resumen.asistentes == 0 and resumen.rechazados == 1
    assert [f.resultado for f in resumen.ultimos] == ["vencido"]


def test_rojo_sin_membresia_e_inactivo(servicios, recepcion, admin, mensual):
    sin = registrar_cliente(servicios, admin, 1)
    r = servicios.asistencia.registrar_ingreso(recepcion, sin.codigo)
    assert r.tarjeta.titulo == "SIN MEMBRESÍA" and r.tarjeta.resultado == "vencido"
    inactivo = registrar_cliente(servicios, admin, 2)
    membresia(servicios, admin, inactivo.id, mensual, HOY)
    servicios.clientes.inactivar(admin, inactivo.id, "Retiro voluntario")
    r = servicios.asistencia.registrar_ingreso(recepcion, inactivo.codigo)
    assert r.estado == RECHAZADO  # RN-05: aunque tenga membresía vigente
    assert r.tarjeta.color == ROJO and r.tarjeta.resultado == "inactivo"


def test_membresia_futura_no_permite_entrar(servicios, recepcion, admin, cliente, mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY + timedelta(days=3))
    t = servicios.asistencia.tarjeta(recepcion, cliente.id)
    assert t.color == ROJO and t.inicio_futuro == date(2026, 11, 29)
    assert "inicia el 29/11/2026" in t.mensaje


def test_renovacion_anticipada_cuenta_dias_encadenados(servicios, recepcion, admin, cliente,
                                                       mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=27))  # vence 28/11
    membresia(servicios, admin, cliente.id, mensual, None)  # inicia 29/11
    t = servicios.asistencia.tarjeta(recepcion, cliente.id)
    assert t.color == VERDE and t.fecha_fin == date(2026, 12, 28) and t.inicio_futuro is None


def test_cumpleanos_y_alertas(servicios, recepcion, admin, mensual):
    c = registrar_cliente(servicios, admin, 1, fecha_nacimiento=date(1990, 11, 26))
    membresia(servicios, admin, c.id, mensual, HOY)
    servicios.alertas.crear(recepcion, c.id, "Falta copia del documento", "advertencia")
    critica = servicios.alertas.crear(admin, c.id, "Pago con cheque devuelto", "critica")
    servicios.alertas.crear(admin, c.id, "Desde la próxima semana", "info",
                            fecha_inicio=HOY + timedelta(days=7))
    t = servicios.asistencia.tarjeta(recepcion, c.id)
    assert t.cumple_hoy
    assert [a.nivel for a in t.alertas] == ["critica", "advertencia"]
    servicios.alertas.resolver(recepcion, critica)
    t = servicios.asistencia.tarjeta(recepcion, c.id)
    assert [a.mensaje for a in t.alertas] == ["Falta copia del documento"]
    with pytest.raises(ErrorValidacion, match="ya estaba resuelta"):
        servicios.alertas.resolver(admin, critica)


def test_alertas_validan_y_se_auditan(servicios, recepcion, cliente, fabrica):
    with pytest.raises(ErrorValidacion):
        servicios.alertas.crear(recepcion, cliente.id, "  ", "info")
    with pytest.raises(ErrorValidacion):
        servicios.alertas.crear(recepcion, cliente.id, "Mensaje", "urgente")
    with pytest.raises(ErrorValidacion):
        servicios.alertas.crear(recepcion, cliente.id, "Mensaje", "info",
                                fecha_fin=HOY - timedelta(days=1))
    alerta = servicios.alertas.crear(recepcion, cliente.id, "Trae certificado médico")
    servicios.alertas.resolver(recepcion, alerta)
    assert auditorias(fabrica, "alerta_creada")[0]["mensaje"] == "Trae certificado médico"
    assert auditorias(fabrica, "alerta_resuelta")[0]["cliente"] == cliente.codigo


# --- asistencia duplicada (sección 13, punto 3: avisar y confirmar) ---------------------

def test_duplicado_avisa_y_pide_confirmacion(servicios, recepcion, admin, cliente, mensual,
                                            reloj):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    primero = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    reloj.avanzar(hours=2)
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    assert r.estado == DUPLICADO_CONFIRMAR and r.asistencia_id is None
    assert r.ingreso_previo == reloj.ahora - timedelta(hours=2)
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo,
                                               confirmar_duplicado=True)
    assert r.estado == REGISTRADO and r.asistencia_id != primero.asistencia_id
    resumen = servicios.asistencia.resumen_del_dia(recepcion)
    assert resumen.asistentes == 1 and resumen.ingresos == 2


def test_duplicado_bloquear_o_permitir_segun_configuracion(servicios, recepcion, admin, cliente,
                                                          mensual):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    servicios.configuracion.guardar(admin, {"asistencia_duplicada": "bloquear"})
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo,
                                               confirmar_duplicado=True)
    assert r.estado == DUPLICADO_BLOQUEADO and r.asistencia_id is None
    servicios.configuracion.guardar(admin, {"asistencia_duplicada": "permitir"})
    assert servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo).estado == REGISTRADO


def test_rechazo_previo_no_cuenta_como_duplicado(servicios, recepcion, admin, cliente, mensual):
    servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)  # sin membresía
    membresia(servicios, admin, cliente.id, mensual, HOY)
    assert servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo).estado == REGISTRADO


def test_duplicado_de_ayer_no_cuenta(servicios, recepcion, admin, cliente, mensual, reloj):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=1))
    servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    reloj.avanzar(days=1)
    assert servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo).estado == REGISTRADO


# --- ingreso autorizado y renovar ahora ------------------------------------------------

def test_ingreso_autorizado_con_clave_de_admin(servicios, recepcion, admin, cliente, fabrica):
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    with pytest.raises(ErrorAutenticacion):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", "mala-clave")
    # Una clave de recepción no sirve: debe ser un administrador.
    with pytest.raises(ErrorPermiso):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "rita", CLAVE_PRUEBA)
    ok = servicios.asistencia.autorizar_ingreso(
        recepcion, r.asistencia_id, "ADMIN", CLAVE_PRUEBA, "Paga mañana")
    assert ok.estado == REGISTRADO and ok.tarjeta.resultado == "autorizado"
    assert "Ana Admin" in ok.tarjeta.mensaje
    with fabrica() as s:
        assert s.get(Asistencia, r.asistencia_id).resultado == "autorizado"
        registro = s.scalars(select(Auditoria).where(
            Auditoria.accion == "ingreso_autorizado")).one()
        assert registro.usuario_id == admin.id
    detalle = auditorias(fabrica, "ingreso_autorizado")[0]
    assert detalle == {"cliente": cliente.codigo, "resultado_anterior": "vencido",
                       "registrado_por": "rita", "motivo": "Paga mañana"}
    assert len(auditorias(fabrica, "autorizacion_fallida")) == 2
    assert "mala-clave" not in json.dumps(auditorias(fabrica, "autorizacion_fallida"))
    # Ya autorizado: no se puede autorizar dos veces.
    with pytest.raises(ErrorValidacion):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", CLAVE_PRUEBA)
    assert servicios.asistencia.resumen_del_dia(recepcion).asistentes == 1


def test_autorizacion_fallida_cuenta_para_el_bloqueo(servicios, recepcion, admin, cliente):
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    for _ in range(4):
        with pytest.raises(ErrorAutenticacion):
            servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", "x")
    from gimnasio.servicios.errores import UsuarioBloqueado

    with pytest.raises(UsuarioBloqueado):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", "x")
    with pytest.raises(UsuarioBloqueado):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", CLAVE_PRUEBA)


def test_solo_se_autorizan_rechazos_de_hoy(servicios, recepcion, admin, cliente, mensual, reloj):
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    reloj.avanzar(days=1)
    with pytest.raises(ErrorValidacion, match="de hoy"):
        servicios.asistencia.autorizar_ingreso(recepcion, r.asistencia_id, "admin", CLAVE_PRUEBA)
    membresia(servicios, admin, cliente.id, mensual, HOY + timedelta(days=1))
    ok = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    with pytest.raises(ErrorValidacion, match="ya estaba permitido"):
        servicios.asistencia.autorizar_ingreso(recepcion, ok.asistencia_id, "admin", CLAVE_PRUEBA)


def test_renovar_ahora_convierte_el_rechazo_en_ingreso(servicios, recepcion, admin, cliente,
                                                      mensual, fabrica):
    membresia(servicios, admin, cliente.id, mensual, HOY - timedelta(days=40))
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    with pytest.raises(ErrorValidacion, match="todavía no"):
        servicios.asistencia.confirmar_tras_renovar(recepcion, r.asistencia_id)
    servicios.pagos.registrar_membresia(recepcion, cliente.id, mensual.id,
                                        pago=DatosPago(120_000, "efectivo"))
    ok = servicios.asistencia.confirmar_tras_renovar(recepcion, r.asistencia_id)
    assert ok.tarjeta.color == VERDE and ok.asistencia_id == r.asistencia_id
    with fabrica() as s:
        assert s.get(Asistencia, r.asistencia_id).resultado == "permitido"
    assert auditorias(fabrica, "ingreso_tras_renovar")[0]["resultado_anterior"] == "vencido"
    assert servicios.asistencia.resumen_del_dia(recepcion).asistentes == 1


# --- eliminación lógica ----------------------------------------------------------------

def test_eliminar_asistencia_con_motivo(servicios, recepcion, admin, cliente, mensual, fabrica,
                                        reloj):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    with pytest.raises(ErrorValidacion, match="motivo"):
        servicios.asistencia.eliminar(recepcion, r.asistencia_id, " ")
    servicios.asistencia.eliminar(recepcion, r.asistencia_id, "Se registró por error")
    with fabrica() as s:
        a = s.get(Asistencia, r.asistencia_id)
        assert a.eliminada and a.eliminada_por == recepcion.id and a.motivo_eliminacion
    assert servicios.asistencia.resumen_del_dia(recepcion).asistentes == 0
    assert auditorias(fabrica, "asistencia_eliminada")[0]["motivo"] == "Se registró por error"
    with pytest.raises(ErrorValidacion, match="ya estaba eliminado"):
        servicios.asistencia.eliminar(admin, r.asistencia_id, "Otra vez")
    # Tras eliminarla, un nuevo ingreso hoy no es duplicado.
    assert servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo).estado == REGISTRADO


def test_recepcion_solo_elimina_las_de_hoy(servicios, recepcion, admin, cliente, mensual, reloj):
    membresia(servicios, admin, cliente.id, mensual, HOY)
    r = servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    reloj.avanzar(days=1)
    with pytest.raises(ErrorPermiso, match="solo puede eliminar asistencias del día"):
        servicios.asistencia.eliminar(recepcion, r.asistencia_id, "Error de ayer")
    servicios.asistencia.eliminar(admin, r.asistencia_id, "Error de ayer")


# --- consultas y reportes ---------------------------------------------------------------

@pytest.fixture
def historial(servicios, recepcion, admin, mensual, fabrica, reloj):
    """Tres clientes con asistencias del 20/11 al 26/11 (reloj vuelve al 26/11)."""
    trimestral = servicios.planes.crear(admin, "Trimestral", 90, 300_000)
    a = registrar_cliente(servicios, admin, 1, sexo="F")
    b = registrar_cliente(servicios, admin, 2, sexo="M")
    c = registrar_cliente(servicios, admin, 3, sexo="M")
    inicio = HOY - timedelta(days=6)
    membresia(servicios, admin, a.id, mensual, inicio)
    membresia(servicios, admin, b.id, trimestral, inicio)
    asignar_casillero(fabrica, a.id, "007")
    original = reloj.ahora
    reloj.avanzar(days=-6)
    for dia in range(7):
        servicios.asistencia.registrar_ingreso(recepcion, a.codigo)
        if dia % 2 == 0:
            servicios.asistencia.registrar_ingreso(recepcion, b.codigo)
        reloj.avanzar(days=1)
    reloj.ahora = original
    servicios.asistencia.registrar_ingreso(recepcion, c.codigo)  # rechazado: sin membresía
    return a, b, c, trimestral


def test_consultas_por_cliente_dia_rango_sexo_plan(servicios, admin, historial):
    a, b, c, trimestral = historial
    consultar = servicios.asistencia.consultar
    assert consultar(admin, FiltrosAsistencia(desde=HOY - timedelta(days=6), hasta=HOY)).total == 11
    assert consultar(admin, FiltrosAsistencia(cliente_id=a.id)).total == 7
    hoy = consultar(admin, FiltrosAsistencia(desde=HOY, hasta=HOY))
    assert hoy.total == 2 and {f.codigo for f in hoy.filas} == {a.codigo, b.codigo}
    con_rechazos = consultar(admin, FiltrosAsistencia(desde=HOY, hasta=HOY, incluir_rechazos=True))
    assert con_rechazos.total == 3
    assert consultar(admin, FiltrosAsistencia(resultado="vencido")).filas[0].codigo == c.codigo
    assert consultar(admin, FiltrosAsistencia(sexo="M")).total == 4
    por_plan = consultar(admin, FiltrosAsistencia(plan_id=trimestral.id))
    assert por_plan.total == 4 and {f.plan for f in por_plan.filas} == {"Trimestral"}
    fila = consultar(admin, FiltrosAsistencia(cliente_id=a.id)).filas[0]
    assert fila.casillero == "007" and fila.plan == "Mensual" and fila.usuario == "rita"


def test_recepcion_consulta_hoy_o_un_cliente(servicios, recepcion, historial):
    a, *_ = historial
    consultar = servicios.asistencia.consultar
    assert consultar(recepcion, FiltrosAsistencia(desde=HOY, hasta=HOY)).total == 2
    assert consultar(recepcion, FiltrosAsistencia(cliente_id=a.id)).total == 7
    with pytest.raises(ErrorPermiso):
        consultar(recepcion, FiltrosAsistencia(desde=HOY - timedelta(days=3), hasta=HOY))
    with pytest.raises(ErrorPermiso):
        consultar(recepcion, FiltrosAsistencia(desde=HOY, hasta=HOY, incluir_eliminadas=True))


def test_eliminadas_no_cuentan_pero_el_admin_las_ve(servicios, admin, historial):
    a, *_ = historial
    fila = servicios.asistencia.consultar(admin, FiltrosAsistencia(cliente_id=a.id)).filas[0]
    servicios.asistencia.eliminar(admin, fila.id, "Duplicado por error")
    assert servicios.asistencia.consultar(admin, FiltrosAsistencia(cliente_id=a.id)).total == 6
    todas = servicios.asistencia.consultar(
        admin, FiltrosAsistencia(cliente_id=a.id, incluir_eliminadas=True))
    assert todas.total == 7 and todas.filas[0].eliminada
    rep = servicios.asistencia.reporte(admin, ParametrosReporte("cliente", cliente_id=a.id))
    assert len(rep.filas) == 6


def test_reporte_del_dia_con_casillero(servicios, recepcion, admin, historial):
    a, b, *_ = historial
    rep = servicios.asistencia.reporte(recepcion, ParametrosReporte("dia"))
    assert rep.encabezados[6] == "Casillero"
    por_codigo = {f[2]: f for f in rep.filas}
    assert por_codigo[a.codigo][6] == "007" and por_codigo[b.codigo][6] == ""
    assert por_codigo[a.codigo][1] == "10:00"  # hora de Bogotá
    assert "2 ingresos" in rep.resumen
    with pytest.raises(ErrorPermiso):
        servicios.asistencia.reporte(recepcion, ParametrosReporte("dia", desde=HOY - timedelta(1)))
    with pytest.raises(ErrorPermiso):
        servicios.asistencia.reporte(recepcion, ParametrosReporte("ranking"))
    assert len(servicios.asistencia.reporte(
        admin, ParametrosReporte("dia", desde=HOY - timedelta(days=1))).filas) == 1


def test_recepcion_reporte_de_un_cliente_solo_historial_completo(servicios, recepcion, historial):
    a, *_ = historial
    rep = servicios.asistencia.reporte(recepcion, ParametrosReporte("cliente", cliente_id=a.id))
    assert rep.filas and {f[2] for f in rep.filas} == {a.codigo}
    with pytest.raises(ErrorPermiso, match="todo el historial"):
        servicios.asistencia.reporte(recepcion, ParametrosReporte(
            "cliente", cliente_id=a.id, desde=HOY - timedelta(days=7), hasta=HOY))
    with pytest.raises(ErrorValidacion):
        servicios.asistencia.reporte(recepcion, ParametrosReporte("cliente"))


def test_instantanea_del_casillero_no_cambia_al_liberar(servicios, admin, historial, fabrica,
                                                        reloj):
    a, *_ = historial
    with fabrica() as s:
        asignacion = s.scalars(select(CasilleroAsignacion)).one()
        asignacion.fecha_liberacion = reloj.ahora
        s.commit()
    rep = servicios.asistencia.reporte(admin, ParametrosReporte("cliente", cliente_id=a.id))
    assert {f[6] for f in rep.filas} == {"007"}  # RN-11
    assert servicios.asistencia.tarjeta(admin, a.id).casillero is None


def test_reporte_franja_ranking_y_ausentes(servicios, admin, historial):
    a, b, c, _ = historial
    desde = HOY - timedelta(days=6)
    franja = servicios.asistencia.reporte(admin, ParametrosReporte("franja", desde, HOY))
    assert franja.filas == [("10:00 – 10:59", 11, 1.6, "100,0 %")]
    ranking = servicios.asistencia.reporte(admin, ParametrosReporte("ranking", desde, HOY))
    assert [(f[0], f[1], f[3]) for f in ranking.filas] == [(1, a.codigo, 7), (2, b.codigo, 4)]
    assert ranking.filas[0][5] == "007"
    ausentes = servicios.asistencia.reporte(admin, ParametrosReporte("ausentes", dias=1))
    assert ausentes.filas == []  # los dos vinieron hoy; c nunca ha entrado
    con_nunca = servicios.asistencia.reporte(
        admin, ParametrosReporte("ausentes", dias=1, incluir_nunca=True))
    assert [f[0] for f in con_nunca.filas] == [c.codigo] and con_nunca.filas[0][3] == "Nunca"
    with pytest.raises(ErrorValidacion):
        servicios.asistencia.reporte(admin, ParametrosReporte("ausentes", dias=0))


def test_ausentes_hace_n_dias(servicios, admin, recepcion, mensual, reloj):
    c = registrar_cliente(servicios, admin, 1)
    membresia(servicios, admin, c.id, mensual, HOY - timedelta(days=20))
    reloj.avanzar(days=-20)
    servicios.asistencia.registrar_ingreso(recepcion, c.codigo)
    reloj.avanzar(days=20)
    rep = servicios.asistencia.reporte(admin, ParametrosReporte("ausentes", dias=15))
    assert rep.filas[0][:5] == (c.codigo, "Laura Ríos 1", "3001234501", date(2026, 11, 6), 20)
    assert rep.filas[0][5] == "Vigente"
    assert servicios.asistencia.reporte(admin, ParametrosReporte("ausentes", dias=25)).filas == []


def test_exportar_reporte(servicios, admin, recepcion, historial, tmp_path, fabrica):
    ruta = servicios.asistencia.exportar(admin, ParametrosReporte("rango", HOY - timedelta(6), HOY),
                                         tmp_path / "rango.xlsx", "xlsx")
    from openpyxl import load_workbook

    hoja = load_workbook(ruta).active
    assert hoja.max_row == 12 and hoja["G1"].value == "Casillero"
    pdf = servicios.asistencia.exportar(recepcion, ParametrosReporte("dia"),
                                        tmp_path / "dia.pdf", "pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert [d["reporte"] for d in auditorias(fabrica, "asistencias_exportadas")] == ["rango", "dia"]


def test_filtro_sin_asistir_ignora_rechazos(servicios, admin, recepcion, cliente):
    from gimnasio.servicios.clientes import FiltrosClientes

    servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)  # rechazado
    pagina = servicios.clientes.buscar(admin, FiltrosClientes(sin_asistir_dias=30))
    assert [f.id for f in pagina.filas] == [cliente.id]


def test_permisos_de_asistencia(servicios, cliente):
    with pytest.raises(ErrorPermiso):
        servicios.asistencia.registrar_ingreso(None, cliente.codigo)
    with pytest.raises(ErrorPermiso):
        servicios.alertas.crear(None, cliente.id, "Hola")


def test_usuario_desactivado_no_registra(servicios, admin, recepcion, cliente):
    servicios.usuarios.desactivar(admin, recepcion.id)
    with pytest.raises(ErrorPermiso):
        servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)


def test_rendimiento_registro_con_muchos_datos(servicios, admin, recepcion, mensual, fabrica):
    """Un ingreso con miles de asistencias previas sigue siendo instantáneo."""
    import time

    c = registrar_cliente(servicios, admin, 1)
    membresia(servicios, admin, c.id, mensual, HOY)
    with fabrica() as s:
        otro = s.scalar(select(Cliente.id).where(Cliente.id == c.id))
        s.add_all(Asistencia(cliente_id=otro, fecha=HOY - timedelta(days=i % 300),
                             resultado="permitido", usuario_id=admin.id) for i in range(5000))
        s.commit()
    inicio = time.perf_counter()
    servicios.asistencia.registrar_ingreso(recepcion, c.codigo, confirmar_duplicado=True)
    servicios.asistencia.resumen_del_dia(recepcion)
    assert time.perf_counter() - inicio < 0.2
