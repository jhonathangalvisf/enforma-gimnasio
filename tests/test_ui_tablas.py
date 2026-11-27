"""Las tablas no deben congelar la aplicación al llenarse estando visibles.

Antes, con el modo «ajustar al contenido» de Qt, cada celda escrita volvía a medir todas
las filas: Pagos, Asistencia, Casilleros e Invitados tardaban de 25 s a 60 s en abrirse con
los datos importados del programa anterior, sobre todo al volver a un módulo ya abierto."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.ui.comunes import celda, tabla  # noqa: E402

QHeaderView = QtWidgets.QHeaderView


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _llenar(t, filas: int) -> None:
    t.setSortingEnabled(False)
    t.setRowCount(filas)
    for i in range(filas):
        for j in range(t.columnCount()):
            # textos de largo distinto: así el ancho de las columnas cambia al llenar
            t.setItem(i, j, celda(f"Cliente {i} " + "x" * (i % 37)))
    t.setSortingEnabled(True)


def test_llenar_tabla_visible_es_rapido(qapp):
    t = tabla(["Recibo", "Hora", "Cliente", "Concepto", "Método", "Monto", "Usuario", "Estado"])
    t.resize(1000, 600)
    t.show()
    qapp.processEvents()
    _llenar(t, 300)
    qapp.processEvents()
    # Volver a llenar (lo que pasa al regresar a un módulo) reemplaza celdas existentes:
    # era el caso lento (300 filas tardaban más de un minuto).
    inicio = time.perf_counter()
    _llenar(t, 300)
    qapp.processEvents()
    assert time.perf_counter() - inicio < 2.0
    t.close()


def test_columnas_se_ajustan_al_contenido_despues_de_llenar(qapp):
    t = tabla(["A", "B", "Última"])
    t.show()
    qapp.processEvents()
    angosta = t.columnWidth(0)
    t.setSortingEnabled(False)
    t.setRowCount(1)
    t.setItem(0, 0, celda("Un texto bastante más largo que el título de la columna"))
    t.setItem(0, 1, celda("corto"))
    t.setSortingEnabled(True)
    qapp.processEvents()  # el ajuste se hace una sola vez, al terminar el llenado
    assert t.columnWidth(0) > angosta
    assert t.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert t.horizontalHeader().stretchLastSection()
    t.close()


def test_columna_que_se_estira_no_se_toca(qapp):
    t = tabla(["A", "B", "C"])
    t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    t.resize(800, 300)
    t.show()
    qapp.processEvents()
    _llenar(t, 3)
    qapp.processEvents()
    assert t.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    t.close()
