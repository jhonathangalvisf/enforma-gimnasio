"""Pruebas de las pantallas de clientes (Qt offscreen, sin mostrar ventanas)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gimnasio.servicios.clientes import FiltrosClientes  # noqa: E402
from gimnasio.ui import cliente_ficha  # noqa: E402
from gimnasio.ui.cliente_ficha import DialogoFicha, cambiar_estado  # noqa: E402
from gimnasio.ui.cliente_formulario import DialogoCliente  # noqa: E402
from gimnasio.ui.clientes import TAMANO_PAGINA, PantallaClientes  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from tests.test_clientes import _asignar_casillero, datos  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def llenar(d: DialogoCliente, **campos):
    d.campo_documento.setText(campos.get("documento", "1020304050"))
    d.campo_nombres.setText(campos.get("nombres", "Laura"))
    d.campo_apellidos.setText(campos.get("apellidos", "Ríos"))
    d.campo_sexo.setCurrentIndex(d.campo_sexo.findData("F"))
    d.campo_nacimiento.setText(campos.get("nacimiento", "05/03/1990"))
    d.campo_telefonos.setText("300 111 2233, 6045556677")
    d.campo_correos.setText("laura@example.com")
    d.campos_emergencia[0][0].setText("Mamá")
    d.campos_emergencia[0][1].setText("3109998877")


def test_registrar_desde_formulario(qapp, servicios, recepcion):
    d = DialogoCliente(servicios, recepcion)
    llenar(d, nacimiento="31/02/1990")
    d.guardar()
    assert d.ficha is None and "dd/mm/aaaa" in d.error.text()
    llenar(d)
    d.guardar()
    assert d.ficha.codigo == "000001"
    assert d.ficha.telefonos == ["3001112233", "6045556677"]
    assert d.ficha.fecha_nacimiento.isoformat() == "1990-03-05"


def test_recepcion_ve_bloqueados_los_datos_personales(qapp, servicios, recepcion):
    ficha = servicios.clientes.registrar(recepcion, datos())
    d = DialogoCliente(servicios, recepcion, ficha)
    assert not d.campo_nombres.isEnabled() and not d.campo_documento.isEnabled()
    assert d.campo_telefonos.isEnabled() and d.campo_direccion.isEnabled()
    d.campo_telefonos.setText("3001234567")
    d.guardar()
    assert d.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert servicios.clientes.obtener_ficha(recepcion, ficha.id).telefonos == ["3001234567"]


def test_lista_busca_filtra_y_carga_por_paginas(qapp, servicios, admin):
    for i in range(TAMANO_PAGINA + 30):
        servicios.clientes.registrar(admin, datos(
            documento=f"{50_000_000 + i}", nombres=f"Persona{i}", apellidos="Prueba",
            sexo="M" if i % 2 else "F", telefonos=[], correos=[], emergencias=[]))
    p = PantallaClientes(servicios, admin)
    assert p.desbloquear()
    assert p.modelo.total == TAMANO_PAGINA + 30
    assert p.modelo.rowCount() == TAMANO_PAGINA  # carga virtual
    assert p.modelo.canFetchMore()
    p.modelo.fetchMore()
    assert p.modelo.rowCount() == TAMANO_PAGINA + 30 and not p.modelo.canFetchMore()
    p.filtro_sexo.setCurrentIndex(p.filtro_sexo.findData("M"))
    assert p.modelo.total == (TAMANO_PAGINA + 30) // 2
    p.campo_busqueda.setText("persona7")
    p.actualizar()
    assert {f.nombres for f in p.modelo.filas} >= {"Persona7", "Persona71"}
    p.limpiar_filtros()
    assert p.modelo.total == TAMANO_PAGINA + 30
    p.filtro_desde.setText("99/99/2026")
    p.actualizar()
    assert "dd/mm/aaaa" in p.mensaje.text()


def test_orden_por_columna_en_la_base(qapp, servicios, admin):
    for doc, apellido in (("111111", "Zuluaga"), ("222222", "Arias")):
        servicios.clientes.registrar(admin, datos(documento=doc, apellidos=apellido))
    p = PantallaClientes(servicios, admin)
    assert p.desbloquear()
    assert p.modelo.filas[0].apellidos == "Arias"
    p.tabla.sortByColumn(0, Qt.SortOrder.DescendingOrder)  # código
    assert p.modelo.orden == "codigo" and p.modelo.filas[0].codigo == "000002"


def test_exportar_solo_admin(qapp, servicios, admin, recepcion, tmp_path):
    servicios.clientes.registrar(admin, datos())
    assert PantallaClientes(servicios, recepcion).boton_excel is None
    p = PantallaClientes(servicios, admin)
    assert p.desbloquear()
    assert p.exportar("xlsx", str(tmp_path / "lista.xlsx")) == 1
    assert (tmp_path / "lista.xlsx").exists()


def test_ficha_tiene_las_siete_pestanas(qapp, servicios, admin, recepcion):
    ficha = servicios.clientes.registrar(admin, datos())
    f = DialogoFicha(servicios, admin, ficha.id)
    titulos = [f.pestanas.tabText(i).split(" (")[0] for i in range(f.pestanas.count())]
    assert titulos == ["Datos", "Contactos", "Membresías", "Pagos", "Asistencias",
                       "Casillero", "Alertas"]
    assert f.boton_estado is not None
    assert DialogoFicha(servicios, recepcion, ficha.id).boton_estado is None


def test_inactivar_desde_la_ficha_pregunta_por_el_casillero(qapp, servicios, admin, motor):
    from gimnasio.db.engine import crear_fabrica_sesiones

    ficha = servicios.clientes.registrar(admin, datos())
    _asignar_casillero(crear_fabrica_sesiones(motor), ficha.id)
    preguntas = []

    def preguntar(_padre, numero):
        preguntas.append(numero)
        return cliente_ficha.CANCELAR

    assert not cambiar_estado(None, servicios, admin, ficha.id,
                              pedir_motivo=lambda *_: "Se retiró", preguntar_casillero=preguntar)
    assert preguntas == ["007"] and servicios.clientes.obtener_ficha(admin, ficha.id).activo
    assert cambiar_estado(None, servicios, admin, ficha.id, pedir_motivo=lambda *_: "Se retiró",
                          preguntar_casillero=lambda *_: cliente_ficha.LIBERAR)
    final = servicios.clientes.obtener_ficha(admin, ficha.id)
    assert not final.activo and final.casillero is None
    assert cambiar_estado(None, servicios, admin, ficha.id)  # activar no pregunta
    assert servicios.clientes.obtener_ficha(admin, ficha.id).activo


def test_busqueda_global_ctrl_k(qapp, servicios, admin, monkeypatch):
    a = servicios.clientes.registrar(admin, datos())
    servicios.clientes.registrar(admin, datos(documento="99887766", nombres="María Elena"))
    v = VentanaPrincipal(servicios, admin)
    abiertas = []
    monkeypatch.setattr(v, "abrir_ficha", abiertas.append)
    v.show()
    v.activateWindow()
    QTest.qWaitForWindowActive(v)
    QTest.keyClick(v, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert QtWidgets.QApplication.focusWidget() is v.busqueda
    QTest.keyClicks(v.busqueda, "1")  # código sin ceros
    QTest.keyClick(v.busqueda, Qt.Key.Key_Return)
    assert abiertas == [a.id] and v.busqueda.text() == ""
    v.busqueda.setText("no existe nadie")
    assert v.buscar() is None and "No se encontró" in v.statusBar().currentMessage()
    v.close()


def test_pantalla_clientes_en_la_ventana(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    assert "clientes" in v.modulos_visibles()
    assert isinstance(v.pantalla_clientes, PantallaClientes)
    assert v.pantalla_clientes.modelo.filtros == FiltrosClientes()
    v.close()


# --- códigos, cédula repetida, vigencia a mano y resumen ---------------------------

def test_formulario_sugiere_codigo_y_admin_puede_cambiarlo(qapp, servicios, admin, recepcion):
    d = DialogoCliente(servicios, recepcion)
    assert d.campo_codigo.text() == "000001" and not d.campo_codigo.isEnabled()
    d = DialogoCliente(servicios, admin)
    assert d.campo_codigo.text() == "000001" and d.campo_codigo.isEnabled()
    llenar(d)
    d.campo_codigo.setText("5000")
    d.guardar()
    assert d.ficha.codigo == "005000"
    d = DialogoCliente(servicios, admin)
    assert d.campo_codigo.text() == "000001"  # el consecutivo no se movió
    # Corregir el código de un cliente ya registrado (solo admin).
    e = DialogoCliente(servicios, admin, servicios.clientes.obtener_ficha(admin, d_id := _id(servicios, admin, "005000")))
    e.campo_codigo.setText("4999")
    e.guardar()
    assert servicios.clientes.obtener_ficha(admin, d_id).codigo == "004999"


def _id(servicios, admin, codigo):
    return servicios.clientes.buscar_rapido(admin, codigo)[0].id


def test_cedula_repetida_reactiva_el_codigo_antiguo(qapp, servicios, admin):
    viejo = servicios.clientes.registrar(admin, datos(documento="1020304050"))
    servicios.clientes.inactivar(admin, viejo.id, "Se retiró")
    preguntas = []
    d = DialogoCliente(servicios, admin,
                       preguntar=lambda _p, _t, texto: preguntas.append(texto) or True)
    llenar(d, documento="1020304050")
    d.guardar()
    assert "000001" in preguntas[0] and "reactivarlo" in preguntas[0]
    assert d.ficha.id == viejo.id and d.ficha.activo
    assert servicios.clientes.buscar(admin).total == 1


def test_cedula_repetida_recepcion_no_reactiva(qapp, servicios, admin, recepcion):
    viejo = servicios.clientes.registrar(admin, datos(documento="1020304050"))
    servicios.clientes.inactivar(admin, viejo.id, "Se retiró")
    d = DialogoCliente(servicios, recepcion, preguntar=lambda *_: False)
    llenar(d, documento="1020304050")
    d.guardar()
    assert d.ficha is None and "ya está registrada" in d.error.text()
    assert not servicios.clientes.obtener_ficha(admin, viejo.id).activo


def test_cambiar_vigencia_desde_la_ficha(qapp, servicios, admin, recepcion, motor):
    from gimnasio.db.engine import crear_fabrica_sesiones
    from gimnasio.ui.cliente_ficha import DialogoVigencia
    from tests.test_clientes import HOY, membresia

    c = servicios.clientes.registrar(admin, datos())
    membresia(crear_fabrica_sesiones(motor), c.id, HOY, HOY)
    assert DialogoFicha(servicios, recepcion, c.id).boton_vigencia is None
    assert DialogoFicha(servicios, admin, c.id).boton_vigencia is not None
    d = DialogoVigencia(servicios, admin, servicios.clientes.obtener_ficha(admin, c.id))
    assert d.campo_plan is None
    d.campo_fecha.setText("31/12/2026")
    d.guardar()
    assert "motivo" in d.error.text()
    d.campo_motivo.setText("Cortesía de fin de año")
    d.guardar()
    assert servicios.clientes.obtener_ficha(admin, c.id).fecha_fin.isoformat() == "2026-12-31"


def test_resumen_al_dia_filtra_la_lista(qapp, servicios, admin, motor):
    from gimnasio.db.engine import crear_fabrica_sesiones
    from tests.test_clientes import HOY, membresia

    fabrica = crear_fabrica_sesiones(motor)
    a = servicios.clientes.registrar(admin, datos())
    servicios.clientes.registrar(admin, datos(documento="99887766"))
    membresia(fabrica, a.id, HOY, HOY + timedelta(days=29))
    p = PantallaClientes(servicios, admin)
    assert p.desbloquear()
    assert p.botones_resumen["al_dia"].text() == "✔ Al día: 1"
    assert p.botones_resumen["sin_membresia"].text() == "— Sin membresía: 1"
    p.botones_resumen["al_dia"].click()
    assert [f.id for f in p.modelo.filas] == [a.id]
    p.botones_resumen["total"].click()
    assert p.modelo.total == 2
