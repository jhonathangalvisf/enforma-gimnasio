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
from tests.conftest import CLAVE_PRUEBA  # noqa: E402

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
    assert pantalla.tabla.rowCount() == 1 and pantalla.tabla.item(0, 1).text() == c.codigo
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


def test_amarillo_saldo_pendiente(qapp, pantalla, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(20_000, "efectivo"))
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
    assert pantalla.tabla.rowCount() == 1


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


def test_pantalla_asistencia_no_carga_nada_al_abrir(qapp, servicios, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    servicios.asistencia.registrar_ingreso(admin, c.codigo)
    p = PantallaAsistencia(servicios, admin)
    p.show()
    for i in range(p.pestanas.count()):
        p.pestanas.setCurrentIndex(i)
        qapp.processEvents()
    assert [p.pestanas.tabText(i) for i in range(p.pestanas.count())] == [
        "Registrar ingreso", "Historial del cliente", "Reportes del cliente"]
    assert p.registros.tabla.rowCount() == 0
    assert p.reportes.reporte_actual is None and p.reportes.tabla.rowCount() == 0
    assert p.ingreso.tabla.parentWidget().isHidden()  # sin listado de ingresos del día
    p.close()


def test_asistencia_registra_ingreso_por_codigo(qapp, servicios, recepcion, admin, plan):
    c = nuevo_cliente(servicios, admin)
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(120_000, "efectivo"))
    sin_plan = nuevo_cliente(servicios, admin, n=2)
    p = PantallaAsistencia(servicios, recepcion)
    ing = p.ingreso
    ing.sonar = Sonido()
    ing.campo.setText(c.codigo)
    ing.procesar()
    assert ing.ultimo.estado == "registrado" and ing.ultimo.tarjeta.permite_ingreso
    assert ing.tabla.rowCount() == 0  # no se llena la lista del día
    # Segundo ingreso del día: avisa y pide confirmación (Enter registra, Esc cancela).
    ing.campo.setText(c.codigo)
    ing.procesar()
    assert ing.pendiente == c.id and "Ya ingresó hoy" in ing.tarjeta.aviso.text()
    ing.cancelar()
    assert ing.pendiente is None
    assert servicios.asistencia.resumen_del_dia(recepcion).ingresos == 1
    ing.campo.setText(c.codigo)
    ing.procesar()
    ing.procesar()  # Enter con el campo vacío confirma
    assert servicios.asistencia.resumen_del_dia(recepcion).ingresos == 2
    # Sin membresía: rojo, con sonido y botón Autorizar.
    ing.campo.setText(sin_plan.codigo)
    ing.procesar()
    assert ing.ultimo.estado == "rechazado" and ing.sonar.veces == 1
    assert not ing.tarjeta.boton_autorizar.isHidden()


def test_historial_del_cliente_consulta_y_elimina(qapp, servicios, recepcion, admin, plan):
    c = nuevo_cliente(servicios, admin)
    otro = nuevo_cliente(servicios, admin, n=2)
    for cliente in (c, otro):
        servicios.pagos.registrar_membresia(admin, cliente.id, plan.id,
                                            pago=DatosPago(120_000, "efectivo"))
        servicios.asistencia.registrar_ingreso(recepcion, cliente.codigo)
    p = PantallaAsistencia(servicios, recepcion)
    reg = p.registros
    assert not reg.todo.isEnabled() and reg.eliminadas.isHidden()
    errores = []
    import gimnasio.ui.asistencia as modulo
    original = modulo.mostrar_error
    modulo.mostrar_error = lambda padre, e: errores.append(str(e))
    try:
        reg.consultar()  # sin código: pide el código, no lista a todos
    finally:
        modulo.mostrar_error = original
    assert errores == ["Escriba el código del cliente."] and reg.tabla.rowCount() == 0
    reg.codigo.setText(c.codigo)
    reg.consultar()
    assert reg.tabla.rowCount() == 1 and reg.tabla.item(0, 2).text() == c.codigo
    reg.tabla.selectRow(0)
    reg.pedir_motivo = lambda *a: "Registrado por error"
    reg.eliminar()
    assert reg.tabla.rowCount() == 0 and reg.total.text() == "0 registros"


def test_reporte_del_cliente_exporta_e_imprime(qapp, servicios, admin, recepcion, plan, tmp_path):
    c = nuevo_cliente(servicios, admin)
    otro = nuevo_cliente(servicios, admin, n=2)
    for cliente in (c, otro):
        servicios.pagos.registrar_membresia(admin, cliente.id, plan.id,
                                            pago=DatosPago(120_000, "efectivo"))
        servicios.asistencia.registrar_ingreso(admin, cliente.codigo)
    p = PantallaAsistencia(servicios, admin)
    rep = p.reportes
    rep.codigo.setText(c.codigo)
    r = rep.generar()
    assert r.tipo == "cliente" and rep.tabla.rowCount() == 1
    assert rep.tabla.item(0, 2).text() == c.codigo and "todo el historial" in r.subtitulo
    rep.todo.setChecked(False)
    assert rep.desde.isEnabled()
    rep.elegir_ruta = lambda sugerido, filtro: str(tmp_path / "cliente")
    destino = rep.exportar("xlsx")
    assert destino.name == "cliente.xlsx" and destino.exists()
    abiertos = []
    rep.abrir = abiertos.append
    assert rep.imprimir().suffix == ".pdf" and abiertos
    # Recepción también saca el reporte de un cliente (todo su historial).
    pantalla_r = PantallaAsistencia(servicios, recepcion)
    rep_r = pantalla_r.reportes
    assert not rep_r.todo.isEnabled()
    rep_r.codigo.setText(otro.codigo)
    assert rep_r.generar().filas[0][2] == otro.codigo


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
