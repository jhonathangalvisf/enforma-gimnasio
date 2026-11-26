"""Pruebas de humo de las pantallas (sin mostrar ventanas: plataforma offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gimnasio.ui.configuracion import PantallaConfiguracion  # noqa: E402
from gimnasio.ui.dialogos import DialogoLogin, DialogoPrimerAdministrador  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from tests.conftest import CLAVE_PRUEBA  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_primer_arranque_crea_admin(qapp, servicios):
    d = DialogoPrimerAdministrador(servicios)
    d.campo_nombre.setText("Ana Admin")
    d.campo_usuario.setText("admin")
    d.campo_clave.setText(CLAVE_PRUEBA)
    d.campo_confirmar.setText("otra-cosa")
    d.crear()
    assert d.usuario_actual is None and "no coinciden" in d.error.text()
    d.campo_confirmar.setText(CLAVE_PRUEBA)
    d.crear()
    assert d.usuario_actual.es_admin


def test_login_con_teclado(qapp, servicios, admin):
    d = DialogoLogin(servicios)
    d.show()
    QTest.keyClicks(d.campo_usuario, "admin")
    QTest.keyClick(d.campo_usuario, Qt.Key.Key_Return)
    assert d.error.isHidden()  # Enter en el usuario solo pasa a la contraseña
    QTest.keyClicks(d.campo_clave, "incorrecta")
    QTest.keyClick(d.campo_clave, Qt.Key.Key_Return)
    assert d.usuario_actual is None and "incorrectos" in d.error.text()
    assert d.campo_clave.text() == ""
    QTest.keyClicks(d.campo_clave, CLAVE_PRUEBA)
    QTest.keyClick(d.campo_clave, Qt.Key.Key_Return)
    assert d.usuario_actual and d.usuario_actual.id == admin.id
    d.close()


def test_recepcion_no_ve_configuracion(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    assert "configuracion" not in v.modulos_visibles()
    assert v.modulos_visibles()[0] == "recepcion"
    assert {"clientes", "pagos", "ayuda"} <= set(v.modulos_visibles())
    v.close()


def test_admin_ve_todo_y_ctrl_k_enfoca_busqueda(qapp, servicios, admin):
    v = VentanaPrincipal(servicios, admin)
    v.show()
    assert "configuracion" in v.modulos_visibles()
    v.ir_a("configuracion")
    assert v.modulo_actual() == "configuracion"
    QTest.keySequence(v, QKeySequence("Ctrl+K"))
    qapp.processEvents()
    assert v.busqueda.hasFocus() or qapp.focusWidget() is v.busqueda
    v.close()


def test_cerrar_sesion_por_inactividad_excepto_en_recepcion(qapp, servicios, admin, reloj):
    v = VentanaPrincipal(servicios, admin)
    cerradas = []
    v.sesion_cerrada.connect(cerradas.append)
    v.control_inactividad._reloj = reloj
    v.control_inactividad.registrar_actividad()
    reloj.avanzar(minutes=30)
    v.ir_a("recepcion")
    v.revisar_inactividad()
    assert cerradas == []
    v.ir_a("clientes")
    v.revisar_inactividad()
    assert cerradas == [True]


def test_pantalla_configuracion_guarda_y_lista(qapp, servicios, admin, recepcion):
    p = PantallaConfiguracion(servicios, admin)
    p.parametros.editores["dias_por_vencer"].setValue(8)
    p.parametros.guardar()
    assert servicios.configuracion.obtener("dias_por_vencer") == 8
    assert "1 cambio" in p.parametros.mensaje.text()
    assert p.usuarios.tabla.rowCount() == 2
    p.auditoria.buscar()
    assert p.auditoria.tabla.rowCount() >= 3


def test_tablas_ordenadas_por_defecto(qapp, servicios, admin, recepcion, reloj):
    p = PantallaConfiguracion(servicios, admin)
    nombres = [p.usuarios.tabla.item(i, 0).text() for i in range(p.usuarios.tabla.rowCount())]
    assert nombres == sorted(nombres)
    # Auditoría: del más reciente al más antiguo aunque cambie el mes.
    reloj.avanzar(days=40)
    servicios.sesion.cerrar_sesion(admin)
    from PySide6.QtCore import QDate
    p.auditoria.desde.setDate(QDate(2026, 11, 1))
    p.auditoria.hasta.setDate(QDate(2027, 1, 31))
    p.auditoria.buscar()
    assert p.auditoria.tabla.item(0, 2).text() == "Cierre de sesión"
