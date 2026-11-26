"""Importación del programa anterior (Fase 10): lectura de .DBF, limpieza, modo prueba,
importación real con copia previa, una sola vez, permisos y casos raros.

Los .DBF se generan aquí con datos inventados (nunca datos reales de clientes)."""

from __future__ import annotations

import json
import struct
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from sqlalchemy import func, select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.importacion.dbf import leer_dbf
from gimnasio.importacion.programa_anterior import leer_carpeta, separar_nombre
from gimnasio.modelos import (
    Asistencia, Auditoria, Casillero, CasilleroAsignacion, Cliente, Invitado, Membresia, Pago,
)
from gimnasio.servicios.clientes import DatosCliente, Vigencia
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.importacion import NOMBRE_PLAN
from tests.conftest import nuevo_cliente

HOY = date(2026, 11, 26)
CLAVE_COPIAS = "copias-Enforma-2026"


# --- escritor mínimo de .DBF (solo para las pruebas) --------------------------------
def escribir_dbf(ruta: Path, campos: list[tuple[str, str, int]], filas: list[dict],
                 borrados: tuple[int, ...] = ()) -> Path:
    largo = 1 + sum(c[2] for c in campos)
    cabecera = 32 + 32 * len(campos) + 1
    datos = bytearray(struct.pack("<BBBBIHH", 3, 126, 11, 26, len(filas), cabecera, largo))
    datos += bytes(20)
    for nombre, tipo, ancho in campos:
        bloque = nombre.encode("ascii").ljust(11, b"\0") + tipo.encode("ascii") + bytes(4)
        bloque += bytes([ancho, 0]) + bytes(14)
        datos += bloque
    datos += b"\r"
    for i, fila in enumerate(filas):
        datos += b"*" if i in borrados else b" "
        for nombre, tipo, ancho in campos:
            valor = str(fila.get(nombre, ""))
            crudo = valor.encode("cp850")[:ancho]
            datos += crudo.rjust(ancho) if tipo == "N" else crudo.ljust(ancho)
    datos += b"\x1a"
    ruta.write_bytes(bytes(datos))
    return ruta


CAMPOS_CLIENTES = [
    ("IDCLIE", "N", 4), ("CLIENTE", "C", 32), ("CC", "C", 10), ("SA", "C", 3), ("SEX", "C", 1),
    ("ACT", "L", 1), ("FCHANAC", "D", 8), ("DIRRES", "C", 30), ("TELRES", "C", 15),
    ("ACUDIENTE", "C", 20), ("TELACU", "C", 15), ("FCHAINI", "D", 8), ("FCHAFIN", "D", 8),
    ("FUMA", "L", 1),
]


@pytest.fixture
def db3(tmp_path) -> Path:
    carpeta = tmp_path / "ENFORMA PROGRAMA" / "DB3"
    carpeta.mkdir(parents=True)
    escribir_dbf(carpeta / "ENCLIE.DBF", CAMPOS_CLIENTES, [
        dict(IDCLIE=1, CLIENTE="PEREZ GOMEZ*ANA MARIA", CC="1053000001", SEX="M", ACT="T",
             FCHANAC="19900515", DIRRES="CALLE 1 # 2-3", TELRES="312 555 0001",
             ACUDIENTE="LUIS PEREZ", TELACU="3125550002", FCHAINI="20261116",
             FCHAFIN="20261215", FUMA="T"),
        dict(IDCLIE=2, CLIENTE="LOPEZ*JUAN", CC="1053000001", SEX="H", ACT="F",
             FCHAINI="20200101", FCHAFIN="20200130"),
        dict(IDCLIE=3, CLIENTE="SINSEPARADOR CARLOS", CC="", SEX="H", ACT="T",
             FCHAINI="30240101", FCHAFIN="30240131"),
        dict(IDCLIE=245, CLIENTE="RUIZ*MARTA", CC="10'289.575", SEX="M", ACT="T",
             FCHANAC="18000101", FCHAINI="20261021", FCHAFIN="20261120"),
        dict(IDCLIE=3, CLIENTE="REPETIDO*CODIGO", CC="99999999", SEX="H", ACT="T"),
        dict(IDCLIE=7, CLIENTE="BORRADO*REGISTRO", CC="77777777", SEX="H", ACT="T"),
    ], borrados=(5,))
    escribir_dbf(carpeta / "ENPAGO.DBF", [
        ("IDCLIE", "N", 4), ("SERV", "C", 20), ("FCHAPAGO", "D", 8), ("FCHAINI", "D", 8),
        ("FCHAFIN", "D", 8), ("PAGO", "N", 6),
    ], [
        dict(IDCLIE=3, SERV="MENSUALIDAD", FCHAPAGO="20261102", FCHAINI="20261102",
             FCHAFIN="20261201", PAGO=1000),
        dict(IDCLIE=1, SERV="CASILLERO", FCHAPAGO="20261102", FCHAINI="20261102",
             FCHAFIN="20270101", PAGO=1000),
    ])
    escribir_dbf(carpeta / "ENASIS.DBF", [("IDCLIE", "N", 4), ("FCHASIS", "D", 8),
                                          ("HORA", "C", 1)], [
        dict(IDCLIE=1, FCHASIS="20261120", HORA="M"),
        dict(IDCLIE=1, FCHASIS="20261121", HORA="N"),
        dict(IDCLIE=999, FCHASIS="20261120", HORA="T"),
        dict(IDCLIE=245, FCHASIS="70261010", HORA="T"),
    ])
    escribir_dbf(carpeta / "ENCASI.DBF", [
        ("NUMCAS", "N", 4), ("SEX", "C", 1), ("IDCLIE", "N", 4), ("FCHAINI", "D", 8),
        ("FCHAFIN", "D", 8), ("DISP", "L", 1),
    ], [
        dict(NUMCAS=1, SEX="H", IDCLIE=3, FCHAINI="20261101", FCHAFIN="20261201", DISP="F"),
        dict(NUMCAS=2, SEX="M", IDCLIE=1, FCHAINI="20261110", FCHAFIN="20261210", DISP="F"),
        dict(NUMCAS=3, SEX="", IDCLIE=0, DISP="T"),
        dict(NUMCAS=4, SEX="M", IDCLIE=1, FCHAINI="20261110", FCHAFIN="20261210", DISP="F"),
    ])
    escribir_dbf(carpeta / "ENHUES.DBF", [
        ("IDHUES", "N", 10), ("HUESPED", "C", 30), ("CLASE", "C", 1), ("VISITAS", "N", 2),
        ("FCHA1AVIS", "D", 8), ("FCHAULVIS", "D", 8),
    ], [
        dict(IDHUES=1020304, HUESPED="DIAZ*PEDRO", CLASE="P", VISITAS=5,
             FCHA1AVIS="20250101", FCHAULVIS="20261101"),
        dict(IDHUES=1, HUESPED="X", CLASE="P", VISITAS=1),
        dict(IDHUES=5556667, HUESPED="ROJAS*LUZ", CLASE="P", VISITAS=1,
             FCHA1AVIS="20261110", FCHAULVIS="20261110"),
    ])
    return carpeta


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def contar(fabrica, modelo) -> int:
    with fabrica() as s:
        return s.scalar(select(func.count()).select_from(modelo))


def con_copias(servicios, admin):
    servicios.backups.configurar_clave(admin, CLAVE_COPIAS, CLAVE_COPIAS)
    return servicios


# --- lectura y limpieza ------------------------------------------------------------
def test_lector_dbf_salta_borrados_y_limpia(db3):
    tabla = leer_dbf(db3 / "ENCLIE.DBF")
    assert tabla.borrados == 1 and len(tabla.registros) == 5
    assert tabla.registros[0]["CLIENTE"] == "PEREZ GOMEZ*ANA MARIA"
    assert tabla.registros[0]["IDCLIE"] == "1"


def test_separar_nombre():
    assert separar_nombre("PEREZ GOMEZ*ANA MARIA") == ("Ana Maria", "Perez Gomez", True)
    assert separar_nombre("SINSEPARADOR CARLOS") == ("Carlos", "Sinseparador", False)
    assert separar_nombre("SOLO") == ("Solo", "Sin Apellido", False)


def test_leer_carpeta_limpia_los_datos(db3):
    datos = leer_carpeta(db3, HOY)
    clientes = {c.codigo: c for c in datos.clientes}
    assert set(clientes) == {"000001", "000002", "000003", "000245"}
    ana = clientes["000001"]
    assert (ana.nombres, ana.apellidos, ana.sexo) == ("Ana Maria", "Perez Gomez", "F")
    assert ana.documento == "1053000001" and ana.telefono == "3125550001"
    assert (ana.emergencia_nombre, ana.emergencia_telefono) == ("Luis Perez", "3125550002")
    assert ana.fecha_fin == date(2026, 12, 15)
    # Documento repetido: se lo queda el activo; el otro queda «Sin documento».
    assert (clientes["000002"].tipo_documento, clientes["000002"].documento) == ("SD", "SD000002")
    assert clientes["000002"].sexo == "M" and not clientes["000002"].activo
    # Fecha de fin con año mal digitado: se toma la del pago de mensualidad.
    assert clientes["000003"].fecha_fin == date(2026, 12, 1)
    assert clientes["000003"].tipo_documento == "SD"
    marta = clientes["000245"]
    assert marta.documento == "10289575" and marta.fecha_nacimiento is None
    descripciones = " | ".join(p.descripcion for p in datos.problemas)
    assert "Código repetido" in descripciones
    assert "repetido con el código 000001" in descripciones
    assert "Fecha de asistencia inválida" in descripciones
    assert "cliente que no existe" in descripciones
    assert len(datos.asistencias) == 2
    assert [a.hora for a in datos.asistencias] == [7, 19]
    casilleros = {c.numero: c for c in datos.casilleros}
    assert casilleros["001"].zona == "hombres" and casilleros["001"].codigo_cliente == "000003"
    assert casilleros["003"].zona == "mixto" and casilleros["003"].codigo_cliente is None
    assert casilleros["004"].codigo_cliente is None  # el cliente ya tenía el 002
    assert [i.documento for i in datos.invitados] == ["1020304", "5556667"]


def test_carpeta_sin_clientes(servicios, admin, tmp_path):
    vacia = tmp_path / "vacia"
    vacia.mkdir()
    with pytest.raises(ErrorValidacion, match="ENCLIE.DBF"):
        servicios.importacion.importar(admin, vacia)


# --- modo prueba --------------------------------------------------------------------
def test_modo_prueba_no_guarda_nada_ni_toca_el_origen(servicios, admin, fabrica, db3, tmp_path):
    antes = {p.name: p.read_bytes() for p in db3.iterdir()}
    r = servicios.importacion.importar(admin, db3)
    assert not r.guardado
    assert (r.clientes, r.membresias, r.asistencias) == (4, 4, 2)
    assert (r.casilleros_creados, r.casilleros_ocupados, r.invitados) == (4, 2, 2)
    assert r.vigentes == 2 and r.sin_documento == 2
    for modelo in (Cliente, Membresia, Asistencia, Casillero, Invitado):
        assert contar(fabrica, modelo) == 0
    assert {p.name: p.read_bytes() for p in db3.iterdir()} == antes
    # Se leyó una copia, guardada en la carpeta de datos.
    copia = r.ruta_informe.parent / "origen" / "ENCLIE.DBF"
    assert copia.read_bytes() == antes["ENCLIE.DBF"]
    libro = load_workbook(r.ruta_informe)
    assert libro.sheetnames == ["Resumen", "Problemas"]
    assert libro["Problemas"].max_row == len(r.problemas) + 1
    assert servicios.importacion.ya_importado(admin) is None


# --- importación real -------------------------------------------------------------
def test_importar_de_verdad(servicios, admin, fabrica, db3):
    con_copias(servicios, admin)
    r = servicios.importacion.importar(admin, db3, guardar=True)
    assert r.guardado and r.ruta_backup and r.ruta_backup.exists()
    assert r.ruta_informe.name == "informe_importacion.xlsx"
    assert contar(fabrica, Cliente) == 4
    assert contar(fabrica, Pago) == 0  # los valores viejos no entran a la caja

    ana = servicios.clientes.buscar_rapido(admin, "000001")[0]
    ficha = servicios.clientes.obtener_ficha(admin, ana.id)
    assert ficha.vigencia == Vigencia.VIGENTE and ficha.fecha_fin == date(2026, 12, 15)
    assert ficha.plan_actual == NOMBRE_PLAN and ficha.saldo_pendiente == 0
    assert ficha.telefonos == ["3125550001"] and ficha.casillero == "002"
    assert len(ficha.asistencias) == 2
    marta = servicios.clientes.obtener_ficha(
        admin, servicios.clientes.buscar_rapido(admin, "000245")[0].id)
    assert marta.vigencia == Vigencia.VENCIDA
    juan = servicios.clientes.obtener_ficha(
        admin, servicios.clientes.buscar_rapido(admin, "000002")[0].id)
    assert juan.estado == "inactivo" and juan.tipo_documento == "SD"

    with fabrica() as s:
        asignaciones = s.scalars(select(CasilleroAsignacion)).all()
        assert len(asignaciones) == 2
        assert {a.fecha_vencimiento for a in asignaciones} == {date(2026, 12, 1),
                                                                date(2026, 12, 10)}
        estados = dict(s.execute(select(Casillero.numero, Casillero.estado)).all())
        assert estados == {"001": "ocupado", "002": "ocupado", "003": "disponible",
                           "004": "disponible"}
        detalle = json.loads(s.scalar(select(Auditoria.detalle_json).where(
            Auditoria.accion == "importacion_programa_anterior")))
        assert detalle["clientes"] == 4 and "copia_seguridad" in detalle

    pedro = servicios.invitados.por_documento(admin, "1020304")
    assert pedro.total_visitas == 5 and pedro.visitas_anteriores == 3
    assert len(pedro.visitas) == 2 and pedro.visitas_mes == 1  # la del 01/11/2026
    assert "del programa anterior" in pedro.texto_contador

    # Los clientes nuevos siguen después del código más alto.
    assert servicios.clientes.codigo_sugerido(admin) == "000246"
    assert servicios.importacion.ya_importado(admin) is not None
    with pytest.raises(ErrorValidacion, match="ya se importaron"):
        servicios.importacion.importar(admin, db3, guardar=True)
    # La prueba sí se puede repetir, y avisa que todo ya existe.
    r2 = servicios.importacion.importar(admin, db3)
    assert r2.clientes == 0 and any("ya existe" in p.descripcion for p in r2.problemas)


def test_sin_copia_de_seguridad_no_importa(servicios, admin, fabrica, db3):
    with pytest.raises(ErrorValidacion, match="copia de seguridad"):
        servicios.importacion.importar(admin, db3, guardar=True)
    assert contar(fabrica, Cliente) == 0
    assert servicios.importacion.ya_importado(admin) is None


def test_recepcion_no_puede_importar(servicios, recepcion, db3):
    with pytest.raises(ErrorPermiso):
        servicios.importacion.importar(recepcion, db3)


def test_no_pisa_clientes_ni_casilleros_existentes(servicios, admin, fabrica, sesion, db3):
    nuevo_cliente(sesion, 1, documento="1053000001")
    sesion.add(Casillero(numero="2", zona="mujeres"))
    sesion.commit()
    con_copias(servicios, admin)
    r = servicios.importacion.importar(admin, db3, guardar=True)
    assert r.clientes == 3
    assert any("ya existe en el sistema nuevo" in p.descripcion for p in r.problemas)
    with fabrica() as s:
        # El casillero «2» que ya existía se reutiliza (no se crea «002»).
        assert s.scalar(select(func.count()).where(Casillero.numero == "002")) == 0
        # El cliente 1 no se importó, así que su casillero queda libre.
        assert s.scalar(select(func.count()).select_from(CasilleroAsignacion)) == 1


# --- clientes «Sin documento» ------------------------------------------------------
def test_sin_documento_se_puede_editar_y_no_inscribir(servicios, admin, recepcion, db3):
    con_copias(servicios, admin)
    servicios.importacion.importar(admin, db3, guardar=True)
    juan = servicios.clientes.obtener_ficha(
        admin, servicios.clientes.buscar_rapido(admin, "000002")[0].id)
    datos = juan.a_datos()
    datos.telefonos = ["3001234567"]
    assert servicios.clientes.modificar(recepcion, juan.id, datos) == ["telefonos"]
    datos.tipo_documento, datos.documento = "CC", "1053999999"
    assert "documento" in servicios.clientes.modificar(admin, juan.id, datos)
    with pytest.raises(ErrorValidacion):
        servicios.clientes.registrar(admin, DatosCliente(
            tipo_documento="SD", documento="SD000999", nombres="Nuevo", apellidos="Cliente",
            sexo="M"))
