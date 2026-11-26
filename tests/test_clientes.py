"""Pruebas del servicio de clientes (sección 3.2)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import (
    Asistencia, Auditoria, Casillero, CasilleroAsignacion, Cliente, Contacto, Membresia, Plan,
)
from gimnasio.servicios.clientes import (
    ContactoEmergencia, DatosCliente, ErrorCasilleroAsignado, FiltrosClientes, Vigencia,
    calcular_vigencia,
)
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion

HOY = date(2026, 11, 26)  # el reloj de prueba está en 26/11/2026 10:00 en Bogotá


def datos(**cambios) -> DatosCliente:
    base = dict(
        tipo_documento="CC", documento="1020304050", nombres="María José",
        apellidos="Gómez Pérez", sexo="F", fecha_nacimiento=date(1995, 11, 26),
        direccion="Calle 1 # 2-3", telefonos=["300 123 4567", "6041234567"],
        correos=["Maria@Example.com"],
        emergencias=[ContactoEmergencia("Pedro Gómez", "3109876543")], autoriza_datos=True,
    )
    base.update(cambios)
    return DatosCliente(**base)


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


def membresia(fabrica, cliente_id, inicio, fin, estado="activa", plan="Mensual"):
    with fabrica() as s:
        p = s.scalar(select(Plan).where(Plan.nombre == plan))
        if p is None:
            p = Plan(nombre=plan, duracion_dias=30, precio=120_000)
            s.add(p)
            s.flush()
        s.add(Membresia(cliente_id=cliente_id, plan_id=p.id, fecha_inicio=inicio,
                        fecha_fin=fin, precio_pactado=120_000, estado=estado,
                        motivo_anulacion="Prueba" if estado == "anulada" else None))
        s.commit()
        return p.id


# --- vigencia ---------------------------------------------------------------------

@pytest.mark.parametrize("fin, esperado, dias", [
    (None, Vigencia.SIN_MEMBRESIA, None),
    (HOY - timedelta(days=1), Vigencia.VENCIDA, -1),
    (HOY, Vigencia.POR_VENCER, 0),  # el día de fecha_fin todavía puede entrar
    (HOY + timedelta(days=5), Vigencia.POR_VENCER, 5),
    (HOY + timedelta(days=6), Vigencia.VIGENTE, 6),
])
def test_calcular_vigencia(fin, esperado, dias):
    assert calcular_vigencia(fin, HOY, 5) == (esperado, dias)


def test_vigencia_usa_ultima_membresia_no_anulada(clientes, admin, fabrica):
    c = clientes.registrar(admin, datos())
    assert c.vigencia == Vigencia.SIN_MEMBRESIA
    membresia(fabrica, c.id, HOY - timedelta(days=40), HOY - timedelta(days=11))
    assert clientes.obtener_ficha(admin, c.id).vigencia == Vigencia.VENCIDA
    membresia(fabrica, c.id, HOY - timedelta(days=10), HOY + timedelta(days=19), estado="anulada")
    assert clientes.obtener_ficha(admin, c.id).vigencia == Vigencia.VENCIDA
    membresia(fabrica, c.id, HOY - timedelta(days=10), HOY + timedelta(days=3))
    ficha = clientes.obtener_ficha(admin, c.id)
    assert (ficha.vigencia, ficha.dias_restantes, ficha.plan_actual) == (
        Vigencia.POR_VENCER, 3, "Mensual")


def test_vigencia_no_se_guarda_en_la_base(motor):
    with motor.connect() as con:
        columnas = {f[1] for f in con.execute(text("PRAGMA table_info(clientes)"))}
    assert not any("vigencia" in c or "vence" in c for c in columnas)


# --- registro ------------------------------------------------------------------------

def test_registrar_genera_codigo_y_normaliza(clientes, recepcion, fabrica):
    ficha = clientes.registrar(recepcion, datos())
    assert ficha.codigo == "000001" and len(ficha.qr_token) >= 16
    assert ficha.telefonos == ["3001234567", "6041234567"]
    assert ficha.correos == ["maria@example.com"]
    assert ficha.emergencias == [ContactoEmergencia("Pedro Gómez", "3109876543")]
    assert ficha.autoriza_datos_en is not None and ficha.activo
    assert ficha.cumple_hoy
    segundo = clientes.registrar(recepcion, datos(documento="99887766"))
    assert segundo.codigo == "000002"
    with fabrica() as s:
        principal = s.scalar(select(Contacto).where(
            Contacto.cliente_id == ficha.id, Contacto.tipo == "telefono",
            Contacto.principal.is_(True)))
        assert principal.valor == "3001234567"
    detalle = auditorias(fabrica, "cliente_registrado")[0]
    assert detalle == {"codigo": "000001"}  # sin copiar datos personales


def test_codigo_sigue_al_mayor_existente(clientes, admin, sesion):
    from tests.conftest import nuevo_cliente

    nuevo_cliente(sesion, 41)
    sesion.commit()
    assert clientes.registrar(admin, datos()).codigo == "000042"


def test_documento_unico(clientes, admin):
    clientes.registrar(admin, datos())
    with pytest.raises(ErrorValidacion, match="Ya existe un cliente con el documento.*000001"):
        clientes.registrar(admin, datos(documento="1.020.304.050", nombres="Otra"))


@pytest.mark.parametrize("cambios, mensaje", [
    (dict(tipo_documento="XX"), "tipo de documento"),
    (dict(documento="12AB"), "solo números"),
    (dict(tipo_documento="PAS", documento="A!"), "letras o números"),
    (dict(nombres=" "), "nombres"),
    (dict(apellidos=""), "apellidos"),
    (dict(sexo="X"), "sexo"),
    (dict(fecha_nacimiento=HOY + timedelta(days=1)), "futura"),
    (dict(telefonos=["12"]), "entre 7 y 15"),
    (dict(telefonos=["300-abc"]), "solo puede tener números"),
    (dict(correos=["no-es-correo"]), "no es válido"),
    (dict(emergencias=[ContactoEmergencia("Sin teléfono", "")]), "teléfono del contacto"),
])
def test_validaciones(clientes, admin, cambios, mensaje):
    with pytest.raises(ErrorValidacion, match=mensaje):
        clientes.registrar(admin, datos(**cambios))


def test_pasaporte_alfanumerico(clientes, admin):
    ficha = clientes.registrar(admin, datos(tipo_documento="PAS", documento="ab-12345"))
    assert ficha.documento == "AB12345"


def test_codigo_no_editable_ni_borrable(clientes, admin):
    """No hay métodos para cambiar el código ni para borrar clientes."""
    nombres = {n for n in dir(clientes) if not n.startswith("_")}
    assert not any(p in n for n in nombres for p in ("borrar", "eliminar", "codigo"))
    ficha = clientes.registrar(admin, datos())
    clientes.modificar(admin, ficha.id, datos(nombres="Otra"))
    assert clientes.obtener_ficha(admin, ficha.id).codigo == "000001"


# --- modificación y permisos --------------------------------------------------------

def test_admin_modifica_todo_con_auditoria_por_campo(clientes, admin, fabrica):
    ficha = clientes.registrar(admin, datos())
    cambios = clientes.modificar(admin, ficha.id, datos(
        nombres="María", fecha_nacimiento=date(1995, 1, 2), telefonos=["3001234567"]))
    assert set(cambios) == {"nombres", "fecha_nacimiento", "telefonos"}
    detalle = auditorias(fabrica, "cliente_modificado")[-1]
    assert detalle["nombres"] == {"antes": "María José", "despues": "María"}
    assert detalle["fecha_nacimiento"] == {"antes": "26/11/1995", "despues": "02/01/1995"}
    assert detalle["telefonos"]["despues"] == "3001234567"
    assert "documento" not in detalle  # solo lo que cambió
    assert clientes.modificar(admin, ficha.id, datos(
        nombres="María", fecha_nacimiento=date(1995, 1, 2), telefonos=["3001234567"])) == []


def test_recepcion_solo_modifica_contacto(clientes, recepcion):
    ficha = clientes.registrar(recepcion, datos())
    cambios = clientes.modificar(recepcion, ficha.id, datos(
        direccion="Carrera 9", telefonos=["3112223344"], correos=[],
        emergencias=[ContactoEmergencia("Luisa", "3001112233")]))
    assert set(cambios) == {"direccion", "telefonos", "correos", "emergencias"}
    for prohibido in (dict(nombres="Otra"), dict(documento="555666777"), dict(sexo="M"),
                      dict(fecha_nacimiento=None), dict(notas="algo"),
                      dict(autoriza_datos=False)):
        actuales = clientes.obtener_ficha(recepcion, ficha.id).a_datos()
        for k, v in prohibido.items():
            setattr(actuales, k, v)
        with pytest.raises(ErrorPermiso, match="Recepción solo puede"):
            clientes.modificar(recepcion, ficha.id, actuales)
    assert clientes.obtener_ficha(recepcion, ficha.id).nombres == "María José"


def test_cambio_de_documento_valida_unicidad(clientes, admin):
    a = clientes.registrar(admin, datos())
    clientes.registrar(admin, datos(documento="777888999"))
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        clientes.modificar(admin, a.id, datos(documento="777888999"))


# --- activar / inactivar ------------------------------------------------------------

def test_solo_admin_inactiva(clientes, admin, recepcion, fabrica):
    ficha = clientes.registrar(admin, datos())
    with pytest.raises(ErrorPermiso):
        clientes.inactivar(recepcion, ficha.id, "No paga")
    with pytest.raises(ErrorPermiso):
        clientes.activar(recepcion, ficha.id)
    with pytest.raises(ErrorValidacion, match="motivo"):
        clientes.inactivar(admin, ficha.id, "")
    clientes.inactivar(admin, ficha.id, "Se retiró")
    assert clientes.obtener_ficha(admin, ficha.id).estado == "inactivo"
    assert auditorias(fabrica, "cliente_inactivado")[0]["motivo"] == "Se retiró"
    clientes.activar(admin, ficha.id)
    assert clientes.obtener_ficha(admin, ficha.id).activo
    assert len(auditorias(fabrica, "cliente_activado")) == 1


def _asignar_casillero(fabrica, cliente_id, numero="007"):
    with fabrica() as s:
        cas = Casillero(numero=numero, zona="mixto", estado="ocupado")
        s.add(cas)
        s.flush()
        s.add(CasilleroAsignacion(casillero_id=cas.id, cliente_id=cliente_id,
                                  fecha_asignacion=datetime(2026, 10, 1, tzinfo=timezone.utc)))
        s.commit()
        return cas.id


def test_inactivar_con_casillero_pide_decidir_y_libera(clientes, admin, fabrica):
    ficha = clientes.registrar(admin, datos())
    cas_id = _asignar_casillero(fabrica, ficha.id)
    assert clientes.casillero_activo(admin, ficha.id) == "007"
    with pytest.raises(ErrorCasilleroAsignado) as error:
        clientes.inactivar(admin, ficha.id, "Se retiró")
    assert error.value.numero == "007"
    assert clientes.obtener_ficha(admin, ficha.id).activo  # no cambió nada
    clientes.inactivar(admin, ficha.id, "Se retiró", liberar_casillero=True)
    with fabrica() as s:
        asignacion = s.scalar(select(CasilleroAsignacion))
        assert asignacion.fecha_liberacion is not None
        assert asignacion.liberado_por == admin.id
        assert "Se retiró" in asignacion.motivo_liberacion
        assert s.get(Casillero, cas_id).estado == "disponible"
    assert auditorias(fabrica, "casillero_liberado")[0]["casillero"] == "007"
    ficha = clientes.obtener_ficha(admin, ficha.id)
    assert ficha.casillero is None and len(ficha.historial_casilleros) == 1


def test_inactivar_conservando_casillero(clientes, admin, fabrica):
    ficha = clientes.registrar(admin, datos())
    _asignar_casillero(fabrica, ficha.id)
    clientes.inactivar(admin, ficha.id, "Viaje largo", liberar_casillero=False)
    assert clientes.obtener_ficha(admin, ficha.id).casillero == "007"
    assert auditorias(fabrica, "cliente_inactivado")[0]["casillero_conservado"] == "007"


# --- foto ------------------------------------------------------------------------------

def test_foto_se_copia_y_se_quita(clientes, recepcion, tmp_path):
    ficha = clientes.registrar(recepcion, datos())
    origen = tmp_path / "foto.JPG"
    origen.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
    destino = clientes.cambiar_foto(recepcion, ficha.id, origen)
    assert destino == tmp_path / "fotos" / "000001.jpg" and destino.exists()
    assert clientes.obtener_ficha(recepcion, ficha.id).foto == destino
    with pytest.raises(ErrorValidacion, match="PNG o JPG"):
        clientes.cambiar_foto(recepcion, ficha.id, tmp_path / "foto.gif")
    clientes.cambiar_foto(recepcion, ficha.id, None)
    assert not destino.exists() and clientes.obtener_ficha(recepcion, ficha.id).foto is None


# --- búsqueda y filtros -------------------------------------------------------------

@pytest.fixture
def varios(clientes, admin, fabrica):
    """Cinco clientes con vigencias, sexos, planes y asistencias distintas."""
    a = clientes.registrar(admin, datos())  # María José Gómez Pérez, F, cumple en noviembre
    b = clientes.registrar(admin, datos(
        documento="80123456", nombres="José", apellidos="Martínez", sexo="M",
        fecha_nacimiento=date(1988, 3, 4), telefonos=["3157778899"],
        correos=["jose.m@correo.co"], emergencias=[]))
    c = clientes.registrar(admin, datos(
        documento="52987654", nombres="Ana", apellidos="Rodríguez", sexo="F",
        fecha_nacimiento=None, telefonos=[], correos=[], emergencias=[]))
    d = clientes.registrar(admin, datos(
        documento="1001001001", nombres="Luis", apellidos="Zapata", sexo="M",
        fecha_nacimiento=date(2000, 11, 3), telefonos=["3201112233"], correos=[],
        emergencias=[]))
    e = clientes.registrar(admin, datos(
        documento="AB778899", tipo_documento="PAS", nombres="John", apellidos="Smith",
        sexo="O", fecha_nacimiento=date(1979, 6, 1), telefonos=["+14155550123"], correos=[], emergencias=[]))
    mensual = membresia(fabrica, a.id, HOY - timedelta(days=10), HOY + timedelta(days=19))
    membresia(fabrica, b.id, HOY - timedelta(days=27), HOY + timedelta(days=2))
    membresia(fabrica, c.id, HOY - timedelta(days=60), HOY - timedelta(days=31))
    trimestral = membresia(fabrica, d.id, HOY, HOY + timedelta(days=89), plan="Trimestral")
    with fabrica() as s:
        s.add(Asistencia(cliente_id=a.id, fecha=HOY - timedelta(days=1), resultado="permitido",
                         usuario_id=admin.id,
                         fecha_hora=datetime(2026, 11, 25, 12, tzinfo=timezone.utc)))
        s.add(Asistencia(cliente_id=b.id, fecha=HOY - timedelta(days=2), resultado="permitido",
                         usuario_id=admin.id, eliminada=True, motivo_eliminacion="error",
                         fecha_hora=datetime(2026, 11, 24, 12, tzinfo=timezone.utc)))
        s.commit()
    clientes.inactivar(admin, d.id, "Lesión")
    return dict(a=a, b=b, c=c, d=d, e=e, mensual=mensual, trimestral=trimestral)


def codigos(pagina):
    return sorted(f.codigo for f in pagina.filas)


@pytest.mark.parametrize("texto, esperados", [
    ("1", ["000001"]),            # código sin ceros a la izquierda
    ("000002", ["000002"]),
    ("8012", ["000002"]),         # documento por prefijo
    ("315 777", ["000002"]),      # teléfono por prefijo, con espacios
    ("310987", ["000001"]),       # teléfono del contacto de emergencia
    ("jose", ["000001", "000002"]),  # sin tildes ni mayúsculas
    ("MARÍA gómez", ["000001"]),  # varias palabras, en nombres y apellidos
    ("rodri", ["000003"]),
    ("@correo.co", ["000002"]),
    ("ab778899", ["000005"]),     # pasaporte exacto
    ("+1415", ["000005"]),
    ("nadie", []),
    ("50%", []),                  # comodines escapados
])
def test_busqueda_por_texto(clientes, admin, varios, texto, esperados):
    assert codigos(clientes.buscar(admin, FiltrosClientes(texto=texto))) == esperados


@pytest.mark.parametrize("filtro, esperados", [
    (dict(estado="inactivo"), ["000004"]),
    (dict(estado="activo"), ["000001", "000002", "000003", "000005"]),
    (dict(vigencia=Vigencia.VIGENTE), ["000001", "000004"]),
    (dict(vigencia=Vigencia.POR_VENCER), ["000002"]),
    (dict(vigencia=Vigencia.VENCIDA), ["000003"]),
    (dict(vigencia=Vigencia.SIN_MEMBRESIA), ["000005"]),
    (dict(sexo="M"), ["000002", "000004"]),
    (dict(cumple_mes=11), ["000001", "000004"]),
    (dict(sin_asistir_dias=7), ["000002", "000003", "000004", "000005"]),
    (dict(registro_desde=HOY, registro_hasta=HOY), ["000001", "000002", "000003", "000004", "000005"]),
    (dict(registro_desde=HOY + timedelta(days=1)), []),
    (dict(sexo="F", vigencia=Vigencia.VIGENTE), ["000001"]),
])
def test_filtros(clientes, admin, varios, filtro, esperados):
    assert codigos(clientes.buscar(admin, FiltrosClientes(**filtro))) == esperados


def test_filtro_por_plan(clientes, admin, varios):
    assert codigos(clientes.buscar(admin, FiltrosClientes(plan_id=varios["trimestral"]))) == ["000004"]
    assert codigos(clientes.buscar(admin, FiltrosClientes(plan_id=varios["mensual"]))) == [
        "000001", "000002", "000003"]


def test_orden_y_paginas(clientes, admin, varios):
    pagina = clientes.buscar(admin, orden="apellidos")
    assert [f.apellidos for f in pagina.filas][:2] == ["Gómez Pérez", "Martínez"]
    assert pagina.total == 5
    desc = clientes.buscar(admin, orden="codigo", descendente=True, desde=1, limite=2)
    assert [f.codigo for f in desc.filas] == ["000004", "000003"] and desc.total == 5
    vence = clientes.buscar(admin, orden="vence")
    assert vence.filas[0].fecha_fin is None  # sin membresía primero
    fila = next(f for f in vence.filas if f.codigo == "000002")
    assert (fila.plan, fila.vigencia, fila.dias_restantes, fila.telefono) == (
        "Mensual", Vigencia.POR_VENCER, 2, "3157778899")
    for columna in ("nombres", "documento", "telefono", "correo", "plan", "vigencia",
                    "estado", "registro", "sexo"):
        assert clientes.buscar(admin, orden=columna).total == 5
    with pytest.raises(ErrorValidacion):
        clientes.buscar(admin, orden="hash_clave")


def test_busqueda_rapida(clientes, admin, varios):
    assert [f.codigo for f in clientes.buscar_rapido(admin, "4")] == ["000004"]
    assert [f.codigo for f in clientes.buscar_rapido(admin, varios["e"].qr_token)] == ["000005"]
    assert {f.codigo for f in clientes.buscar_rapido(admin, "jose")} == {"000001", "000002"}
    assert clientes.buscar_rapido(admin, "   ") == []


def test_ficha_con_pestanas(clientes, admin, varios):
    ficha = clientes.obtener_ficha(admin, varios["a"].id)
    assert len(ficha.membresias) == 1 and ficha.membresias[0].plan == "Mensual"
    assert len(ficha.asistencias) == 1
    assert ficha.pagos == [] and ficha.alertas == []
    b = clientes.obtener_ficha(admin, varios["b"].id)
    assert b.asistencias == []  # las eliminadas no aparecen


def test_ver_requiere_sesion(clientes):
    with pytest.raises(ErrorPermiso):
        clientes.buscar(None)


# --- exportación ------------------------------------------------------------------------

def test_exportar_excel_y_pdf(clientes, admin, recepcion, varios, tmp_path, fabrica):
    from openpyxl import load_workbook

    with pytest.raises(ErrorPermiso):
        clientes.exportar(recepcion, FiltrosClientes(), tmp_path / "x.xlsx", "xlsx")
    n = clientes.exportar(admin, FiltrosClientes(sexo="M"), tmp_path / "c.xlsx", "xlsx")
    assert n == 2
    hoja = load_workbook(tmp_path / "c.xlsx").active
    assert hoja["A1"].value == "Código" and hoja.max_row == 3
    assert {hoja["A2"].value, hoja["A3"].value} == {"000002", "000004"}
    assert hoja["I2"].number_format == "dd/mm/yyyy"
    n = clientes.exportar(admin, FiltrosClientes(), tmp_path / "c.pdf", "pdf")
    assert n == 5 and (tmp_path / "c.pdf").read_bytes().startswith(b"%PDF")
    assert [d["cantidad"] for d in auditorias(fabrica, "clientes_exportados")] == [2, 5]


def test_documentos_y_codigos_unicos_en_la_base(sesion):
    """Aunque se salte el servicio, la base no acepta códigos ni documentos repetidos."""
    from sqlalchemy.exc import IntegrityError

    from tests.conftest import nuevo_cliente

    nuevo_cliente(sesion, 1)
    sesion.commit()
    with pytest.raises(IntegrityError):
        nuevo_cliente(sesion, 2, documento=sesion.scalar(select(Cliente.documento)))
    sesion.rollback()
    with pytest.raises(IntegrityError):
        nuevo_cliente(sesion, 1, documento="otro", qr_token="otro")


def test_migracion_0003_llena_la_busqueda_de_clientes_existentes(tmp_path):
    from alembic import command

    from gimnasio.db.engine import crear_motor
    from gimnasio.db.migraciones import configuracion_alembic

    url = f"sqlite:///{(tmp_path / 'vieja.db').as_posix()}"
    configuracion = configuracion_alembic(url)
    command.upgrade(configuracion, "0002")
    motor = crear_motor(url)
    with motor.begin() as con:
        con.execute(text(
            "INSERT INTO clientes (codigo, qr_token, tipo_documento, documento, nombres, "
            "apellidos, sexo, estado, creado_en, actualizado_en) VALUES ('000001', 'qr', 'CC', "
            "'123456', 'Ángela María', 'Núñez', 'F', 'activo', '2026-01-01', '2026-01-01')"))
    command.upgrade(configuracion, "head")
    with motor.connect() as con:
        assert con.execute(text("SELECT busqueda FROM clientes")).scalar() == "angela maria nunez"
    motor.dispose()


def test_busqueda_se_actualiza_al_modificar_nombre(clientes, admin):
    ficha = clientes.registrar(admin, datos())
    clientes.modificar(admin, ficha.id, datos(nombres="Ángela"))
    assert codigos(clientes.buscar(admin, FiltrosClientes(texto="angela gomez"))) == ["000001"]
    assert codigos(clientes.buscar(admin, FiltrosClientes(texto="maria jose"))) == []
