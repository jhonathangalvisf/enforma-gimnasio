"""Pantalla de Invitados (Qt offscreen): registro solo con teclado, reutilización por
documento, contador visible, duplicado del día, límite con autorización, ficha con el
detalle de fechas, eliminación con motivo, lista y reportes."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.servicios.clientes import DatosCliente  # noqa: E402
from gimnasio.servicios.invitados import LIMITE_AUTORIZAR, REGISTRADA, DatosInvitado  # noqa: E402
from gimnasio.ui.invitados import DialogoFichaInvitado, PantallaInvitados  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from tests.conftest import CLAVE_PRUEBA  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def anfitrion(servicios, admin):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="5566778899", nombres="Laura", apellidos="Ríos",
        sexo="F", telefonos=["3001234567"], fecha_nacimiento=date(1990, 3, 15)))


def test_invitado_nuevo_solo_con_teclado(qapp, servicios, recepcion, anfitrion):
    pantalla = PantallaInvitados(servicios, recepcion)
    p = pantalla.invitados
    p.documento.setText("1.020.304")
    p.documento.returnPressed.emit()
    assert p.ficha_actual is None and "nuevo" in p.estado.text()
    p.nombre.setText("José Pérez")
    p.nombre.returnPressed.emit()
    p.telefono.setText("3001112233")
    p.telefono.returnPressed.emit()
    p.campo_anfitrion.setText(anfitrion.codigo)
    p.campo_anfitrion.returnPressed.emit()  # elige al anfitrión y registra
    assert p.ultimo_resultado.estado == REGISTRADA
    assert "Visita registrada" in p.estado.text()
    assert "lleva 1 visita como invitado" in p.estado.text()
    assert p.documento.text() == ""  # listo para el siguiente
    ficha = p.ultimo_resultado.ficha
    assert ficha.visitas[0].anfitrion == f"{anfitrion.codigo} Laura Ríos"
    assert p.tabla.rowCount() == 1 and p.tabla.item(0, 3).text() == "1"


def test_invitado_existente_muestra_contador_y_se_reutiliza(qapp, servicios, recepcion):
    ficha, _ = servicios.invitados.registrar(recepcion, DatosInvitado("Ana Gómez", "111222"))
    servicios.invitados.registrar_visita(recepcion, ficha.id)
    pantalla = PantallaInvitados(servicios, recepcion)
    p = pantalla.invitados
    p.documento.setText("111222")
    p.documento.returnPressed.emit()
    assert p.ficha_actual.id == ficha.id
    assert not p.nombre.isEnabled() and p.nombre.text() == "Ana Gómez"
    assert "lleva 1 visita" in p.estado.text()
    preguntas = []
    p.confirmar = lambda _p, titulo, texto: preguntas.append(texto) or True
    p.campo_anfitrion.returnPressed.emit()  # sin anfitrión: registra
    assert preguntas and "ya registró visita hoy" in preguntas[0]
    assert p.ultimo_resultado.ficha.total_visitas == 2
    assert len(servicios.invitados.buscar(recepcion)) == 1  # no se duplicó


def test_duplicado_cancelado_no_registra(qapp, servicios, recepcion):
    ficha, _ = servicios.invitados.registrar(recepcion, DatosInvitado("Ana Gómez", "111222"))
    servicios.invitados.registrar_visita(recepcion, ficha.id)
    pantalla = PantallaInvitados(servicios, recepcion)
    p = pantalla.invitados
    p.confirmar = lambda *_: False
    p.documento.setText("111222")
    p.documento.returnPressed.emit()
    p.registrar()
    assert servicios.invitados.ficha(recepcion, ficha.id).total_visitas == 1


def test_limite_pide_clave_del_admin(qapp, servicios, admin, recepcion):
    servicios.configuracion.guardar(admin, {"invitado_visitas_mes": 1})
    ficha, _ = servicios.invitados.registrar(recepcion, DatosInvitado("Ana Gómez", "111222"))
    servicios.invitados.registrar_visita(recepcion, ficha.id)
    pantalla = PantallaInvitados(servicios, recepcion)
    p = pantalla.invitados
    p.confirmar = lambda *_: True
    pedidos = []
    p.pedir_autorizacion = lambda f: pedidos.append(f) or None  # cancela
    p.documento.setText("111222")
    p.documento.returnPressed.emit()
    assert "máximo 1" in p.detalle.text()
    r = p.registrar()
    assert r.estado == LIMITE_AUTORIZAR and pedidos[0].limite_alcanzado
    p.pedir_autorizacion = lambda f: ("admin", CLAVE_PRUEBA, "conoce el gimnasio")
    r = p.registrar()
    assert r.estado == REGISTRADA and r.ficha.visitas[0].autorizada_por == "admin"


def test_ficha_muestra_contador_grande_y_fechas(qapp, servicios, admin, recepcion, reloj):
    ficha, _ = servicios.invitados.registrar(recepcion, DatosInvitado("Ana Gómez", "111222"))
    reloj.avanzar(days=-7)
    servicios.invitados.registrar_visita(recepcion, ficha.id)
    reloj.avanzar(days=7)
    servicios.invitados.registrar_visita(recepcion, ficha.id)
    dialogo = DialogoFichaInvitado(servicios, recepcion, ficha.id)
    assert dialogo.numero.text() == "2"
    assert dialogo.contador.text() == "Lleva 2 visitas como invitado"
    assert "2 este mes" in dialogo.detalle_contador.text()
    assert "primera: 19/11/2026" in dialogo.detalle_contador.text()
    assert dialogo.tabla.rowCount() == 2
    assert [dialogo.tabla.item(i, 1).text() for i in range(2)] == ["26/11/2026", "19/11/2026"]
    assert [dialogo.tabla.item(i, 0).text() for i in range(2)] == ["2", "1"]
    # Eliminar la de hoy con motivo.
    dialogo.tabla.selectRow(0)
    dialogo.pedir_motivo = lambda *_: "Registrada por error"
    dialogo.eliminar()
    assert dialogo.cambio and dialogo.numero.text() == "1" and dialogo.tabla.rowCount() == 1


def test_lista_busca_y_admin_ve_reportes(qapp, servicios, admin, recepcion, tmp_path):
    a, _ = servicios.invitados.registrar(recepcion, DatosInvitado("Ana Gómez", "111222"))
    servicios.invitados.registrar(recepcion, DatosInvitado("Beto Ruiz", "333444"))
    servicios.invitados.registrar_visita(recepcion, a.id)
    pantalla = PantallaInvitados(servicios, admin)
    p = pantalla.invitados
    p.actualizar()
    assert p.tabla.rowCount() == 2
    p.busqueda.setText("gomez")
    assert p.tabla.rowCount() == 1 and p.tabla.item(0, 0).text() == "Ana Gómez"
    abiertos = []
    p.abrir_ficha = abiertos.append
    p.tabla.selectRow(0)
    p.ver_seleccionado()
    assert abiertos == [a.id]

    rep = pantalla.reportes
    rep.tipo.setCurrentIndex(rep.tipo.findData("invitados"))
    generado = rep.generar()
    assert generado.filas[0][1] == "Ana Gómez" and rep.tabla.rowCount() == 1
    rep.elegir_ruta = lambda sugerido, filtro: str(tmp_path / "invitados")
    assert rep.exportar("xlsx").exists()


def test_recepcion_solo_ve_reporte_de_hoy(qapp, servicios, recepcion):
    pantalla = PantallaInvitados(servicios, recepcion)
    rep = pantalla.reportes
    assert rep.tipo.count() == 1 and not rep.desde.isEnabled()
    assert rep.generar() is not None


def test_menu_principal_abre_invitados(qapp, servicios, recepcion):
    ventana = VentanaPrincipal(servicios, recepcion)
    assert "invitados" in ventana.modulos_visibles()
    ventana.ir_a("invitados")
    assert isinstance(ventana.pantallas.currentWidget(), PantallaInvitados)
    ventana._detener()
    ventana.close()
