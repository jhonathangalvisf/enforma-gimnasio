"""Pruebas de Invitados (sección 3.7): reutilización por documento, contador de visitas
calculado (RN-10), detalle de fechas, duplicado del día, límite mensual con autorización
del administrador, eliminación lógica con motivo, permisos y reportes."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria, Invitado, InvitadoAsistencia
from gimnasio.servicios.clientes import DatosCliente
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorPermiso, ErrorValidacion
from gimnasio.servicios.invitados import (
    DUPLICADO_BLOQUEADO, DUPLICADO_CONFIRMAR, LIMITE_AUTORIZAR, REGISTRADA, DatosInvitado,
    ParametrosReporteInvitados,
)
from tests.conftest import CLAVE_PRUEBA

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


def nuevo_invitado(servicios, actual, documento="1.020.304", nombre="José Pérez",
                   telefono=""):
    ficha, _ = servicios.invitados.registrar(actual, DatosInvitado(nombre, documento, telefono))
    return ficha


@pytest.fixture
def anfitrion(servicios, admin):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="5566778899", nombres="Laura", apellidos="Ríos",
        sexo="F", telefonos=["3001234567"], fecha_nacimiento=date(1990, 3, 15)))


def visita_en(servicios, actual, invitado_id, reloj, dias_atras, anfitrion_id=None):
    """Registra una visita `dias_atras` días antes de hoy y devuelve el reloj a hoy."""
    reloj.avanzar(days=-dias_atras)
    r = servicios.invitados.registrar_visita(actual, invitado_id, anfitrion_id,
                                             confirmar_duplicado=True)
    reloj.avanzar(days=dias_atras)
    assert r.estado == REGISTRADA
    return r


# --- registro y reutilización --------------------------------------------------------

def test_registrar_normaliza_y_audita(servicios, recepcion, fabrica):
    ficha, nuevo = servicios.invitados.registrar(
        recepcion, DatosInvitado("  josé   pérez ", "1.020-304", "300 123 4567"))
    assert nuevo
    assert (ficha.nombre, ficha.documento, ficha.telefono) == ("josé pérez", "1020304",
                                                                "3001234567")
    assert ficha.total_visitas == 0 and ficha.texto_contador.startswith("Aún no")
    assert ficha.creado_por == "rita"
    assert auditorias(fabrica, "invitado_registrado")[0]["documento"] == "1020304"


def test_mismo_documento_no_duplica_y_el_contador_aumenta(servicios, recepcion, fabrica):
    """Criterio de aceptación 7 de la especificación."""
    primero = nuevo_invitado(servicios, recepcion, "1020304")
    servicios.invitados.registrar_visita(recepcion, primero.id)
    segundo, nuevo = servicios.invitados.registrar(
        recepcion, DatosInvitado("Jose Perez", "1.020.304", "3109876543"))
    assert not nuevo and segundo.id == primero.id
    assert segundo.telefono == "3109876543"  # completa el teléfono que faltaba
    assert segundo.nombre == "José Pérez"  # el nombre guardado no cambia
    r = servicios.invitados.registrar_visita(recepcion, segundo.id, confirmar_duplicado=True)
    assert r.ficha.total_visitas == 2
    assert r.ficha.texto_contador == "Lleva 2 visitas como invitado"
    with fabrica() as s:
        assert s.scalar(select(func.count(Invitado.id))) == 1


def test_validaciones(servicios, recepcion):
    with pytest.raises(ErrorValidacion, match="nombre"):
        servicios.invitados.registrar(recepcion, DatosInvitado("Jo", "1020304"))
    with pytest.raises(ErrorValidacion, match="documento"):
        servicios.invitados.registrar(recepcion, DatosInvitado("José Pérez", ""))
    with pytest.raises(ErrorValidacion, match="documento"):
        servicios.invitados.registrar(recepcion, DatosInvitado("José Pérez", "12/34"))
    with pytest.raises(ErrorValidacion, match="teléfono"):
        servicios.invitados.registrar(recepcion, DatosInvitado("José Pérez", "1020304", "abc"))


def test_contador_se_calcula_y_no_se_guarda():
    """RN-10: ninguna columna guarda el número de visitas."""
    columnas = set(Invitado.__table__.columns.keys())
    assert not {c for c in columnas if "visita" in c or "contador" in c or "total" in c}


# --- contador y detalle de fechas ----------------------------------------------------

def test_ficha_muestra_contador_y_detalle_de_fechas(servicios, recepcion, anfitrion, reloj):
    inv = nuevo_invitado(servicios, recepcion)
    visita_en(servicios, recepcion, inv.id, reloj, 40, anfitrion.id)  # 17/10/2026
    visita_en(servicios, recepcion, inv.id, reloj, 10)  # 16/11/2026
    servicios.invitados.registrar_visita(recepcion, inv.id, anfitrion.id)  # hoy
    ficha = servicios.invitados.ficha(recepcion, inv.id)
    assert ficha.total_visitas == 3
    assert ficha.visitas_mes == 2  # noviembre
    assert ficha.primera_visita == date(2026, 10, 17)
    assert ficha.ultima_visita == HOY
    assert [v.fecha for v in ficha.visitas] == [HOY, date(2026, 11, 16), date(2026, 10, 17)]
    assert ficha.visitas[0].anfitrion == f"{anfitrion.codigo} Laura Ríos"
    assert ficha.visitas[1].anfitrion == ""
    assert ficha.visitas[0].usuario == "rita"
    assert servicios.invitados.contar_visitas(recepcion, inv.id, desde=date(2026, 11, 1)) == 2


def test_lista_trae_total_mes_y_ultima_visita(servicios, recepcion, reloj):
    a = nuevo_invitado(servicios, recepcion, "111222", "Ana Gómez")
    b = nuevo_invitado(servicios, recepcion, "333444", "Beto Ruiz", "3005550000")
    nuevo_invitado(servicios, recepcion, "555666", "Carla Díaz")
    visita_en(servicios, recepcion, a.id, reloj, 60)
    visita_en(servicios, recepcion, a.id, reloj, 3)
    servicios.invitados.registrar_visita(recepcion, b.id)
    filas = servicios.invitados.buscar(recepcion)
    assert [f.nombre for f in filas] == ["Beto Ruiz", "Ana Gómez", "Carla Díaz"]
    por_nombre = {f.nombre: f for f in filas}
    assert (por_nombre["Ana Gómez"].visitas, por_nombre["Ana Gómez"].visitas_mes) == (2, 1)
    assert por_nombre["Ana Gómez"].ultima_visita == date(2026, 11, 23)
    assert por_nombre["Carla Díaz"].visitas == 0 and por_nombre["Carla Díaz"].ultima_visita is None
    # Búsqueda por nombre sin tildes, por documento y por teléfono.
    assert [f.nombre for f in servicios.invitados.buscar(recepcion, "gomez")] == ["Ana Gómez"]
    assert [f.nombre for f in servicios.invitados.buscar(recepcion, "3334")] == ["Beto Ruiz"]
    assert [f.nombre for f in servicios.invitados.buscar(recepcion, "555 0000")] == ["Beto Ruiz"]
    assert servicios.invitados.buscar(recepcion, "zzz") == []


def test_por_documento_y_aviso_si_ya_es_cliente(servicios, recepcion, anfitrion):
    assert servicios.invitados.por_documento(recepcion, "999") is None
    inv = nuevo_invitado(servicios, recepcion, "55.667.788-99", "Laura Ríos")
    assert servicios.invitados.por_documento(recepcion, "5566778899").id == inv.id
    assert inv.cliente_codigo == anfitrion.codigo
    assert servicios.invitados.cliente_con_documento(recepcion, "5566778899") == anfitrion.codigo
    with pytest.raises(ErrorValidacion, match="propio anfitrión"):
        servicios.invitados.registrar_visita(recepcion, inv.id, anfitrion.id)


# --- duplicado y límite ----------------------------------------------------------------

def test_visita_duplicada_del_dia_avisa_y_confirma(servicios, recepcion):
    inv = nuevo_invitado(servicios, recepcion)
    assert servicios.invitados.registrar_visita(recepcion, inv.id).estado == REGISTRADA
    r = servicios.invitados.registrar_visita(recepcion, inv.id)
    assert r.estado == DUPLICADO_CONFIRMAR and r.visita_previa_hoy is not None
    assert r.ficha.total_visitas == 1  # no guardó nada
    r = servicios.invitados.registrar_visita(recepcion, inv.id, confirmar_duplicado=True)
    assert r.estado == REGISTRADA and r.ficha.total_visitas == 2


def test_visita_duplicada_bloqueada_por_parametro(servicios, admin, recepcion):
    servicios.configuracion.guardar(admin, {"asistencia_duplicada": "bloquear"})
    inv = nuevo_invitado(servicios, recepcion)
    servicios.invitados.registrar_visita(recepcion, inv.id)
    r = servicios.invitados.registrar_visita(recepcion, inv.id, confirmar_duplicado=True)
    assert r.estado == DUPLICADO_BLOQUEADO and r.ficha.total_visitas == 1


def test_sin_limite_por_defecto_ni_limite_por_anfitrion(servicios, recepcion, anfitrion, reloj):
    for i in range(6):
        inv = nuevo_invitado(servicios, recepcion, f"77700{i}", f"Invitado {i}")
        for d in (1, 2, 3, 4, 5):
            visita_en(servicios, recepcion, inv.id, reloj, d, anfitrion.id)
    rep = servicios.invitados.reporte(recepcion, ParametrosReporteInvitados("visitas"))
    assert rep.filas == []  # hoy no hay visitas
    assert servicios.invitados.buscar(recepcion)[0].visitas_mes == 5


def test_limite_mensual_pide_autorizacion_del_admin(servicios, admin, recepcion, reloj, fabrica):
    servicios.configuracion.guardar(admin, {"invitado_visitas_mes": 2})
    inv = nuevo_invitado(servicios, recepcion)
    visita_en(servicios, recepcion, inv.id, reloj, 30)  # octubre: no cuenta para noviembre
    visita_en(servicios, recepcion, inv.id, reloj, 5)
    visita_en(servicios, recepcion, inv.id, reloj, 2)
    r = servicios.invitados.registrar_visita(recepcion, inv.id)
    assert r.estado == LIMITE_AUTORIZAR and r.ficha.limite_alcanzado
    assert r.ficha.visitas_mes == 2 and r.ficha.total_visitas == 3
    with pytest.raises(ErrorAutenticacion):
        servicios.invitados.registrar_visita(recepcion, inv.id, admin_usuario="admin",
                                             admin_clave="mala")
    with pytest.raises(ErrorPermiso):  # recepción no es administrador
        servicios.invitados.registrar_visita(recepcion, inv.id, admin_usuario="rita",
                                             admin_clave=CLAVE_PRUEBA)
    r = servicios.invitados.registrar_visita(
        recepcion, inv.id, admin_usuario="admin", admin_clave=CLAVE_PRUEBA,
        motivo_autorizacion="viene a conocer")
    assert r.estado == REGISTRADA and r.ficha.visitas_mes == 3
    assert r.ficha.visitas[0].autorizada_por == "admin"
    detalle = auditorias(fabrica, "invitado_visita_autorizada")[0]
    assert detalle["registrado_por"] == "rita" and detalle["limite_mes"] == 2
    assert "clave" not in json.dumps(detalle)


def test_admin_con_sesion_autoriza_sin_clave(servicios, admin, reloj):
    servicios.configuracion.guardar(admin, {"invitado_visitas_mes": 1})
    inv = nuevo_invitado(servicios, admin)
    visita_en(servicios, admin, inv.id, reloj, 1)
    r = servicios.invitados.registrar_visita(admin, inv.id)
    assert r.estado == REGISTRADA and r.ficha.visitas[0].autorizada_por == "admin"


def test_limite_en_configuracion_valida_rango(servicios, admin):
    with pytest.raises(ErrorValidacion):
        servicios.configuracion.guardar(admin, {"invitado_visitas_mes": -1})
    assert servicios.configuracion.obtener("invitado_visitas_mes") == 0


# --- eliminación lógica y permisos -----------------------------------------------------

def test_eliminar_visita_con_motivo_descuenta_del_contador(servicios, recepcion, fabrica):
    inv = nuevo_invitado(servicios, recepcion)
    r = servicios.invitados.registrar_visita(recepcion, inv.id)
    with pytest.raises(ErrorValidacion, match="motivo"):
        servicios.invitados.eliminar_visita(recepcion, r.visita_id, " ")
    servicios.invitados.eliminar_visita(recepcion, r.visita_id, "Registrado por error")
    ficha = servicios.invitados.ficha(recepcion, inv.id)
    assert ficha.total_visitas == 0 and ficha.visitas == []  # recepción no ve eliminadas
    with fabrica() as s:
        visita = s.get(InvitadoAsistencia, r.visita_id)
        assert visita.eliminada and visita.eliminada_por == recepcion.id  # no se borra
    with pytest.raises(ErrorValidacion, match="ya estaba"):
        servicios.invitados.eliminar_visita(recepcion, r.visita_id, "otra vez")
    assert auditorias(fabrica, "invitado_visita_eliminada")[0]["motivo"] == "Registrado por error"


def test_recepcion_solo_elimina_visitas_de_hoy(servicios, admin, recepcion, reloj):
    inv = nuevo_invitado(servicios, recepcion)
    vieja = visita_en(servicios, recepcion, inv.id, reloj, 3)
    with pytest.raises(ErrorPermiso, match="hoy"):
        servicios.invitados.eliminar_visita(recepcion, vieja.visita_id, "Error de fecha")
    servicios.invitados.eliminar_visita(admin, vieja.visita_id, "Error de fecha")
    ficha = servicios.invitados.ficha(admin, inv.id)
    assert ficha.total_visitas == 0
    assert ficha.visitas[0].eliminada  # el administrador sí ve la eliminada


def test_modificar_documento_solo_admin(servicios, admin, recepcion, fabrica):
    inv = nuevo_invitado(servicios, recepcion, "1020304")
    nuevo_invitado(servicios, recepcion, "9999999", "Otra Persona")
    ficha = servicios.invitados.modificar(recepcion, inv.id,
                                          DatosInvitado("José A. Pérez", "1020304", "3001112233"))
    assert ficha.nombre == "José A. Pérez" and ficha.telefono == "3001112233"
    with pytest.raises(ErrorPermiso):
        servicios.invitados.modificar(recepcion, inv.id, DatosInvitado("José", "1020305"))
    with pytest.raises(ErrorValidacion, match="otro invitado"):
        servicios.invitados.modificar(admin, inv.id, DatosInvitado("José Pérez", "9999999"))
    assert servicios.invitados.modificar(admin, inv.id,
                                         DatosInvitado("José Pérez", "1020305")).documento == "1020305"
    assert len(auditorias(fabrica, "invitado_modificado")) == 2


def test_sin_sesion_no_hay_acceso(servicios):
    with pytest.raises(ErrorPermiso):
        servicios.invitados.buscar(None)
    with pytest.raises(ErrorPermiso):
        servicios.invitados.registrar(None, DatosInvitado("José Pérez", "1020304"))


def test_usuario_desactivado_no_registra(servicios, admin, recepcion):
    servicios.usuarios.desactivar(admin, recepcion.id)
    with pytest.raises(ErrorPermiso, match="desactivado"):
        servicios.invitados.registrar(recepcion, DatosInvitado("José Pérez", "1020304"))


# --- reportes ----------------------------------------------------------------------------

@pytest.fixture
def historial(servicios, recepcion, anfitrion, reloj):
    a = nuevo_invitado(servicios, recepcion, "111222", "Ana Gómez")
    b = nuevo_invitado(servicios, recepcion, "333444", "Beto Ruiz")
    visita_en(servicios, recepcion, a.id, reloj, 20, anfitrion.id)
    visita_en(servicios, recepcion, a.id, reloj, 5, anfitrion.id)
    visita_en(servicios, recepcion, b.id, reloj, 5)
    servicios.invitados.registrar_visita(recepcion, a.id, anfitrion.id)
    return a, b


def test_reporte_visitas_por_rango_y_por_anfitrion(servicios, admin, anfitrion, historial):
    p = ParametrosReporteInvitados("visitas", date(2026, 11, 1), HOY)
    rep = servicios.invitados.reporte(admin, p)
    assert len(rep.filas) == 4
    assert rep.resumen == "4 visitas · 2 invitados distintos"
    assert rep.filas[0][0] == HOY and rep.filas[0][3] == "Ana Gómez"
    rep = servicios.invitados.reporte(
        admin, ParametrosReporteInvitados("visitas", date(2026, 11, 1), HOY, anfitrion.id))
    assert len(rep.filas) == 3 and "Laura Ríos" in rep.titulo
    assert {f[3] for f in rep.filas} == {"Ana Gómez"}


def test_reporte_visitas_por_invitado_cuenta_periodo_y_total(servicios, admin, historial):
    rep = servicios.invitados.reporte(
        admin, ParametrosReporteInvitados("invitados", date(2026, 11, 15), HOY))
    assert [(f[1], f[3], f[6]) for f in rep.filas] == [("Ana Gómez", 2, 3), ("Beto Ruiz", 1, 1)]
    assert rep.filas[0][4] == date(2026, 11, 21) and rep.filas[0][5] == HOY


def test_reporte_por_anfitrion(servicios, admin, anfitrion, historial):
    rep = servicios.invitados.reporte(
        admin, ParametrosReporteInvitados("anfitriones", date(2026, 11, 1), HOY))
    assert rep.filas == [(anfitrion.codigo, "Laura Ríos", 1, 3, HOY)]
    assert "1 visitas sin anfitrión" in rep.resumen


def test_recepcion_solo_ve_el_reporte_de_hoy(servicios, recepcion, historial):
    rep = servicios.invitados.reporte(recepcion, ParametrosReporteInvitados("visitas"))
    assert len(rep.filas) == 1
    with pytest.raises(ErrorPermiso):
        servicios.invitados.reporte(
            recepcion, ParametrosReporteInvitados("visitas", date(2026, 11, 1), HOY))
    with pytest.raises(ErrorPermiso):
        servicios.invitados.reporte(recepcion, ParametrosReporteInvitados("anfitriones"))


def test_exportar_excel_y_pdf_queda_en_auditoria(servicios, admin, historial, tmp_path, fabrica):
    p = ParametrosReporteInvitados("invitados", date(2026, 11, 1), HOY)
    xlsx = servicios.invitados.exportar(admin, p, tmp_path / "inv.xlsx", "xlsx")
    pdf = servicios.invitados.exportar(admin, p, tmp_path / "inv.pdf", "pdf")
    assert xlsx.exists() and pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    assert [d["formato"] for d in auditorias(fabrica, "invitados_exportados")] == ["xlsx", "pdf"]
    with pytest.raises(ErrorValidacion):
        servicios.invitados.exportar(admin, p, tmp_path / "inv.csv", "csv")
