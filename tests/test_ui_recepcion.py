"""Pruebas de las pantallas de Recepción y Asistencia (Qt offscreen), con un lector USB
simulado: escribe el código tecla por tecla y presiona Enter."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gimnasio.servicios.clientes import DatosCliente  # noqa: E402
from gimnasio.servicios.pagos import DatosPago  # noqa: E402
from gimnasio.ui.asistencia import PantallaAsistencia  # noqa: E402
from gimnasio.ui.cliente_ficha import PESTANA_ALERTAS, DialogoAlerta, DialogoFicha  # noqa: E402
from gimnasio.ui.recepcion import DialogoAutorizacion, PantallaRecepcion  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402
from gimnasio.db.engine import crear_fabrica_sesiones  # noqa: E402
from tests.conftest import CLAVE_PRUEBA, dejar_saldo_antiguo  # noqa: E402

HOY = date(2026, 11, 26)


@pytest.fixture(scope="module")
def qapp():
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def ajustes_temporales(tmp_path):
    # El tamaño de letra de Recepción se guarda en QSettings: en las pruebas, en tmp.
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings("Enforma", "Gimnasio").clear()


@pytest.fixture
def plan(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


def nuevo_cliente(servicios, admin, n=1, **campos):
    datos = dict(tipo_documento="CC", documento=f"5060708{n:02d}", nombres="Carlos",
                 apellidos=f"Pérez {n}", sexo="M", telefonos=[f"31000000{n:02d}"])
    datos.update(campos)
    return servicios.clientes.registrar(admin, DatosCliente(**datos))


class Sonido:
    def __init__(self):
        self.veces = 0

    def __call__(self):
        self.veces += 1


@pytest.fixture
def pantalla(qapp, servicios, recepcion):
    p = PantallaRecepcion(servicios, recepcion)
    p.sonar = Sonido()
    p.show()
    qapp.processEvents()
    return p


def lector(qapp, pantalla, codigo: str) -> None:
    """Simula el lector USB: teclas rápidas en el campo enfocado y Enter."""
    assert qapp.focusWidget() is pantalla.campo
    QTest.keyClicks(qapp.focusWidget(), codigo)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Return)
    qapp.processEvents()


def test_lector_usb_tarjeta_verde_y_contador(qapp, pantalla, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    lector(qapp, pantalla, c.codigo)
    assert pantalla.tarjeta.color == "verde"
    assert "BIENVENIDO" in pantalla.tarjeta.titulo.text()
    assert pantalla.tarjeta.nombre.text() == "Carlos Pérez 1"
    assert pantalla.campo.text() == "" and qapp.focusWidget() is pantalla.campo
    assert pantalla.contador.text() == "Hoy: 1 asistentes"
    assert not hasattr(pantalla, "tabla")  # sin lista lateral de ingresos (está en Asistencia)
    assert pantalla.sonar.veces == 0
    # Renovar se ofrece también al cliente al día (puede pagar por adelantado).
    assert not pantalla.tarjeta.boton_renovar.isHidden()
    assert pantalla.tarjeta.boton_autorizar.isHidden()


def test_f2_renueva_por_adelantado_a_cliente_al_dia(qapp, pantalla, servicios, admin, plan,
                                                     monkeypatch):
    from gimnasio.ui.pagos import DialogoMembresia

    c = nuevo_cliente(servicios, admin)
    m = servicios.pagos.registrar_membresia(admin, c.id, plan.id,
                                            pago=DatosPago(120_000, "efectivo"))
    lector(qapp, pantalla, c.codigo)
    pantalla.abrir = lambda ruta: None

    def ejecutar(dialogo):
        dialogo.guardar()
        return dialogo.result()

    monkeypatch.setattr(DialogoMembresia, "exec", ejecutar)
    QTest.keyClick(pantalla.campo, Qt.Key.Key_F2)
    nuevo_fin = m.fecha_fin + timedelta(30)
    assert f"Vence el {nuevo_fin:%d/%m/%Y}" in pantalla.tarjeta.detalle.text()
    assert servicios.asistencia.resumen_del_dia(admin).asistentes == 1  # sin otro ingreso
    assert qapp.focusWidget() is pantalla.campo


def test_f2_sin_cliente_explica_que_hacer(qapp, pantalla):
    QTest.keyClick(pantalla.campo, Qt.Key.Key_F2)
    assert "F2" in pantalla.tarjeta.aviso.text() and not pantalla.tarjeta.aviso.isHidden()


def test_codigo_no_encontrado_suena(qapp, pantalla):
    lector(qapp, pantalla, "999999")
    assert pantalla.tarjeta.color == "rojo" and "NO ENCONTRADO" in pantalla.tarjeta.titulo.text()
    assert pantalla.sonar.veces == 1 and qapp.focusWidget() is pantalla.campo
    assert pantalla.tarjeta.boton_renovar.isHidden()


def test_amarillo_saldo_pendiente(qapp, pantalla, servicios, admin, plan, motor):
    c = nuevo_cliente(servicios, admin)
    m = servicios.pagos.registrar_membresia(admin, c.id, plan.id,
                                            pago=DatosPago(120_000, "efectivo"))
    dejar_saldo_antiguo(crear_fabrica_sesiones(motor), m.pago.id, 20_000)
    lector(qapp, pantalla, str(int(c.codigo)))  # sin ceros a la izquierda
    assert pantalla.tarjeta.color == "amarillo"
    assert "$ 100.000" in pantalla.tarjeta.mensaje.text()


def test_duplicado_enter_confirma_y_esc_cancela(qapp, pantalla, servicios, admin, plan, reloj):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    lector(qapp, pantalla, c.codigo)
    reloj.avanzar(minutes=30)
    lector(qapp, pantalla, c.codigo)
    assert "Ya ingresó hoy a las 10:00" in pantalla.tarjeta.aviso.text()
    assert pantalla.pendiente == c.id
    QTest.keyClick(pantalla.campo, Qt.Key.Key_Escape)
    assert pantalla.pendiente is None and "No se registró" in pantalla.tarjeta.aviso.text()
    assert servicios.asistencia.resumen_del_dia(admin).ingresos == 1
    lector(qapp, pantalla, c.codigo)
    lector(qapp, pantalla, "")  # Enter en el campo vacío confirma
    assert servicios.asistencia.resumen_del_dia(admin).ingresos == 2
    assert "Segundo ingreso" in pantalla.tarjeta.aviso.text()


def test_rojo_autorizar_con_f3(qapp, pantalla, servicios, admin, monkeypatch):
    c = nuevo_cliente(servicios, admin)
    lector(qapp, pantalla, c.codigo)
    assert pantalla.tarjeta.color == "rojo" and pantalla.sonar.veces == 1
    assert not pantalla.tarjeta.boton_autorizar.isHidden()
    vistos = []

    def ejecutar(dialogo):
        vistos.append(dialogo)
        dialogo.campo_usuario.setText("admin")
        dialogo.campo_clave.setText("mala")
        dialogo.autorizar()
        assert "incorrectos" in dialogo.error.text() and dialogo.campo_clave.text() == ""
        dialogo.campo_clave.setText(CLAVE_PRUEBA)
        dialogo.campo_motivo.setText("Paga el lunes")
        dialogo.autorizar()
        return dialogo.result()

    monkeypatch.setattr(DialogoAutorizacion, "exec", ejecutar)
    QTest.keyClick(pantalla.campo, Qt.Key.Key_F3)
    assert vistos and pantalla.tarjeta.color == "verde"
    assert "AUTORIZADO" in pantalla.tarjeta.titulo.text()
    assert pantalla.contador.text() == "Hoy: 1 asistentes"


def test_rojo_renovar_ahora_con_f2(qapp, pantalla, servicios, admin, plan, monkeypatch):
    from gimnasio.ui.pagos import DialogoMembresia

    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, fecha_inicio=HOY - timedelta(40),
                                        pago=DatosPago(120_000, "efectivo"))
    lector(qapp, pantalla, c.codigo)
    assert "VENCIDA" in pantalla.tarjeta.titulo.text()
    rutas = []
    pantalla.abrir = rutas.append

    def ejecutar(dialogo):
        dialogo.guardar()
        return dialogo.result()

    monkeypatch.setattr(DialogoMembresia, "exec", ejecutar)
    QTest.keyClick(pantalla.campo, Qt.Key.Key_F2)
    assert pantalla.tarjeta.color == "verde" and rutas  # recibo abierto para imprimir
    assert servicios.asistencia.resumen_del_dia(admin).asistentes == 1


def test_inactivo_no_ofrece_renovar(qapp, pantalla, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.clientes.inactivar(admin, c.id, "Retiro")
    lector(qapp, pantalla, c.codigo)
    assert "INACTIVO" in pantalla.tarjeta.titulo.text()
    assert pantalla.tarjeta.boton_renovar.isHidden()
    assert not pantalla.tarjeta.boton_autorizar.isHidden()
    assert not pantalla.tarjeta.boton_activar.isHidden()  # al lado de autorizar y ficha


def test_alertas_y_cumpleanos_en_la_tarjeta(qapp, pantalla, servicios, admin, plan, recepcion):
    c = nuevo_cliente(servicios, admin, fecha_nacimiento=date(2000, 11, 26))
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    servicios.alertas.crear(recepcion, c.id, "Falta firmar el consentimiento", "critica")
    lector(qapp, pantalla, c.codigo)
    assert "Falta firmar el consentimiento" in pantalla.tarjeta.alertas.text()
    assert "cumple años" in pantalla.tarjeta.extra.text()


def test_busqueda_manual_por_documento(qapp, pantalla, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    pantalla.buscar_manual(c.documento)
    assert pantalla.ultimo.tarjeta.cliente_id == c.id
    assert pantalla.contador.text() == "Hoy: 0 asistentes"  # sin membresía: rechazado


def test_tamano_de_letra(qapp, pantalla):
    QTest.keyClick(pantalla.campo, Qt.Key.Key_Plus, Qt.KeyboardModifier.ControlModifier)
    assert pantalla.escala == 1.1
    for _ in range(10):
        pantalla.cambiar_escala(0.1)
    assert pantalla.escala == 1.6
    pantalla.cambiar_escala(None)
    assert pantalla.escala == 1.0


def test_ficha_crea_y_resuelve_alertas(qapp, servicios, recepcion, admin, monkeypatch):
    c = nuevo_cliente(servicios, admin)
    ficha = DialogoFicha(servicios, recepcion, c.id)

    def ejecutar(dialogo):
        dialogo.guardar()
        assert "mensaje" in dialogo.error.text()
        dialogo.campo_mensaje.setText("Traer certificado médico")
        dialogo.campo_nivel.setCurrentIndex(dialogo.campo_nivel.findData("advertencia"))
        dialogo.guardar()
        return dialogo.result()

    monkeypatch.setattr(DialogoAlerta, "exec", ejecutar)
    ficha.nueva_alerta()
    assert ficha.pestanas.currentIndex() == PESTANA_ALERTAS
    assert ficha.tabla_alertas.item(0, 0).text() == "Traer certificado médico"
    ficha.resolver_alerta()
    assert ficha.tabla_alertas.item(0, 4).text() == "Resuelta"
    assert servicios.alertas.activas(recepcion, c.id) == []


def test_pantalla_asistencia_consulta_y_elimina(qapp, servicios, recepcion, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    servicios.asistencia.registrar_ingreso(recepcion, c.codigo)
    p = PantallaAsistencia(servicios, recepcion)
    reg = p.registros
    assert not reg.desde.isEnabled() and reg.eliminadas.isHidden()
    reg.consultar()
    assert reg.tabla.rowCount() == 1 and reg.tabla.item(0, 2).text() == c.codigo
    reg.tabla.selectRow(0)
    reg.pedir_motivo = lambda *a: "Registrado por error"
    reg.eliminar()
    assert reg.tabla.rowCount() == 0 and reg.total.text() == "0 registros"


def test_pantalla_reportes_exporta_e_imprime(qapp, servicios, admin, plan, tmp_path):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    servicios.asistencia.registrar_ingreso(admin, c.codigo)
    p = PantallaAsistencia(servicios, admin)
    rep = p.reportes
    rep.tipo.setCurrentIndex(rep.tipo.findData("ranking"))
    assert rep.limite.isVisible() or not rep.limite.isHidden()
    rep.generar()
    assert rep.tabla.columnCount() == 6 and rep.tabla.item(0, 1).text() == c.codigo
    rep.elegir_ruta = lambda sugerido, filtro: str(tmp_path / "ranking")
    destino = rep.exportar("xlsx")
    assert destino.name == "ranking.xlsx" and destino.exists()
    abiertos = []
    rep.abrir = abiertos.append
    rep.tipo.setCurrentIndex(rep.tipo.findData("dia"))
    assert rep.imprimir().suffix == ".pdf" and abiertos


def test_recepcion_solo_ve_reporte_del_dia(qapp, servicios, recepcion):
    p = PantallaAsistencia(servicios, recepcion)
    assert [p.reportes.tipo.itemData(i) for i in range(p.reportes.tipo.count())] == ["dia"]


def test_ventana_principal_recepcion_enfocada_y_pantalla_completa(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    v.show()
    qapp.processEvents()
    assert v.modulo_actual() == "recepcion"
    assert qapp.focusWidget() is v.pantalla_recepcion.campo
    v.alternar_pantalla_completa()
    assert v.navegacion.isHidden() and v.barra_superior.isHidden()
    v.ir_a("asistencia")
    assert not v.navegacion.isHidden()
    v.ir_a("recepcion")
    qapp.processEvents()
    assert qapp.focusWidget() is v.pantalla_recepcion.campo
    v.close()


# --- botones grandes y botón Activar (27/11/2026) -------------------------------------------

def test_botones_grandes_hacen_lo_mismo_que_las_teclas(qapp, pantalla, servicios, admin, plan,
                                                       monkeypatch):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    for b in (pantalla.boton_registrar, pantalla.boton_buscar, pantalla.boton_pantalla,
              pantalla.boton_letra_mas, pantalla.boton_letra_menos):
        assert b.focusPolicy() == Qt.FocusPolicy.NoFocus  # el lector sigue en el campo
    # Registrar: lo que esté escrito en el campo, como Enter.
    QTest.keyClicks(pantalla.campo, c.codigo)
    pantalla.boton_registrar.click()
    assert pantalla.tarjeta.color == "verde" and pantalla.contador.text() == "Hoy: 1 asistentes"
    assert qapp.focusWidget() is pantalla.campo
    # Buscar por nombre o cédula (F6).
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText",
                        lambda *a, **k: (c.documento, True))
    llamados = []
    monkeypatch.setattr(pantalla, "registrar_cliente", lambda cid, confirmar=False:
                        llamados.append(cid))
    pantalla.boton_buscar.click()
    assert llamados == [c.id]
    # Pantalla completa (F11) y tamaño de letra.
    señales = []
    pantalla.pantalla_completa.connect(lambda: señales.append(1))
    pantalla.boton_pantalla.click()
    assert señales == [1]
    pantalla.boton_letra_mas.click()
    assert pantalla.escala == 1.1
    pantalla.boton_letra_menos.click()
    pantalla.boton_letra_menos.click()
    assert pantalla.escala == 0.9


def test_cliente_activo_no_muestra_activar(qapp, pantalla, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    lector(qapp, pantalla, c.codigo)  # sin membresía: rojo, pero está activo
    assert pantalla.tarjeta.color == "rojo"
    assert pantalla.tarjeta.boton_activar.isHidden()
    assert not pantalla.tarjeta.boton_renovar.isHidden()


def test_activar_cliente_inactivo_y_cobrar(qapp, pantalla, servicios, admin, plan, monkeypatch):
    from gimnasio.ui.pagos import DialogoMembresia

    c = nuevo_cliente(servicios, admin)
    servicios.clientes.inactivar(admin, c.id, "Retiro")
    lector(qapp, pantalla, c.codigo)
    assert "INACTIVO" in pantalla.tarjeta.titulo.text()
    pantalla.abrir = lambda ruta: None
    abiertos = []

    def ejecutar(dialogo):
        abiertos.append(dialogo)
        dialogo.guardar()
        return dialogo.result()

    monkeypatch.setattr(DialogoMembresia, "exec", ejecutar)
    QTest.keyClick(pantalla.campo, Qt.Key.Key_F5)
    assert servicios.clientes.obtener_ficha(admin, c.id).activo
    assert len(abiertos) == 1 and abiertos[0].resultado.pago.monto == 120_000
    # Activado y pagado: entra (el intento rechazado se confirma).
    assert pantalla.tarjeta.color == "verde"
    assert servicios.asistencia.resumen_del_dia(admin).asistentes == 1
    assert pantalla.tarjeta.boton_activar.isHidden()
    assert qapp.focusWidget() is pantalla.campo


def test_activar_y_cancelar_el_cobro_deja_al_cliente_activo(qapp, pantalla, servicios, admin,
                                                            plan, monkeypatch):
    from gimnasio.ui.pagos import DialogoMembresia

    c = nuevo_cliente(servicios, admin)
    servicios.clientes.inactivar(admin, c.id, "Retiro")
    lector(qapp, pantalla, c.codigo)
    monkeypatch.setattr(DialogoMembresia, "exec", lambda dialogo: 0)
    pantalla.tarjeta.boton_activar.click()
    assert servicios.clientes.obtener_ficha(admin, c.id).activo
    assert pantalla.tarjeta.boton_activar.isHidden()
    assert not pantalla.tarjeta.boton_renovar.isHidden()  # puede cobrar después con F2
    assert "activado" in pantalla.tarjeta.aviso.text()
