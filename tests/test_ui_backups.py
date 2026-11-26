"""Pantalla de Copias de seguridad, avisos del inicio y copias automáticas (offscreen)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from sqlalchemy import select  # noqa: E402

from gimnasio.modelos import BackupLog  # noqa: E402
from gimnasio.servicios.backups import TIPO_MANUAL  # noqa: E402
from gimnasio.ui.aplicacion import Aplicacion  # noqa: E402
from gimnasio.ui.backups import (  # noqa: E402
    DialogoClaveBackups, DialogoRestaurar, PantallaBackups, textos_aviso,
)
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from tests.conftest import nuevo_cliente  # noqa: E402

CLAVE = "copias-Enforma-2026"


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def con_clave(servicios, admin, sesion):
    nuevo_cliente(sesion, 1)
    sesion.commit()
    servicios.backups.configurar_clave(admin, CLAVE, CLAVE)
    return servicios


def test_textos_de_aviso(servicios, admin, recepcion, reloj):
    estado = servicios.backups.estado(admin)
    avisos_admin = textos_aviso(estado, es_admin=True)
    assert any("No hay ninguna copia" in a and "Haga una copia" in a for a in avisos_admin)
    assert any("Falta crear la contraseña" in a for a in avisos_admin)
    avisos_recepcion = textos_aviso(servicios.backups.estado(recepcion), es_admin=False)
    assert len(avisos_recepcion) == 1 and "Avise al administrador" in avisos_recepcion[0]


def test_recepcion_ve_el_aviso_sin_perder_el_foco_del_codigo(qapp, con_clave, recepcion):
    v = VentanaPrincipal(con_clave, recepcion)
    v.show()
    qapp.processEvents()
    assert "backups" not in v.modulos_visibles()
    assert v.aviso_backup.isVisible() and "Avise al administrador" in v.texto_aviso_backup.text()
    assert not v.boton_aviso_backup.isVisible()
    v.pantalla_recepcion.enfocar()
    qapp.processEvents()
    assert qapp.focusWidget() is v.pantalla_recepcion.campo
    v.close()


def test_aviso_desaparece_tras_la_copia(qapp, con_clave, admin, tmp_path):
    v = VentanaPrincipal(con_clave, admin)
    v.show()
    assert "backups" in v.modulos_visibles()
    assert v.aviso_backup.isVisible()
    v.ir_a("backups")
    assert v.tema_ayuda() == "backups"
    pantalla = v.pantalla_backups
    resultado = pantalla.backup_ahora()
    assert resultado.exitoso
    assert pantalla.tabla_copias.rowCount() == 1 and pantalla.tabla_historial.rowCount() == 1
    assert "Copia hecha y verificada" in pantalla.mensaje.text()
    # Queda solo el recordatorio semanal de llevar una copia fuera del local.
    assert "Recordatorio semanal" in v.texto_aviso_backup.text()
    disco = tmp_path / "disco"
    disco.mkdir()
    assert pantalla.copiar_a_otro_disco(str(disco)).exists()
    assert not v.aviso_backup.isVisible()
    v.close()


def test_pantalla_destino_verificar(qapp, con_clave, admin, tmp_path):
    p = PantallaBackups(con_clave, admin)
    assert "solo en este PC" in p.valores["destino"].text()
    usb = tmp_path / "usb"
    usb.mkdir()
    p.elegir_destino(str(usb))
    assert "(conectado)" in p.valores["destino"].text()
    p.backup_ahora()
    assert p.tabla_copias.rowCount() == 2  # una en el PC y otra en el USB
    assert p.verificar_seleccionada(CLAVE)
    assert "abre bien" in p.mensaje.text()
    assert "21:00" in p.valores["diaria"].text()


def test_dialogo_clave_exige_confirmar_que_la_guardo(qapp, servicios, admin):
    d = DialogoClaveBackups(servicios, admin)
    d.campo_clave.setText(CLAVE)
    d.campo_confirmar.setText(CLAVE)
    d.guardar()
    assert "lugar seguro" in d.error.text() and not servicios.backups.clave_configurada()
    d.casilla.setChecked(True)
    d.guardar()
    assert servicios.backups.clave_configurada()


def test_restaurar_desde_la_pantalla_cierra_la_sesion(qapp, con_clave, admin, sesion):
    v = VentanaPrincipal(con_clave, admin)
    v.ir_a("backups")
    pantalla = v.pantalla_backups
    pantalla.backup_ahora()
    copia = pantalla.copia_seleccionada()
    nuevo_cliente(sesion, 2)
    sesion.commit()

    d = DialogoRestaurar(con_clave, admin, copia, pantalla)
    d.campo_clave.setText("equivocada-123")
    d.casilla.setChecked(True)
    d.restaurar()
    assert "contraseña no es correcta" in d.error.text()
    d.campo_clave.setText(CLAVE)
    d.restaurar()
    assert d.result() == QtWidgets.QDialog.DialogCode.Accepted
    assert d.resumen.conteos["clientes"] == 1

    cerradas = []
    v.sesion_cerrada.connect(cerradas.append)
    pantalla.restaurado.emit()
    assert cerradas == [False] and "Se restauró" in v.aviso_cierre


def test_copia_diaria_en_segundo_plano_y_al_cerrar(qapp, con_clave, reloj, sesion):
    aplicacion = Aplicacion(qapp, con_clave)
    assert not aplicacion.revisar_copia_diaria()  # 10:00 de Bogotá: aún no es la hora
    reloj.avanzar(hours=11, minutes=30)
    assert aplicacion.revisar_copia_diaria()
    aplicacion.hilo_backup.wait()
    qapp.processEvents()
    assert aplicacion.hilo_backup is None and aplicacion.ultimo_resultado.exitoso
    assert not aplicacion.revisar_copia_diaria()

    resultado = aplicacion.copia_al_cerrar()
    assert resultado.exitoso
    tipos = [f.tipo for f in sesion.scalars(select(BackupLog))]
    assert tipos == ["automatico", "automatico"]


def test_copia_al_cerrar_sin_clave_queda_registrada(qapp, servicios, admin, sesion):
    aplicacion = Aplicacion(qapp, servicios)
    resultado = aplicacion.copia_al_cerrar()
    assert not resultado.exitoso
    [fila] = sesion.scalars(select(BackupLog)).all()
    assert fila.resultado == "fallido"


def test_recepcion_no_puede_backup_manual_aunque_llame_al_servicio(con_clave, recepcion):
    from gimnasio.servicios.errores import ErrorPermiso

    with pytest.raises(ErrorPermiso):
        con_clave.backups.preparar(recepcion, TIPO_MANUAL)
