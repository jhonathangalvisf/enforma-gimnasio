"""Arreglos tras probar el instalador en un portátil: ventanas que caben en pantallas
pequeñas (o con escalado de Windows), cobro de la mensualidad desde la ficha y planes
sin precio."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.servicios.clientes import DatosCliente  # noqa: E402
from gimnasio.ui.cliente_ficha import DialogoFicha  # noqa: E402
from gimnasio.ui.comunes import ajustar_a_pantalla  # noqa: E402
from gimnasio.ui.pagos import DialogoMembresia, DialogoPago  # noqa: E402
from gimnasio.ui.recepcion import PantallaRecepcion  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def cliente(servicios, admin):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="7080901020", nombres="Tomás", apellidos="Quintero",
        sexo="M", telefonos=["3009998877"])).id


def test_ventana_principal_cabe_en_un_portatil(qapp, servicios, admin):
    """Con todos los módulos (administrador), la ventana puede achicarse hasta caber en un
    portátil: lo que no cabe en una pantalla se desplaza en lugar de quedar cortado."""
    v = VentanaPrincipal(servicios, admin)
    v.show()
    qapp.processEvents()
    minimo = v.minimumSizeHint()
    # 1366 × 768 con escalado de Windows al 125 % deja 1093 × 614 (menos la barra de tareas).
    partes = {nombre: getattr(v, nombre).minimumSizeHint().toTuple()
              for nombre in ("barra_superior", "aviso_backup", "navegacion", "pantallas")}
    partes["estado"] = v.statusBar().minimumSizeHint().toTuple()
    partes["en la barra"] = [(type(w).__name__, w.minimumSizeHint().width(), w.minimumWidth())
                             for w in v.barra_superior.findChildren(QtWidgets.QWidget)]
    assert minimo.width() <= 1093 and minimo.height() <= 560, (minimo, partes)
    for clave in v.modulos_visibles():
        v.ir_a(clave)
        assert not isinstance(v.pantallas.currentWidget(), QtWidgets.QScrollArea)
    v._detener()
    v.close()


def test_recepcion_se_angosta(qapp, servicios, recepcion):
    p = PantallaRecepcion(servicios, recepcion)
    # Junto al menú lateral (210 px) debe caber en 1093 px de ancho.
    assert p.minimumSizeHint().width() <= 1093 - 210, p.minimumSizeHint()


def test_dialogo_grande_se_ajusta_a_la_pantalla(qapp):
    d = QtWidgets.QDialog()
    d.setMinimumSize(5000, 4000)
    d.show()
    ajustar_a_pantalla(d)
    area = d.screen().availableGeometry()
    assert d.width() <= area.width() and d.height() <= area.height()
    assert area.contains(d.frameGeometry().topLeft())
    d.close()


def test_ficha_ofrece_pagar_mensualidad(qapp, servicios, admin, cliente, monkeypatch):
    plan = servicios.planes.crear(admin, "Mensual", 30, 70_000)
    abiertos = []

    def ejecutar(dialogo):
        abiertos.append(dialogo)
        dialogo.abrir_recibo.setChecked(False)
        dialogo.guardar()
        return dialogo.result()

    monkeypatch.setattr(DialogoMembresia, "exec", ejecutar)
    ficha = DialogoFicha(servicios, admin, cliente)
    assert ficha.boton_mensualidad.isEnabled()
    assert "no es mensualidad" in ficha.boton_pago.text()
    ficha.boton_mensualidad.click()
    assert abiertos and abiertos[0].plan_elegido().id == plan.id
    membresias = servicios.clientes.obtener_ficha(admin, cliente).membresias
    assert len(membresias) == 1 and membresias[0].plan == "Mensual"
    ficha.close()


def test_pago_de_otro_concepto_avisa_que_no_cambia_la_vigencia(qapp, servicios, admin, cliente):
    d = DialogoPago(servicios, admin, cliente, nombre_cliente="Tomás Quintero")
    textos = [w.text() for w in d.findChildren(QtWidgets.QLabel)]
    assert any("NO cambia la vigencia" in t for t in textos)
    d.close()


def test_plan_sin_precio_no_se_vende(qapp, servicios, admin, cliente):
    servicios.planes.crear(admin, "Cortesía", 30, 0)
    d = DialogoMembresia(servicios, admin, cliente, "Tomás Quintero")
    assert "todavía no tiene precio" in d.error.text() and not d.error.isHidden()
    d.guardar()
    assert d.result() == 0
    assert servicios.clientes.obtener_ficha(admin, cliente).membresias == []
    d.close()


def test_planes_del_gimnasio_a_1_peso_se_pueden_cobrar(qapp, servicios, admin, cliente):
    """Decisión del gimnasio: los planes valen $1; lo que importa es qué plan eligió."""
    servicios.planes.crear_planes_ejemplo()
    d = DialogoMembresia(servicios, admin, cliente, "Tomás Quintero")
    assert d.campo_plan.count() == 6
    semestre = next(p for p in servicios.planes.listar(admin) if p.nombre == "Semestre")
    d.campo_plan.setCurrentIndex(d.campo_plan.findData(semestre.id))
    assert d.error.isHidden()
    d.abrir_recibo.setChecked(False)
    d.guardar()
    assert d.result() == 1 and d.resultado.pago.monto == 1
    m = servicios.clientes.obtener_ficha(admin, cliente).membresias[0]
    assert m.plan == "Semestre" and (m.fecha_fin - m.fecha_inicio).days == 179
    d.close()


def test_sin_planes_el_aviso_dice_donde_crearlos(qapp, servicios, admin, cliente):
    d = DialogoMembresia(servicios, admin, cliente, "Tomás Quintero")
    assert "Configuración → Planes" in d.avisos.text()
    d.guardar()
    assert "Configuración → Planes" in d.error.text()
    d.close()


def test_pagar_mensualidad_con_plan_con_precio(qapp, servicios, admin, cliente):
    servicios.planes.crear_planes_ejemplo()
    mensual = next(p for p in servicios.planes.listar(admin) if p.nombre == "Mensual")
    servicios.planes.editar(admin, mensual.id, "Mensual", 30, 70_000)
    d = DialogoMembresia(servicios, admin, cliente, "Tomás Quintero")
    d.campo_plan.setCurrentIndex(d.campo_plan.findData(mensual.id))
    assert d.error.isHidden()
    d.abrir_recibo.setChecked(False)
    d.guardar()
    assert d.result() == 1 and d.resultado.pago.monto == 70_000
    d.close()


def _anchos(pantalla):
    """Para el mensaje de error: qué controles piden más ancho."""
    return sorted(((w.minimumSizeHint().width(), type(w).__name__, w.objectName(),
                    getattr(w, "text", lambda: "")() if hasattr(w, "text") else "")
                   for w in pantalla.findChildren(QtWidgets.QWidget)
                   if w.minimumSizeHint().width() > 150), reverse=True)[:15]


def test_ningun_modulo_queda_cortado_en_un_portatil(qapp, servicios, admin):
    """1366 × 768 con escalado al 125 %: cada módulo (y cada pestaña) cabe en el espacio
    que deja el menú, sin barra horizontal; los botones del final se ven."""
    v = VentanaPrincipal(servicios, admin)
    v.resize(1093, 614)
    v.show()
    qapp.processEvents()
    for clave in v.modulos_visibles():
        v.ir_a(clave)
        qapp.processEvents()
        pantalla = v.pantallas.currentWidget()
        area = v.pantallas.currentWidget().parentWidget().parentWidget()
        assert isinstance(area, QtWidgets.QScrollArea)
        visible = area.viewport().size()
        assert pantalla.minimumSizeHint().width() <= 1093 - 210, (
            clave, pantalla.minimumSizeHint(), _anchos(pantalla))
        # La pantalla ocupa exactamente lo visible: nada queda escondido a la derecha.
        assert pantalla.width() == visible.width(), (clave, pantalla.size(), visible)
        assert not area.horizontalScrollBar().isVisible(), clave
    v._detener()
    v.close()


def test_area_crece_solo_si_la_pantalla_no_cabe(qapp):
    from gimnasio.ui.comunes import AreaPantalla

    pantalla = QtWidgets.QWidget()
    pantalla.setMinimumSize(700, 500)
    area = AreaPantalla(pantalla)
    area.resize(400, 300)
    area.show()
    qapp.processEvents()
    assert pantalla.width() >= 700 and pantalla.height() >= 500  # aparecen las barras
    area.resize(1200, 900)
    qapp.processEvents()
    assert pantalla.size() == area.viewport().size()  # cabe: ocupa todo lo visible
    area.close()
