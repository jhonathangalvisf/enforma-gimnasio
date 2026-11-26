"""Pruebas de las pantallas de membresías, pagos, planes y cierre de caja (Qt offscreen)."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QDate  # noqa: E402

from gimnasio.servicios.pagos import DatosPago  # noqa: E402
from gimnasio.ui.cliente_ficha import PESTANA_MEMBRESIAS, PESTANA_PAGOS, DialogoFicha  # noqa: E402
from gimnasio.ui.configuracion import DialogoPlan, PantallaConfiguracion  # noqa: E402
from gimnasio.ui.pagos import DialogoMembresia, DialogoPago, PantallaPagos  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from tests.test_clientes import datos  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def plan(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


@pytest.fixture
def cliente(servicios, admin):
    return servicios.clientes.registrar(admin, datos()).id


class Abridor:
    def __init__(self):
        self.rutas = []

    def __call__(self, ruta):
        self.rutas.append(ruta)


def test_renovar_con_abono_y_recibo(qapp, servicios, recepcion, plan, cliente):
    d = DialogoMembresia(servicios, recepcion, cliente)
    d.abrir = abridor = Abridor()
    assert d.campo_plan.currentData() == plan.id
    assert d.campo_precio.value() == 120_000 and not d.campo_precio.isEnabled()
    assert d.etiqueta_fin.text().startswith("25/12/2026")
    d.pago.monto.setValue(50_000)
    d.pago.metodo.setCurrentIndex(d.pago.metodo.findData("tarjeta"))
    d.guardar()
    assert "referencia" in d.error.text() and d.resultado is None
    d.pago.referencia.setText("APR-1")
    d.guardar()
    assert d.resultado.saldo == 70_000
    assert abridor.rutas and abridor.rutas[0].name == "R-000001.pdf"
    # La siguiente renovación propone el día siguiente al vencimiento.
    d2 = DialogoMembresia(servicios, recepcion, cliente)
    assert d2.campo_inicio.date() == QDate(2026, 12, 26)
    assert "70.000" in d2.avisos.text()


def test_admin_cambia_precio_con_motivo(qapp, servicios, admin, plan, cliente):
    d = DialogoMembresia(servicios, admin, cliente)
    d.abrir_recibo.setChecked(False)
    assert d.campo_precio.isEnabled() and d.campo_motivo.isHidden()
    d.campo_precio.setValue(100_000)
    assert not d.campo_motivo.isHidden()
    assert d.pago.monto.value() == 100_000  # el pago no supera el nuevo precio
    d.guardar()
    assert "motivo" in d.error.text()
    d.campo_motivo.setText("Convenio empresa")
    d.guardar()
    assert d.resultado.precio_pactado == 100_000 and d.ruta_recibo is None


def test_registrar_sin_pago(qapp, servicios, recepcion, plan, cliente):
    d = DialogoMembresia(servicios, recepcion, cliente)
    d.sin_pago.setChecked(True)
    assert not d.pago.isEnabled()
    d.guardar()
    assert d.resultado.pago is None and d.resultado.saldo == 120_000


def test_dialogo_pago_suelto_es_otro_concepto(qapp, servicios, recepcion, cliente):
    """El casillero ya no se cobra aquí: se cobra al asignarlo o renovarlo (Fase 5)."""
    d = DialogoPago(servicios, recepcion, cliente)
    d.abrir_recibo.setChecked(False)
    assert d.campo_concepto.findData("casillero") == -1
    assert d.campo_concepto.currentData() == "otro"
    d.pago.monto.setValue(15_000)
    d.guardar()
    assert d.resultado.monto == 15_000 and d.resultado.saldo_despues is None


def test_ficha_muestra_saldo_y_permite_abonar_y_anular(qapp, servicios, admin, recepcion, plan, cliente):
    servicios.pagos.registrar_membresia(recepcion, cliente, plan.id, pago=DatosPago(20_000))
    f = DialogoFicha(servicios, recepcion, cliente)
    f.abrir = Abridor()
    assert "100.000" in f.etiqueta_saldo.text()
    assert f.boton_anular_membresia is None and f.boton_anular_pago is None  # recepción
    assert f.tabla_membresias.item(0, 5).text() == "$ 100.000"
    abono = DialogoPago(servicios, recepcion, cliente, f.ficha.membresias[0])
    assert abono.pago.monto.value() == 100_000
    abono.abrir_recibo.setChecked(False)
    abono.guardar()
    f.cargar()
    assert f.ficha.saldo_pendiente == 0
    assert f.tabla_pagos.item(0, 0).text() == "R-000002"

    fa = DialogoFicha(servicios, admin, cliente)
    fa.abrir = abridor = Abridor()
    fa.pedir_motivo = lambda *a: "Cobro duplicado"
    fa.pestanas.setCurrentIndex(PESTANA_PAGOS)
    fa.tabla_pagos.selectRow(0)
    fa.ver_recibo()
    assert abridor.rutas[-1].name == "R-000002.pdf"
    fa.anular_pago()
    assert fa.pestanas.currentIndex() == PESTANA_PAGOS
    assert fa.ficha.pagos[0].anulado and fa.ficha.saldo_pendiente == 100_000
    fa.tabla_membresias.selectRow(0)
    fa.pedir_motivo = lambda *a: "Plan equivocado"
    fa.anular_membresia()
    assert fa.pestanas.currentIndex() == PESTANA_MEMBRESIAS
    assert fa.ficha.membresias[0].estado == "anulada"
    assert all(p.anulado for p in fa.ficha.pagos)


def test_cierre_de_caja_recepcion_y_admin(qapp, servicios, admin, recepcion, plan, cliente):
    servicios.pagos.registrar_membresia(recepcion, cliente, plan.id, pago=DatosPago(120_000))
    p = servicios.pagos.registrar_pago(admin, cliente, DatosPago(10_000, "transferencia", "T1"),
                                       concepto="otro")
    caja = PantallaPagos(servicios, recepcion)
    assert not caja.campo_dia.isEnabled() and caja.boton_anular is None
    assert caja.totales["total"].text() == "$ 120.000"
    assert caja.tabla.rowCount() == 1

    caja_admin = PantallaPagos(servicios, admin, pedir=lambda *a: "Error")
    caja_admin.abrir = Abridor()
    assert caja_admin.totales["total"].text() == "$ 130.000"
    assert caja_admin.tabla_usuarios.rowCount() == 2
    fila = next(i for i in range(caja_admin.tabla.rowCount())
                if caja_admin.tabla.item(i, 0).text() == "R-000002")
    caja_admin.tabla.selectRow(fila)
    assert caja_admin.pago_seleccionado() == p.id
    caja_admin.anular()
    assert caja_admin.totales["total"].text() == "$ 120.000"
    assert caja_admin.totales["anulados"].text() == "1 · $ 10.000"
    caja_admin.campo_dia.setDate(QDate(2026, 11, 25))
    caja_admin.actualizar()
    assert caja_admin.tabla.rowCount() == 0


def test_pestana_planes(qapp, servicios, admin):
    servicios.planes.crear_planes_ejemplo()
    conf = PantallaConfiguracion(servicios, admin)
    assert conf.pestanas.tabText(2) == "Planes"
    planes = conf.planes
    assert planes.tabla.rowCount() == 4
    d = DialogoPlan(servicios, admin)
    d.campo_nombre.setText("Semestral")
    d.campo_dias.setValue(180)
    d.campo_precio.setValue(600_000)
    d.guardar()
    planes.cargar()
    assert planes.tabla.rowCount() == 5
    semestral = next(p for p in servicios.planes.listar(admin) if p.nombre == "Semestral")
    assert semestral.activo and semestral.precio == 600_000
    fila = next(i for i in range(planes.tabla.rowCount())
                if planes.tabla.item(i, 0).text() == "Semestral")
    planes.tabla.selectRow(fila)
    assert planes.boton_estado.text() == "Desactivar"
    planes.cambiar_estado()
    assert not next(p for p in servicios.planes.listar(admin) if p.nombre == "Semestral").activo


def test_modulo_pagos_disponible(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    v.ir_a("pagos")
    assert isinstance(v.pantallas.currentWidget(), PantallaPagos)
    v._detener()
    v.close()


def test_fecha_hoy_de_prueba(servicios):
    assert servicios.pagos.hoy() == date(2026, 11, 26)
