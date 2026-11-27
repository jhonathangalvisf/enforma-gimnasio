"""Zonas de los casilleros del gimnasio: mujeres 1-49 y 276-294; hombres 50-110,
251-275 y 307-328; mixtos el resto hasta el 411. Instalación nueva, migración 0010 de
bases existentes, importación del programa anterior y aviso «fuera de su zona»."""

from __future__ import annotations

import json
from datetime import date

import pytest
from alembic import command
from sqlalchemy import select, text

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
from gimnasio.db.migraciones import configuracion_alembic
from gimnasio.modelos import Auditoria, Casillero, CasilleroAsignacion, ahora_utc
from gimnasio.servicios.casilleros import FiltrosCasilleros
from gimnasio.servicios.clientes import DatosCliente
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.zonas_casilleros import TOTAL_CASILLEROS_GIMNASIO, zona_del_gimnasio

MUJERES = set(range(1, 50)) | set(range(276, 295))
HOMBRES = set(range(50, 111)) | set(range(251, 276)) | set(range(307, 329))


def esperado(n: int) -> str:
    return "mujeres" if n in MUJERES else "hombres" if n in HOMBRES else "mixto"


def cliente(servicios, admin, n, sexo):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento=f"7080901{n:03d}", nombres="Persona",
        apellidos=f"Prueba {n}", sexo=sexo, telefonos=[f"31055501{n:02d}"],
        fecha_nacimiento=date(1990, 1, 1)))


def zonas(fabrica) -> dict[str, str]:
    with fabrica() as s:
        return dict(s.execute(select(Casillero.numero, Casillero.zona)).all())


# --- la distribución ------------------------------------------------------------------

@pytest.mark.parametrize("n, zona", [
    (1, "mujeres"), (49, "mujeres"), (50, "hombres"), (110, "hombres"), (111, "mixto"),
    (250, "mixto"), (251, "hombres"), (275, "hombres"), (276, "mujeres"), (288, "mujeres"),
    (289, "mujeres"), (294, "mujeres"), (295, "mixto"), (306, "mixto"), (307, "hombres"),
    (328, "hombres"), (329, "mixto"), (411, "mixto"),
])
def test_bordes_de_los_rangos(n, zona):
    assert zona_del_gimnasio(n) == zona


def test_cuantos_por_zona():
    conteo = {"mujeres": 0, "hombres": 0, "mixto": 0}
    for n in range(1, TOTAL_CASILLEROS_GIMNASIO + 1):
        conteo[zona_del_gimnasio(n)] += 1
    assert conteo == {"mujeres": 68, "hombres": 108, "mixto": 235}


# --- instalación nueva ----------------------------------------------------------------

def test_instalacion_nueva_crea_los_411(servicios, motor):
    assert servicios.casilleros.crear_catalogo_gimnasio() == 411
    actuales = zonas(crear_fabrica_sesiones(motor))
    assert len(actuales) == 411
    assert all(actuales[f"{n:03d}"] == esperado(n) for n in range(1, 412))
    # Al volver a arrancar no se toca nada.
    assert servicios.casilleros.crear_catalogo_gimnasio() == 0
    with crear_fabrica_sesiones(motor)() as s:
        assert s.scalar(select(Auditoria).where(Auditoria.accion == "casilleros_creados"))


def test_si_ya_hay_casilleros_no_crea(servicios, admin):
    servicios.casilleros.crear(admin, "A-1", "mixto")
    assert servicios.casilleros.crear_catalogo_gimnasio() == 0


# --- al asignar se respeta la zona -----------------------------------------------------

def test_asignar_respeta_la_zona(servicios, admin):
    servicios.casilleros.crear_catalogo_gimnasio()
    hombre = cliente(servicios, admin, 1, "M")
    mujer = cliente(servicios, admin, 2, "F")
    ids = {numero: i for i, numero, _ in servicios.casilleros.libres(admin)}
    with pytest.raises(ErrorValidacion):
        servicios.casilleros.asignar(admin, ids["010"], hombre.id)
    with pytest.raises(ErrorValidacion):
        servicios.casilleros.asignar(admin, ids["060"], mujer.id)
    servicios.casilleros.asignar(admin, ids["060"], hombre.id)
    servicios.casilleros.asignar(admin, ids["200"], mujer.id)
    libres_hombre = {n for _, n, _ in servicios.casilleros.libres(admin, "M")}
    assert "010" not in libres_hombre and "280" not in libres_hombre
    assert "300" in libres_hombre and "320" in libres_hombre


# --- bases existentes: migración 0010 --------------------------------------------------

@pytest.fixture
def url_0009(tmp_path):
    url = f"sqlite:///{(tmp_path / 'existente.db').as_posix()}"
    command.upgrade(configuracion_alembic(url), "0009")
    return url


def test_migracion_corrige_zonas_y_completa(url_0009):
    motor = crear_motor(url_0009)
    with motor.begin() as c:
        # Una base vieja: todo mixto, algunos sin ceros y uno con letras.
        for numero in ("15", "060", "280", "A-1", "500"):
            c.execute(text("INSERT INTO casilleros (numero, zona, estado) "
                           "VALUES (:n, 'mixto', 'disponible')"), {"n": numero})
        c.execute(text("UPDATE casilleros SET estado='mantenimiento' WHERE numero='280'"))
    command.upgrade(configuracion_alembic(url_0009), "head")
    actuales = zonas(crear_fabrica_sesiones(motor))
    assert actuales["15"] == "mujeres"  # se respeta cómo estaba escrito
    assert "015" not in actuales
    assert actuales["060"] == "hombres" and actuales["280"] == "mujeres"
    assert actuales["A-1"] == "mixto" and actuales["500"] == "mixto"  # fuera del mapa
    numeros = [n for n in range(1, 412)]
    assert all((f"{n:03d}" in actuales) or n == 15 for n in numeros)
    assert len(actuales) == 411 + 2
    with motor.connect() as c:
        assert c.scalar(text("SELECT estado FROM casilleros WHERE numero='280'")) \
            == "mantenimiento"
        detalle = json.loads(c.scalar(text(
            "SELECT detalle_json FROM auditoria WHERE accion='casilleros_zonas_gimnasio'")))
    assert detalle == {"zona_corregida": 3, "creados": 408}
    motor.dispose()


def test_migracion_no_toca_base_sin_casilleros(url_0009):
    command.upgrade(configuracion_alembic(url_0009), "head")
    motor = crear_motor(url_0009)
    with motor.connect() as c:
        assert c.scalar(text("SELECT COUNT(*) FROM casilleros")) == 0
    motor.dispose()


# --- quien ya ocupaba un casillero de la otra zona -------------------------------------

def test_ocupado_fuera_de_zona_se_conserva_y_se_marca(servicios, admin, motor):
    servicios.casilleros.crear_catalogo_gimnasio()
    hombre = cliente(servicios, admin, 3, "M")
    fabrica = crear_fabrica_sesiones(motor)
    with fabrica() as s:  # como quedaría tras la migración: un hombre en el 010
        cas = s.scalar(select(Casillero).where(Casillero.numero == "010"))
        s.add(CasilleroAsignacion(casillero_id=cas.id, cliente_id=hombre.id,
                                  fecha_asignacion=ahora_utc(), asignado_por=admin.id))
        cas.estado = "ocupado"
        s.commit()
    filas = servicios.casilleros.listar(admin, FiltrosCasilleros(situacion="fuera_de_zona"))
    assert [f.numero for f in filas] == ["010"]
    assert filas[0].fuera_de_zona and filas[0].cliente_id == hombre.id
    # Los bien ubicados no salen.
    assert not any(f.fuera_de_zona for f in servicios.casilleros.listar(admin)
                   if f.numero != "010")
