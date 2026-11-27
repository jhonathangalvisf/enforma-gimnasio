"""Pestaña «Importar datos» de Configuración (offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.ui import importacion as ui_importacion  # noqa: E402
from gimnasio.ui.configuracion import PantallaConfiguracion  # noqa: E402
from tests.test_importacion import CLAVE_COPIAS, db3  # noqa: E402,F401


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_pestana_probar_e_importar(qapp, servicios, admin, db3, monkeypatch):  # noqa: F811
    pantalla = PantallaConfiguracion(servicios, admin)
    pestana = pantalla.importacion
    assert pantalla.pestanas.tabText(pantalla.pestanas.indexOf(pestana)) == "Importar datos"
    assert pestana.boton_importar.isEnabled() and not pestana.boton_informe.isEnabled()

    # El botón «Elegir carpeta…» va antes del campo, para que siempre se vea.
    fila = pestana.layout().itemAt(1).layout()
    assert fila.itemAt(0).widget() is pestana.boton_elegir
    assert pestana.boton_elegir.text() == "Elegir carpeta…"

    pestana.campo_carpeta.setText(f'"{db3}"')  # pegada con «Copiar como ruta»
    pestana.probar()
    assert pestana.campo_carpeta.text() == str(db3)
    assert "Prueba (no se guardó nada)" in pestana.resumen.toPlainText()
    assert pestana.boton_informe.isEnabled() and pestana.boton_importar.isEnabled()

    servicios.backups.configurar_clave(admin, CLAVE_COPIAS, CLAVE_COPIAS)
    monkeypatch.setattr(ui_importacion, "confirmar", lambda *a: True)
    pestana.importar()
    assert "Importación guardada" in pestana.resumen.toPlainText()
    assert not pestana.boton_importar.isEnabled()
    assert "ya se importaron" in pestana.estado.text()
    pantalla.deleteLater()


def test_sin_carpeta_muestra_error(qapp, servicios, admin, monkeypatch):
    errores = []
    monkeypatch.setattr(ui_importacion, "mostrar_error", lambda padre, e: errores.append(str(e)))
    pestana = ui_importacion.PestanaImportacion(servicios, admin)
    pestana.probar()
    assert errores and "carpeta" in errores[0]
    pestana.deleteLater()
