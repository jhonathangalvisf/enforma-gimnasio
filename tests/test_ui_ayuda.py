"""Pantalla de Ayuda y F1 contextual (criterio 9 de la sección 12)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gimnasio.ui.ayuda import DialogoAyuda, PantallaAyuda, VisorAyuda, tema_para  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402

# Módulo del menú -> tema que debe abrir F1.
ESPERADO = {
    "recepcion": "recepcion", "clientes": "clientes", "asistencia": "asistencia",
    "casilleros": "casilleros", "invitados": "invitados", "pagos": "pagos",
    "reportes": "reportes", "configuracion": "configuracion", "backups": "backups",
    "ayuda": "inicio",
}


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def _cerrar(v: VentanaPrincipal) -> None:
    v._detener()
    v._cerrando_sesion = True
    v.close()


def _f1(widget) -> None:
    QTest.keyClick(widget, Qt.Key.Key_F1)


def test_menu_ayuda_es_una_pantalla_real(qapp, servicios, admin):
    v = VentanaPrincipal(servicios, admin)
    v.ir_a("ayuda")
    assert isinstance(v.pantallas.currentWidget(), PantallaAyuda)
    assert v.pantalla_ayuda.visor.tema_actual == "inicio"
    _cerrar(v)


@pytest.mark.parametrize("usuario", ["admin", "recepcion"])
def test_f1_abre_la_ayuda_del_modulo_activo(qapp, servicios, admin, recepcion, usuario):
    actual = admin if usuario == "admin" else recepcion
    v = VentanaPrincipal(servicios, actual)
    v.show()
    for clave in v.modulos_visibles():
        v.ir_a(clave)
        _f1(v.pantallas.currentWidget())
        assert v.ventana_ayuda is not None, clave
        assert v.ventana_ayuda.visor.tema_actual == ESPERADO[clave], clave
        assert v.ventana_ayuda.isVisible()
    _cerrar(v)


def test_f1_en_configuracion_usuarios_abre_usuarios(qapp, servicios, admin):
    v = VentanaPrincipal(servicios, admin)
    v.show()
    v.ir_a("configuracion")
    pantalla = v.pantallas.currentWidget()
    pantalla.pestanas.setCurrentWidget(pantalla.usuarios)
    _f1(pantalla.usuarios)
    assert v.ventana_ayuda.visor.tema_actual == "usuarios"
    _cerrar(v)


def test_f1_reutiliza_la_misma_ventana(qapp, servicios, admin):
    v = VentanaPrincipal(servicios, admin)
    v.show()
    v.ir_a("clientes")
    primera = v.abrir_ayuda()
    v.ir_a("pagos")
    segunda = v.abrir_ayuda()
    assert primera is segunda and segunda.visor.tema_actual == "pagos"
    assert segunda.windowTitle() == "Ayuda — Pagos, membresías y caja"
    _cerrar(v)


def test_f1_dentro_de_un_dialogo_modal(qapp, servicios, admin):
    """En una ficha (diálogo modal) F1 abre la ayuda encima de ella, con el tema de Clientes."""
    from gimnasio.ui.cliente_ficha import DialogoFicha
    from tests.test_clientes import datos

    ficha = servicios.clientes.registrar(admin, datos())
    v = VentanaPrincipal(servicios, admin)
    v.show()
    v.ir_a("recepcion")
    d = DialogoFicha(servicios, admin, ficha.id, padre=v)
    d.setWindowModality(Qt.WindowModality.ApplicationModal)
    d.show()
    qapp.processEvents()
    _f1(d)
    assert v.ventana_ayuda.visor.tema_actual == "clientes"
    assert v.ventana_ayuda.parentWidget() is d  # si no, el modal la bloquearía
    d.close()
    _cerrar(v)


def test_tema_para_los_dialogos(qapp, servicios, admin):
    from gimnasio.ui.casilleros import DialogoAsignarCasillero
    from gimnasio.ui.configuracion import DialogoUsuario
    from gimnasio.ui.dialogos import DialogoCambiarClave
    from gimnasio.ui.pagos import DialogoMembresia
    from tests.test_clientes import datos

    ficha = servicios.clientes.registrar(admin, datos())
    assert tema_para(DialogoMembresia(servicios, admin, ficha.id)) == "pagos"
    assert tema_para(DialogoAsignarCasillero(servicios, admin, cliente_id=ficha.id)) == "casilleros"
    assert tema_para(DialogoUsuario(servicios, admin)) == "usuarios"
    assert tema_para(DialogoCambiarClave(servicios, admin)) == "inicio"
    dialogo = DialogoMembresia(servicios, admin, ficha.id)  # se guarda: si no, Python lo libera
    caja = QtWidgets.QMessageBox(dialogo)
    assert tema_para(caja) == "pagos"  # mensajes: el tema de su ventana


def test_al_cerrar_la_ayuda_recepcion_recupera_el_foco(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    v.show()
    v.ir_a("recepcion")
    ayuda = v.abrir_ayuda()
    ayuda.close()
    qapp.processEvents()
    assert v.ventana_ayuda is None
    _cerrar(v)


def test_buscador_filtra_y_resalta(qapp, servicios, admin):
    visor = VisorAyuda(servicios, admin)
    visor.show()
    visor.buscador.setText("abono")
    assert visor.temas_listados()[0] == "pagos"
    assert visor.tema_actual == "pagos"
    assert len(visor.texto.extraSelections()) >= 3
    assert "tema" in visor.resumen.text()
    visor.buscador.setText("palabraquenoexiste")
    assert visor.temas_listados() == []
    assert "No se encontró" in visor.resumen.text()
    assert visor.texto.extraSelections() == []
    visor.buscador.clear()
    assert len(visor.temas_listados()) == len(servicios.ayuda.temas(admin))


def test_resaltado_sin_tildes(qapp, servicios, admin):
    visor = VisorAyuda(servicios, admin, "recepcion")
    assert visor.resaltar("recepcion") > 0  # el texto dice "Recepción"


def test_enlace_entre_temas(qapp, servicios, admin):
    visor = VisorAyuda(servicios, admin, "inicio")
    visor._al_hacer_clic_enlace(QUrl("tema:casilleros"))
    assert visor.tema_actual == "casilleros"
    assert visor.lista.currentItem().data(Qt.ItemDataRole.UserRole) == "casilleros"


def test_recepcion_no_ve_temas_de_administrador(qapp, servicios, recepcion):
    visor = VisorAyuda(servicios, recepcion, "configuracion")
    assert visor.tema_actual == "inicio"  # no tiene permiso: abre Primeros pasos
    assert "configuracion" not in visor.temas_listados()
    assert "usuarios" not in visor.temas_listados()


def test_dialogo_ayuda_no_es_modal(qapp, servicios, admin):
    d = DialogoAyuda(servicios, admin, "reportes")
    assert not d.isModal()
    assert d.windowTitle() == "Ayuda — Reportes"
