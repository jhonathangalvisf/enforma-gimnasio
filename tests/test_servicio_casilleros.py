"""Servicio de casilleros (Fase 5): catálogo, asignar con vencimiento propio, renovar,
cambiar, liberar, zonas por sexo, permisos, listas, sugerencias y Recepción."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Asistencia, Auditoria, Casillero, CasilleroAsignacion, Pago
from gimnasio.servicios.asistencia import AMARILLO, VERDE
from gimnasio.servicios.casilleros import (
    FiltrosCasilleros, VigenciaCasillero, calcular_vigencia_casillero, normalizar_numero,
    zona_permitida,
)
from gimnasio.servicios.clientes import DatosCliente
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import DatosPago

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def cliente(servicios, admin, n=1, sexo="F", **campos):
    datos = dict(tipo_documento="CC", documento=f"5060708{n:03d}", nombres="Ana",
                 apellidos=f"Gómez {n}", sexo=sexo, telefonos=[f"31012345{n:02d}"],
                 fecha_nacimiento=date(1992, 5, 10))
    datos.update(campos)
    return servicios.clientes.registrar(admin, DatosCliente(**datos))


@pytest.fixture
def cas(servicios):
    return servicios.casilleros


@pytest.fixture
def catalogo(cas, admin):
    """Casilleros 001-003 de hombres, 004-006 de mujeres y M-1 mixto."""
    cas.crear_rango(admin, 1, 3, "hombres")
    cas.crear_rango(admin, 4, 6, "mujeres")
    cas.crear(admin, "M-1", "mixto")
    return {n: i for i, n, _ in cas.libres(admin)}


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


# --- reglas puras ---------------------------------------------------------------------

def test_vigencia_del_casillero_se_calcula():
    assert calcular_vigencia_casillero(None, HOY, 5) == (VigenciaCasillero.SIN_FECHA, None)
    assert calcular_vigencia_casillero(HOY, HOY, 5) == (VigenciaCasillero.POR_VENCER, 0)
    assert calcular_vigencia_casillero(HOY + timedelta(days=10), HOY, 5)[0] == \
        VigenciaCasillero.AL_DIA
    assert calcular_vigencia_casillero(HOY - timedelta(days=3), HOY, 5) == \
        (VigenciaCasillero.VENCIDO, -3)


def test_zonas_por_sexo():
    assert zona_permitida("hombres", "M") and not zona_permitida("hombres", "F")
    assert zona_permitida("mujeres", "F") and not zona_permitida("mujeres", "M")
    assert not zona_permitida("hombres", "O") and not zona_permitida("mujeres", "O")
    assert all(zona_permitida("mixto", s) for s in "MFO")


def test_numero_de_casillero_se_normaliza():
    assert normalizar_numero(" a-12 ") == "A-12"
    for malo in ("", "12 3", "ñ", "12345678901"):
        with pytest.raises(ErrorValidacion):
            normalizar_numero(malo)


# --- catálogo -------------------------------------------------------------------------

def test_crear_rango_omite_existentes_y_audita(cas, admin, fabrica):
    assert cas.crear_rango(admin, 1, 3, "mixto") == ["001", "002", "003"]
    assert cas.crear_rango(admin, 2, 5, "mixto") == ["004", "005"]
    assert auditorias(fabrica, "casilleros_creados")[1]["omitidos"] == 2
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        cas.crear(admin, "003", "mixto")


def test_catalogo_solo_admin(cas, recepcion, admin):
    with pytest.raises(ErrorPermiso):
        cas.crear(recepcion, "001", "mixto")
    with pytest.raises(ErrorPermiso):
        cas.crear_rango(recepcion, 1, 5, "mixto")
    k = cas.crear(admin, "001", "mixto")
    with pytest.raises(ErrorPermiso):
        cas.modificar(recepcion, k, "001", "hombres")
    with pytest.raises(ErrorPermiso):
        cas.poner_en_mantenimiento(recepcion, k, "Chapa dañada")


def test_mantenimiento_no_se_asigna_y_no_aplica_si_esta_ocupado(cas, servicios, admin, catalogo):
    c = cliente(servicios, admin)
    cas.poner_en_mantenimiento(admin, catalogo["004"], "Chapa dañada")
    assert "004" not in {n for _, n, _ in cas.libres(admin)}
    with pytest.raises(ErrorValidacion, match="mantenimiento"):
        cas.asignar(admin, catalogo["004"], c.id)
    cas.habilitar(admin, catalogo["004"])
    cas.asignar(admin, catalogo["004"], c.id)
    with pytest.raises(ErrorValidacion, match="ocupado"):
        cas.poner_en_mantenimiento(admin, catalogo["004"], "Revisión")


def test_no_se_cambia_la_zona_si_el_ocupante_no_corresponde(cas, servicios, admin, catalogo):
    c = cliente(servicios, admin, sexo="F")
    cas.asignar(admin, catalogo["M-1"], c.id)
    with pytest.raises(ErrorValidacion, match="no puede pasar"):
        cas.modificar(admin, catalogo["M-1"], "M-1", "hombres")
    assert cas.modificar(admin, catalogo["M-1"], "M-1", "mujeres", "Junto a la ducha") == \
        ["zona", "notas"]


# --- asignar con vencimiento propio ---------------------------------------------------

def test_asignar_con_vencimiento_propio_y_pago(cas, servicios, recepcion, admin, catalogo, fabrica):
    c = cliente(servicios, admin)
    r = cas.asignar(recepcion, catalogo["005"], c.id, fecha_inicio=date(2026, 11, 20), dias=30,
                    pago=DatosPago(20_000, "efectivo"))
    assert r.numero == "005" and r.vence == date(2026, 12, 19)
    assert r.pago is not None and r.pago.monto == 20_000
    with fabrica() as s:
        pago = s.get(Pago, r.pago.id)
        assert pago.concepto == "casillero" and pago.casillero_asignacion_id == r.asignacion_id
        assert pago.membresia_id is None
        assert s.get(Casillero, catalogo["005"]).estado == "ocupado"
    info = cas.de_cliente(recepcion, c.id)
    assert info.numero == "005" and info.vence == date(2026, 12, 19)
    assert info.vigencia == VigenciaCasillero.AL_DIA and info.dias == 23
    assert auditorias(fabrica, "casillero_asignado")[0]["vence"] == "19/12/2026"
    # El recibo dice qué casillero se pagó.
    assert servicios.pagos.datos_recibo(recepcion, r.pago.id).detalle == "Casillero 005"


def test_asignar_sin_membresia_y_con_dias_por_defecto(cas, servicios, admin, catalogo):
    """El casillero no depende de la membresía: un cliente sin plan también puede tenerlo."""
    c = cliente(servicios, admin)
    servicios.configuracion.guardar(admin, {"casillero_dias": 15, "casillero_precio": 25_000})
    p = cas.proponer(admin)
    assert (p.inicio, p.dias, p.vence, p.precio) == (HOY, 15, HOY + timedelta(days=14), 25_000)
    assert cas.asignar(admin, catalogo["006"], c.id).vence == HOY + timedelta(days=14)


def test_zona_de_otro_sexo_se_bloquea(cas, servicios, admin, catalogo):
    mujer = cliente(servicios, admin, 1, sexo="F")
    hombre = cliente(servicios, admin, 2, sexo="M")
    otro = cliente(servicios, admin, 3, sexo="O")
    with pytest.raises(ErrorValidacion, match="zona hombres"):
        cas.asignar(admin, catalogo["001"], mujer.id)
    with pytest.raises(ErrorValidacion, match="zona mujeres"):
        cas.asignar(admin, catalogo["004"], hombre.id)
    with pytest.raises(ErrorValidacion):
        cas.asignar(admin, catalogo["001"], otro.id)
    cas.asignar(admin, catalogo["M-1"], otro.id)
    assert [n for _, n, _ in cas.libres(admin, sexo="M")] == ["001", "002", "003"]
    assert [n for _, n, _ in cas.libres(admin, sexo="F")] == ["004", "005", "006"]


def test_un_cliente_un_casillero_desde_el_servicio(cas, servicios, admin, catalogo):
    a = cliente(servicios, admin, 1)
    b = cliente(servicios, admin, 2)
    cas.asignar(admin, catalogo["004"], a.id)
    with pytest.raises(ErrorValidacion, match="ya tiene el casillero 004"):
        cas.asignar(admin, catalogo["005"], a.id)
    with pytest.raises(ErrorValidacion, match="ya está asignado a Ana Gómez 1"):
        cas.asignar(admin, catalogo["004"], b.id)


def test_cliente_inactivo_no_recibe_casillero(cas, servicios, admin, catalogo):
    c = cliente(servicios, admin)
    servicios.clientes.inactivar(admin, c.id, "Se retiró")
    with pytest.raises(ErrorValidacion, match="inactivo"):
        cas.asignar(admin, catalogo["004"], c.id)


def test_pago_requiere_permiso_y_monto_valido_sin_dejar_asignacion(cas, servicios, admin,
                                                                   catalogo, fabrica):
    c = cliente(servicios, admin)
    with pytest.raises(ErrorValidacion):
        cas.asignar(admin, catalogo["004"], c.id, pago=DatosPago(0, "efectivo"))
    with pytest.raises(ErrorValidacion):
        cas.asignar(admin, catalogo["004"], c.id, pago=DatosPago(10_000, "tarjeta"))  # sin ref.
    with fabrica() as s:
        assert s.scalar(select(CasilleroAsignacion)) is None  # todo o nada
        assert s.get(Casillero, catalogo["004"]).estado == "disponible"


def test_dias_e_inicio_se_validan(cas, servicios, admin, catalogo):
    c = cliente(servicios, admin)
    with pytest.raises(ErrorValidacion, match="días"):
        cas.asignar(admin, catalogo["004"], c.id, dias=0)
    with pytest.raises(ErrorValidacion, match="inicio"):
        cas.asignar(admin, catalogo["004"], c.id, fecha_inicio=HOY - timedelta(days=90))


# --- renovar, corregir, cambiar y liberar ---------------------------------------------

def test_renovar_al_dia_sigue_desde_el_vencimiento(cas, servicios, recepcion, admin, catalogo,
                                                   fabrica):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id, dias=30)  # vence 25/12/2026
    p = cas.proponer(recepcion, r.asignacion_id)
    assert p.inicio == date(2026, 12, 26) and p.vence_actual == date(2026, 12, 25)
    ren = cas.renovar(recepcion, r.asignacion_id, dias=30, pago=DatosPago(20_000, "efectivo"))
    assert ren.vence_anterior == date(2026, 12, 25) and ren.vence == date(2027, 1, 24)
    assert auditorias(fabrica, "casillero_renovado")[0]["vence_antes"] == "25/12/2026"


def test_renovar_vencido_empieza_hoy(cas, servicios, admin, catalogo, reloj):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id, dias=10)  # vence 05/12/2026
    reloj.avanzar(days=20)  # 16/12/2026
    assert cas.de_cliente(admin, c.id).vigencia == VigenciaCasillero.VENCIDO
    ren = cas.renovar(admin, r.asignacion_id, dias=30)
    assert ren.vence == date(2026, 12, 16) + timedelta(days=29)


def test_renovar_no_puede_acortar(cas, servicios, admin, catalogo):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id, dias=30)
    with pytest.raises(ErrorValidacion, match="posterior"):
        cas.renovar(admin, r.asignacion_id, fecha_inicio=HOY, dias=5)


def test_corregir_vencimiento_solo_admin_con_motivo(cas, servicios, recepcion, admin, catalogo,
                                                     fabrica):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id, dias=30)
    with pytest.raises(ErrorPermiso):
        cas.corregir_vencimiento(recepcion, r.asignacion_id, HOY, "Pago anulado")
    with pytest.raises(ErrorValidacion, match="motivo"):
        cas.corregir_vencimiento(admin, r.asignacion_id, HOY, "")
    cas.corregir_vencimiento(admin, r.asignacion_id, HOY, "Pago anulado")
    assert cas.de_cliente(admin, c.id).vence == HOY
    assert auditorias(fabrica, "casillero_vencimiento_corregido")[0]["motivo"] == "Pago anulado"


def test_cambiar_de_casillero_conserva_lo_pagado(cas, servicios, recepcion, admin, catalogo,
                                                 fabrica):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id, dias=30)
    nuevo = cas.cambiar(recepcion, r.asignacion_id, catalogo["M-1"])
    assert nuevo.numero == "M-1" and nuevo.vence == r.vence
    with fabrica() as s:
        viejo = s.get(CasilleroAsignacion, r.asignacion_id)
        assert viejo.fecha_liberacion is not None
        assert viejo.motivo_liberacion == "Cambio al casillero M-1"
        assert s.get(Casillero, catalogo["004"]).estado == "disponible"
    with pytest.raises(ErrorValidacion, match="zona hombres"):
        cas.cambiar(admin, nuevo.asignacion_id, catalogo["001"])
    historial = servicios.clientes.obtener_ficha(admin, c.id).historial_casilleros
    assert [h.numero for h in historial] == ["M-1", "004"]


def test_liberar_deja_historial_y_casillero_disponible(cas, servicios, recepcion, admin,
                                                       catalogo, fabrica):
    c = cliente(servicios, admin)
    r = cas.asignar(admin, catalogo["004"], c.id)
    with pytest.raises(ErrorValidacion, match="motivo"):
        cas.liberar(recepcion, r.asignacion_id, " ")
    cas.liberar(recepcion, r.asignacion_id, "El cliente ya no lo quiere usar")
    assert cas.de_cliente(admin, c.id) is None
    with pytest.raises(ErrorValidacion, match="ya fue liberado"):
        cas.liberar(recepcion, r.asignacion_id, "Otra vez")
    historial = cas.historial(admin, catalogo["004"])
    assert len(historial) == 1 and historial[0].liberado_por == "rita"
    assert historial[0].motivo == "El cliente ya no lo quiere usar"
    with fabrica() as s:
        assert s.get(Casillero, catalogo["004"]).estado == "disponible"
        assert s.scalar(select(CasilleroAsignacion)) is not None  # no se borra
    assert auditorias(fabrica, "casillero_liberado")[0]["casillero"] == "004"
    # Se puede volver a asignar a otro cliente.
    otra = cliente(servicios, admin, 2)
    cas.asignar(recepcion, catalogo["004"], otra.id)


def test_sin_sesion_no_se_puede(cas, catalogo):
    with pytest.raises(ErrorPermiso):
        cas.listar(None)
    with pytest.raises(ErrorPermiso):
        cas.asignar(None, catalogo["004"], 1)


# --- listas y sugerencias ---------------------------------------------------------------

@pytest.fixture
def ocupados(cas, servicios, admin, catalogo, reloj):
    """Laura (F) con casillero vencido hace 20 días, Pedro (M) al día, Sofía (F) por vencer."""
    laura = cliente(servicios, admin, 1, sexo="F", nombres="Laura")
    pedro = cliente(servicios, admin, 2, sexo="M", nombres="Pedro")
    sofia = cliente(servicios, admin, 3, sexo="F", nombres="Sofía")
    cas.asignar(admin, catalogo["004"], laura.id, fecha_inicio=HOY - timedelta(days=49), dias=30)
    cas.asignar(admin, catalogo["001"], pedro.id, dias=30)
    cas.asignar(admin, catalogo["M-1"], sofia.id, dias=3)
    return laura, pedro, sofia


def test_listas_por_estado_zona_y_sexo(cas, recepcion, catalogo, ocupados):
    todos = cas.listar(recepcion)
    assert [f.numero for f in todos] == ["001", "002", "003", "004", "005", "006", "M-1"]
    assert {f.numero for f in cas.listar(recepcion, FiltrosCasilleros(estado="ocupado"))} == \
        {"001", "004", "M-1"}
    assert len(cas.listar(recepcion, FiltrosCasilleros(estado="disponible"))) == 4
    assert {f.numero for f in cas.listar(recepcion, FiltrosCasilleros(zona="mujeres"))} == \
        {"004", "005", "006"}
    assert {f.numero for f in cas.listar(recepcion, FiltrosCasilleros(sexo_cliente="F"))} == \
        {"004", "M-1"}
    fila = cas.listar(recepcion, FiltrosCasilleros(texto="4"))[0]
    assert fila.numero == "004" and fila.cliente.startswith("Laura") and fila.telefono
    assert cas.listar(recepcion, FiltrosCasilleros(texto="pedro"))[0].numero == "001"


def test_lista_de_vencidos_y_sugerencias(cas, servicios, recepcion, admin, ocupados):
    laura, _, sofia = ocupados
    vencidos = cas.listar(recepcion, FiltrosCasilleros(situacion="vencidos"))
    assert [(f.numero, f.dias_vencido) for f in vencidos] == [("004", 20)]
    assert vencidos[0].sugerir_liberar and vencidos[0].motivo_sugerencia == "Vencido hace 20 días"
    por_vencer = cas.listar(recepcion, FiltrosCasilleros(situacion="por_vencer"))
    assert [f.numero for f in por_vencer] == ["M-1"]
    # Con un límite mayor ya no se sugiere; inactivar al cliente sí lo sugiere.
    servicios.configuracion.guardar(admin, {"casillero_dias_liberar": 30})
    assert cas.listar(recepcion, FiltrosCasilleros(situacion="sugerido_liberar")) == []
    servicios.clientes.inactivar(admin, sofia.id, "Viaje", liberar_casillero=False)
    sugeridos = cas.listar(recepcion, FiltrosCasilleros(situacion="sugerido_liberar"))
    assert [(f.numero, f.motivo_sugerencia) for f in sugeridos] == [("M-1", "Cliente inactivo")]
    r = cas.resumen(recepcion)
    assert (r.total, r.ocupados, r.disponibles, r.vencidos, r.sugeridos) == (7, 3, 4, 1, 1)
    assert r.por_zona["hombres"] == (3, 1)


def test_lista_de_membresia_vencida(cas, servicios, recepcion, admin, ocupados):
    _, pedro, _ = ocupados
    plan = servicios.planes.crear(admin, "Mensual", 30, 100_000)
    servicios.pagos.registrar_membresia(admin, pedro.id, plan.id, fecha_inicio=HOY)
    filas = cas.listar(recepcion, FiltrosCasilleros(situacion="membresia_vencida"))
    assert {f.numero for f in filas} == {"004", "M-1"}  # sin membresía; Pedro está vigente


def test_movimientos_del_dia(cas, servicios, recepcion, admin, catalogo, reloj):
    c = cliente(servicios, admin)
    r = cas.asignar(recepcion, catalogo["004"], c.id)
    reloj.avanzar(hours=3)
    cas.liberar(recepcion, r.asignacion_id, "Casillero vencido")
    movs = cas.movimientos(recepcion, HOY)
    assert [(m.tipo, m.numero, m.usuario) for m in movs] == \
        [("Asignado", "004", "rita"), ("Liberado", "004", "rita")]
    assert movs[1].motivo == "Casillero vencido"
    assert cas.movimientos(recepcion, HOY - timedelta(days=1)) == []


def test_exportar_listas(cas, recepcion, ocupados, tmp_path, fabrica):
    ruta = cas.exportar(recepcion, "estado", tmp_path / "c.xlsx", "xlsx",
                        FiltrosCasilleros(situacion="vencidos"))
    assert ruta.exists()
    ruta = cas.exportar(recepcion, "dia", tmp_path / "d.pdf", "pdf", dia=HOY)
    assert ruta.read_bytes().startswith(b"%PDF")
    assert [a["lista"] for a in auditorias(fabrica, "casilleros_exportados")] == ["estado", "dia"]
    lista = cas.listado(recepcion, "dia", dia=HOY)
    assert "3 asignados" in lista.subtitulo


# --- integración con Recepción y la ficha -------------------------------------------------

def test_recepcion_muestra_vencimiento_y_guarda_instantanea(cas, servicios, recepcion, admin,
                                                           ocupados, fabrica):
    laura, pedro, _ = ocupados
    plan = servicios.planes.crear(admin, "Mensual", 30, 100_000)
    for c in (laura, pedro):
        servicios.pagos.registrar_membresia(admin, c.id, plan.id, fecha_inicio=HOY,
                                            pago=DatosPago(100_000, "efectivo"))
    t = servicios.asistencia.tarjeta(recepcion, pedro.id)
    assert t.color == VERDE and t.casillero == "001"
    assert t.casillero_aviso == "Casillero 001 pagado hasta el 25/12/2026"
    t = servicios.asistencia.tarjeta(recepcion, laura.id)
    assert t.color == AMARILLO and "CASILLERO VENCIDO" in t.titulo and t.permite_ingreso
    assert t.casillero_sugerir_liberar and "sugerido liberar" in t.casillero_aviso
    r = servicios.asistencia.registrar_ingreso(recepcion, laura.codigo)
    with fabrica() as s:
        assert s.get(Asistencia, r.asistencia_id).casillero_numero == "004"


def test_ficha_muestra_casillero_actual_con_vencimiento(cas, servicios, admin, ocupados):
    laura = ocupados[0]
    ficha = servicios.clientes.obtener_ficha(admin, laura.id)
    assert ficha.casillero == "004" and ficha.casillero_actual.vence == date(2026, 11, 6)
    assert ficha.historial_casilleros[0].vence == date(2026, 11, 6)
