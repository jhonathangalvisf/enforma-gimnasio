"""Pantallas: casillero al inscribir y en la renovación (mismo recibo) y "Pagar casillero…"
en Pagos (recibo propio)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.ui.casilleros import DialogoAsignarCasillero, DialogoRenovarCasillero  # noqa: E402
from gimnasio.ui.cliente_formulario import DialogoCliente  # noqa: E402
from gimnasio.ui.clientes import PantallaClientes  # noqa: E402
from gimnasio.ui.pagos import DialogoMembresia, PantallaPagos  # noqa: E402
from tests.test_clientes import datos  # noqa: E402
from tests.test_ui_clientes import llenar  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def plan(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


@pytest.fixture
def libres(servicios, admin):
    servicios.casilleros.crear(admin, "M-1", "mixto")
    servicios.casilleros.crear(admin, "M-2", "mixto")
    return {n: i for i, n, _ in servicios.casilleros.libres(admin)}


def soltar(dialogos):
    """Los diálogos son hijos de la pantalla: se liberan antes que ella para que Qt no
    los borre dos veces al terminar la prueba."""
    for d in dialogos:
        d.setParent(None)
    dialogos.clear()


def elegir(combo, dato):
    combo.setCurrentIndex(combo.findData(dato))


def test_renovar_membresia_con_casillero_en_un_recibo(qapp, servicios, recepcion, admin, plan,
                                                     libres):
    c = servicios.clientes.registrar(admin, datos()).id
    d = DialogoMembresia(servicios, recepcion, c, con_casillero=True)
    rutas = []
    d.abrir = rutas.append
    assert d.casillero.isChecked() and d.casillero.campo_casillero.currentData() is None
    d.casillero.monto.setValue(20_000)
    d.guardar()
    assert "Elija el casillero" in d.error.text() and d.resultado is None
    elegir(d.casillero.campo_casillero, libres["M-2"])
    d.sin_pago.setChecked(True)
    d.guardar()
    assert "pago de la mensualidad" in d.error.text()
    d.sin_pago.setChecked(False)
    d.guardar()
    assert d.resultado.pago.recibo == "R-000001" and d.resultado_casillero.numero == "M-2"
    assert [r.name for r in rutas] == ["R-000001.pdf"]
    datos_recibo = servicios.pagos.datos_recibo(recepcion, d.resultado.pago.id)
    assert datos_recibo.monto == 140_000 and len(datos_recibo.lineas) == 2
    # La siguiente renovación propone renovar el casillero que ya tiene.
    d2 = DialogoMembresia(servicios, recepcion, c)
    assert not d2.casillero.isChecked()
    assert "Renovar el casillero M-2" in d2.casillero.descripcion.text()


def test_inscripcion_pregunta_por_el_casillero(qapp, servicios, recepcion, plan, libres):
    p = PantallaClientes(servicios, recepcion)
    vistos = []

    def ejecutar(dialogo):
        vistos.append(dialogo)
        if isinstance(dialogo, DialogoCliente):
            assert dialogo.campo_casillero is not None and not dialogo.quiere_casillero
            llenar(dialogo)
            dialogo.campo_casillero.setChecked(True)
            dialogo.guardar()
            return dialogo.result()
        assert isinstance(dialogo, DialogoMembresia)
        assert dialogo.windowTitle().startswith("Inscripción") and dialogo.casillero.isChecked()
        dialogo.abrir = lambda _ruta: None
        elegir(dialogo.casillero.campo_casillero, libres["M-1"])
        dialogo.casillero.monto.setValue(15_000)
        dialogo.guardar()
        return dialogo.result()

    p._ejecutar = ejecutar
    p.nuevo()
    assert len(vistos) == 2
    m = vistos[1]
    assert m.resultado is not None and m.resultado_casillero.numero == "M-1"
    assert servicios.casilleros.de_cliente(recepcion, m._cliente_id).numero == "M-1"
    del m
    soltar(vistos)


def test_inscripcion_sin_casillero_solo_cobra_mensualidad(qapp, servicios, recepcion, plan, libres):
    p = PantallaClientes(servicios, recepcion)
    vistos = []

    def ejecutar(dialogo):
        vistos.append(dialogo)
        if isinstance(dialogo, DialogoCliente):
            llenar(dialogo)
            dialogo.guardar()
            return dialogo.result()
        assert not dialogo.casillero.isChecked()
        dialogo.abrir = lambda _ruta: None
        dialogo.guardar()
        return dialogo.result()

    p._ejecutar = ejecutar
    p.nuevo()
    assert vistos[1].resultado is not None and vistos[1].resultado_casillero is None
    assert servicios.casilleros.de_cliente(recepcion, vistos[1]._cliente_id) is None
    soltar(vistos)


def test_editar_cliente_no_pregunta_por_casillero(qapp, servicios, admin):
    c = servicios.clientes.registrar(admin, datos())
    d = DialogoCliente(servicios, admin, servicios.clientes.obtener_ficha(admin, c.id))
    assert d.campo_casillero is None


def test_pagar_casillero_desde_pagos(qapp, servicios, recepcion, admin, libres):
    c = servicios.clientes.registrar(admin, datos())
    p = PantallaPagos(servicios, recepcion, pedir=lambda *_: c.codigo)
    p.abrir = lambda _ruta: None
    assert p.desbloquear() and p.boton_casillero is not None

    def asignar(dialogo):
        assert isinstance(dialogo, DialogoAsignarCasillero)
        elegir(dialogo.campo_casillero, libres["M-1"])
        dialogo.periodo.pago.monto.setValue(20_000)
        dialogo.guardar()
        return dialogo.result()

    d = p.pagar_casillero(asignar)
    assert d.resultado.pago.recibo == "R-000001"
    assert p.cierre.total == 20_000

    def renovar(dialogo):
        assert isinstance(dialogo, DialogoRenovarCasillero)
        assert dialogo.periodo.cobrar.isChecked()
        dialogo.periodo.pago.monto.setValue(20_000)
        dialogo.guardar()
        return dialogo.result()

    d = p.pagar_casillero(renovar)
    assert d.resultado.pago.recibo == "R-000002"  # recibo propio, siguiente número
    assert p.cierre.total == 40_000
    soltar([d])
    del d


def test_pagar_casillero_cliente_no_encontrado(qapp, servicios, recepcion, monkeypatch):
    errores = []
    monkeypatch.setattr("gimnasio.ui.pagos.mostrar_error", lambda _p, e: errores.append(str(e)))
    p = PantallaPagos(servicios, recepcion, pedir=lambda *_: "999999")
    assert p.pagar_casillero(lambda _d: 1) is None
    assert "No se encontró" in errores[0]
