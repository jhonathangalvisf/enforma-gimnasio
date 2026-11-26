"""Pantallas de consulta de pagos y de borrado de pagos antiguos (Qt offscreen)."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QDate  # noqa: E402

from gimnasio.ui.pagos import PantallaPagos  # noqa: E402
from gimnasio.ui.pagos_consulta import PestanaConsultaPagos, PestanaDepuracion  # noqa: E402
from tests.test_consulta_depuracion_pagos import (  # noqa: E402,F401
    CLAVE_COPIAS, CLAVE_SEGURIDAD, HOY, fabrica, historial, mensual,
)


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Abridor:
    def __init__(self):
        self.rutas = []

    def __call__(self, ruta):
        self.rutas.append(ruta)


def poner_fecha(campo, dia):
    campo.setDate(QDate(dia.year, dia.month, dia.day))


def test_pestanas_segun_rol(qapp, servicios, admin, recepcion):
    p_admin = PantallaPagos(servicios, admin)
    assert [p_admin.pestanas.tabText(i) for i in range(p_admin.pestanas.count())] == [
        "Cierre de caja", "Consultar pagos", "Borrar pagos antiguos"]
    p_rec = PantallaPagos(servicios, recepcion)
    assert p_rec.depuracion is None and p_rec.pestanas.count() == 2


def test_consulta_por_cliente_fechas_y_exportar(qapp, servicios, admin, historial, tmp_path):
    p = PestanaConsultaPagos(servicios, admin)
    p.abrir = abridor = Abridor()
    p.todas_fechas.setChecked(True)
    p.consultar()
    assert p.tabla.rowCount() == 6 and "6 pagos válidos" in p.resumen.text()
    # Por fecha de pago: el último mes.
    p.todas_fechas.setChecked(False)
    poner_fecha(p.campo_desde, HOY - timedelta(days=31))
    poner_fecha(p.campo_hasta, HOY)
    p.consultar()
    assert p.tabla.rowCount() == 2
    # Por cliente: escribir el código.
    p.campo_cliente.setText("000001")
    p.buscar_cliente()
    assert p.cliente_id == historial[0] and p.tabla.rowCount() == 3
    assert "000001" in p.etiqueta_cliente.text()
    # Exportar a Excel y abrir el recibo seleccionado.
    p.elegir_ruta = lambda formato, sugerido: str(tmp_path / f"c.{formato}")
    assert p.exportar("xlsx").exists() and abridor.rutas[-1].suffix == ".xlsx"
    p.tabla.selectRow(0)
    p.ver_recibo()
    assert abridor.rutas[-1].suffix == ".pdf"


def test_recepcion_debe_elegir_cliente(qapp, servicios, recepcion, historial, monkeypatch):
    errores = []
    monkeypatch.setattr("gimnasio.ui.pagos_consulta.mostrar_error", lambda p, e: errores.append(e))
    p = PestanaConsultaPagos(servicios, recepcion)
    assert not p.boton_quitar_cliente.isVisibleTo(p)
    p.consultar()
    assert errores and p.tabla.rowCount() == 0
    p.campo_cliente.setText("000002")
    p.buscar_cliente()
    assert p.tabla.rowCount() == 3


def test_depuracion_con_clave(qapp, servicios, admin, historial, fabrica):
    servicios.backups.configurar_clave(admin, CLAVE_COPIAS, CLAVE_COPIAS)
    confirmaciones = []
    d = PestanaDepuracion(servicios, admin,
                          confirmar_borrado=lambda *a: confirmaciones.append(a) or True)
    assert d.paginas.currentIndex() == 0  # primero hay que crear la clave
    d.campo_clave_admin.setText("ClaveSegura1")
    d.campo_nueva.setText(CLAVE_SEGURIDAD)
    d.campo_confirmar.setText(CLAVE_SEGURIDAD)
    d.crear_clave()
    assert d.paginas.currentIndex() == 1 and "guardada" in d.resultado.text()

    d.campo_clave.setText("mala")
    d.entrar()
    assert not d.abierto and "no es correcta" in d.error.text()
    d.campo_clave.setText(CLAVE_SEGURIDAD)
    d.entrar()
    assert d.abierto

    poner_fecha(d.campo_corte, HOY - timedelta(days=45))
    d.ver_vista()
    assert "Se borrarían 2 pagos" in d.vista.text() and d.boton_borrar.isEnabled()
    assert d.borrar() is None and "motivo" in d.error.text()
    d.campo_motivo.setText("Aligerar historial")
    r = d.borrar()
    assert r and r.vista.pagos == 2 and confirmaciones
    assert "se borraron 2 pagos" in d.resultado.text()
    # Al cerrar el apartado se vuelve a pedir la clave.
    d.bloquear()
    assert not d.abierto and d.paginas.currentIndex() == 1
