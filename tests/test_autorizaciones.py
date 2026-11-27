"""Pagos, inscripciones, módulo de Pagos y módulo de Clientes solo con la clave de un
administrador, cada vez (decisión del dueño). Estas pruebas usan la clave de verdad."""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import select

from gimnasio.db.engine import crear_fabrica_sesiones
from gimnasio.modelos import Auditoria, Cliente, Membresia, Pago
from gimnasio.servicios.autorizaciones import (
    PARA_ACTIVACION, PARA_INSCRIPCION, PARA_MODULO_CLIENTES, PARA_MODULO_PAGOS, PARA_PAGO,
    ErrorAutorizacion,
)
from gimnasio.servicios.casilleros import CasilleroEnRecibo
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import DatosPago, FiltrosPagos
from tests.conftest import CLAVE_PRUEBA, dejar_saldo_antiguo
from tests.test_clientes import datos

pytestmark = pytest.mark.clave_admin_real


@pytest.fixture
def plan(servicios, admin):
    return servicios.planes.crear(admin, "Mensual", 30, 120_000)


@pytest.fixture
def cliente(servicios, admin):
    return servicios.clientes.registrar(admin, datos()).id


@pytest.fixture
def casillero(servicios, admin):
    return servicios.casilleros.crear(admin, "M-1", "mixto")


@pytest.fixture
def fabrica(motor):
    return crear_fabrica_sesiones(motor)


def clave(servicios, recepcion, para):
    return servicios.autorizaciones.autorizar(recepcion, "admin", CLAVE_PRUEBA, para)


def auditorias(fabrica, accion):
    with fabrica() as s:
        return [json.loads(a.detalle_json or "{}") for a in s.scalars(
            select(Auditoria).where(Auditoria.accion == accion).order_by(Auditoria.id))]


def contar(fabrica, modelo):
    with fabrica() as s:
        return len(list(s.scalars(select(modelo))))


def test_recepcion_sin_clave_no_cobra_ni_inscribe(servicios, recepcion, plan, cliente,
                                                  casillero, fabrica):
    pagos, cas = servicios.pagos, servicios.casilleros
    intentos = [
        lambda: pagos.registrar_membresia(recepcion, cliente, plan.id, pago=DatosPago(120_000)),
        lambda: pagos.registrar_membresia(recepcion, cliente, plan.id),  # ni sin pago
        lambda: pagos.registrar_pago(recepcion, cliente, DatosPago(5_000), concepto="otro"),
        lambda: cas.asignar(recepcion, casillero, cliente, pago=DatosPago(20_000)),
        lambda: cas.mensualidad_con_casillero(
            recepcion, cliente, plan.id, pago=DatosPago(120_000),
            casillero=CasilleroEnRecibo(monto=20_000, casillero_id=casillero)),
        lambda: servicios.clientes.registrar(recepcion, datos(documento="99887766")),
        lambda: pagos.cierre_caja(recepcion),
        lambda: pagos.consultar_pagos(recepcion, FiltrosPagos(cliente_id=cliente)),
    ]
    for intento in intentos:
        with pytest.raises(ErrorAutorizacion, match="contraseña de un administrador"):
            intento()
    assert contar(fabrica, Pago) == contar(fabrica, Membresia) == 0
    assert contar(fabrica, Cliente) == 1
    # Asignar un casillero sin cobrar no es un pago: no pide clave.
    assignado = cas.asignar(recepcion, casillero, cliente)
    with pytest.raises(ErrorAutorizacion):
        cas.renovar(recepcion, assignado.asignacion_id, pago=DatosPago(20_000))
    cas.renovar(recepcion, assignado.asignacion_id, dias=40)


def test_el_administrador_no_necesita_clave(servicios, admin, plan, cliente):
    r = servicios.pagos.registrar_membresia(admin, cliente, plan.id, pago=DatosPago(120_000))
    assert r.pago.recibo == "R-000001"
    assert servicios.pagos.cierre_caja(admin).total == 120_000


def test_clave_equivocada_o_de_recepcion_no_autoriza(servicios, admin, recepcion, fabrica):
    with pytest.raises(ErrorAutenticacion):
        servicios.autorizaciones.autorizar(recepcion, "admin", "equivocada", PARA_PAGO)
    with pytest.raises(ErrorPermiso, match="administrador activo"):
        servicios.autorizaciones.autorizar(recepcion, "rita", CLAVE_PRUEBA, PARA_PAGO)
    assert len(auditorias(fabrica, "autorizacion_fallida")) == 2
    assert auditorias(fabrica, "autorizacion_admin") == []


def test_cada_cobro_gasta_su_clave(servicios, recepcion, plan, cliente, fabrica):
    aut = clave(servicios, recepcion, PARA_PAGO)
    # Si falla por otro motivo la autorización sigue sirviendo.
    with pytest.raises(ErrorValidacion, match="referencia"):
        servicios.pagos.registrar_membresia(recepcion, cliente, plan.id, autorizacion=aut,
                                            pago=DatosPago(120_000, "tarjeta"))
    r = servicios.pagos.registrar_membresia(recepcion, cliente, plan.id, autorizacion=aut,
                                            pago=DatosPago(120_000))
    dejar_saldo_antiguo(fabrica, r.pago.id, 110_000)  # saldo de antes de quitar los abonos
    # Ya se usó: el pago siguiente pide la clave otra vez.
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(10_000),
                                       membresia_id=r.id, autorizacion=aut)
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(10_000), membresia_id=r.id,
                                   autorizacion=clave(servicios, recepcion, PARA_PAGO))
    # Queda quién autorizó cada operación.
    usos = auditorias(fabrica, "operacion_autorizada")
    assert [u["operacion"] for u in usos] == ["membresía", "pago"]
    assert {u["autorizado_por"] for u in usos} == {"admin"}
    assert [a["solicitado_por"] for a in auditorias(fabrica, "autorizacion_admin")] == [
        "rita", "rita"]


def test_inscripcion_sirve_para_inscribir_y_el_primer_cobro(servicios, recepcion, plan, casillero):
    aut = clave(servicios, recepcion, PARA_INSCRIPCION)
    nuevo = servicios.clientes.registrar(recepcion, datos(documento="99887766"), autorizacion=aut)
    # No sirve para un pago suelto, sí para la mensualidad (+ casillero) de la inscripción.
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.registrar_pago(recepcion, nuevo.id, DatosPago(1_000), concepto="otro",
                                       autorizacion=aut)
    r = servicios.casilleros.mensualidad_con_casillero(
        recepcion, nuevo.id, plan.id, pago=DatosPago(120_000), autorizacion=aut,
        casillero=CasilleroEnRecibo(monto=20_000, casillero_id=casillero))
    assert r.recibo == "R-000001"
    with pytest.raises(ErrorAutorizacion):  # dos usos y ya
        servicios.clientes.registrar(recepcion, datos(documento="55443322"), autorizacion=aut)


def test_clave_de_pago_no_sirve_para_inscribir_ni_para_otro_usuario(servicios, admin, recepcion,
                                                                    cliente):
    aut = clave(servicios, recepcion, PARA_PAGO)
    with pytest.raises(ErrorAutorizacion):
        servicios.clientes.registrar(recepcion, datos(documento="99887766"), autorizacion=aut)
    servicios.usuarios.crear(admin, "Otra Recepción", "otra", "recepcion", CLAVE_PRUEBA)
    otra = servicios.sesion.iniciar_sesion("otra", CLAVE_PRUEBA)
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.registrar_pago(otra, cliente, DatosPago(1_000), concepto="otro",
                                       autorizacion=aut)


def test_la_clave_vence(servicios, recepcion, cliente, reloj):
    aut = clave(servicios, recepcion, PARA_PAGO)
    reloj.avanzar(minutes=11)
    with pytest.raises(ErrorAutorizacion, match="venció"):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1_000), concepto="otro",
                                       autorizacion=aut)


def test_modulo_de_pagos_mientras_esta_abierto(servicios, recepcion, cliente):
    aut = clave(servicios, recepcion, PARA_MODULO_PAGOS)
    for _ in range(3):
        assert servicios.pagos.cierre_caja(recepcion, autorizacion=aut).total == 0
    servicios.pagos.consultar_pagos(recepcion, FiltrosPagos(cliente_id=cliente), autorizacion=aut)
    with pytest.raises(ErrorAutorizacion):  # abrir el módulo no autoriza cobrar
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1_000), concepto="otro",
                                       autorizacion=aut)
    servicios.autorizaciones.revocar(aut)  # al salir de la pantalla
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.cierre_caja(recepcion, autorizacion=aut)


# --- pantallas --------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_ventana_de_clave(qapp, servicios, recepcion):
    from gimnasio.ui.autorizacion import DialogoClaveAdmin

    d = DialogoClaveAdmin(servicios, recepcion, PARA_PAGO)
    d.campo_usuario.setText("admin")
    d.campo_clave.setText("mala")
    d.autorizar()
    assert d.autorizacion is None and "incorrectos" in d.error.text()
    assert d.campo_clave.text() == ""
    d.campo_clave.setText(CLAVE_PRUEBA)
    d.autorizar()
    assert d.autorizacion is not None and d.autorizacion.admin.usuario == "admin"


def test_admin_no_ve_la_ventana(qapp, servicios, admin, monkeypatch):
    import gimnasio.ui.autorizacion as ua

    monkeypatch.setattr(ua, "PEDIR", lambda *a: pytest.fail("no debía pedir la clave"))
    assert ua.pedir_autorizacion(None, servicios, admin, PARA_PAGO) == (True, None)


def test_cobro_de_recepcion_pide_la_clave(qapp, servicios, recepcion, plan, cliente, fabrica,
                                          monkeypatch):
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.pagos import DialogoMembresia

    pedidas = []

    def pedir(_padre, _servicios, actual, para):
        pedidas.append(para)
        if len(pedidas) == 1:
            return False, None  # canceló
        return True, servicios.autorizaciones.autorizar(actual, "admin", CLAVE_PRUEBA, para)

    monkeypatch.setattr(ua, "PEDIR", pedir)
    d = DialogoMembresia(servicios, recepcion, cliente)
    d.abrir = lambda _r: None
    d.guardar()
    assert d.resultado is None and contar(fabrica, Pago) == 0
    d.pago.metodo.setCurrentIndex(d.pago.metodo.findData("tarjeta"))
    d.guardar()  # pide la clave y falla por la referencia: no la vuelve a pedir
    assert "referencia" in d.error.text()
    d.pago.referencia.setText("APR-1")
    d.guardar()
    assert d.resultado.pago.recibo == "R-000001"
    assert pedidas == [PARA_PAGO, PARA_PAGO]


def test_pantalla_pagos_bloqueada_para_recepcion(qapp, servicios, recepcion, monkeypatch):
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.pagos import PantallaPagos

    respuesta = [False]
    monkeypatch.setattr(ua, "PEDIR", lambda _p, s, actual, para: (True, s.autorizaciones.autorizar(
        actual, "admin", CLAVE_PRUEBA, para)) if respuesta[0] else (False, None))
    p = PantallaPagos(servicios, recepcion)
    assert not p.desbloqueado and p.panel_bloqueado.isVisibleTo(p)
    assert not p.desbloquear() and p.cierre is None
    respuesta[0] = True
    assert p.desbloquear() and p.cierre is not None and p.pestanas.isVisibleTo(p)
    aut = p.autorizacion
    p.bloquear()  # al salir del módulo
    assert not p.desbloqueado and p.autorizacion is None
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.cierre_caja(recepcion, autorizacion=aut)


def test_inscripcion_pide_la_clave_una_sola_vez(qapp, servicios, recepcion, plan, monkeypatch):
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.cliente_formulario import DialogoCliente
    from gimnasio.ui.clientes import PantallaClientes
    from tests.test_ui_clientes import llenar

    pedidas = []

    def pedir(_padre, s, actual, para):
        pedidas.append(para)
        return True, s.autorizaciones.autorizar(actual, "admin", CLAVE_PRUEBA, para)

    monkeypatch.setattr(ua, "PEDIR", pedir)
    p = PantallaClientes(servicios, recepcion)
    vistos = []

    def ejecutar(dialogo):
        vistos.append(dialogo)
        if isinstance(dialogo, DialogoCliente):
            llenar(dialogo)
        else:
            dialogo.abrir = lambda _r: None
        dialogo.guardar()
        return dialogo.result()

    p._ejecutar = ejecutar
    p.nuevo()
    assert pedidas == [PARA_INSCRIPCION]
    assert vistos[1].resultado.pago.recibo == "R-000001"
    for d in vistos:
        d.setParent(None)
    vistos.clear()


def test_pagos_bloqueado_tambien_para_el_administrador(qapp, servicios, admin, monkeypatch):
    """Pagos no queda a la vista de cualquiera: el administrador también escribe la clave
    al entrar, y al salir se vuelve a bloquear."""
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.pagos import PantallaPagos

    pedidas = []
    respuesta = [False]

    def pedir(_p, s, actual, para):
        pedidas.append(para)
        if not respuesta[0]:
            return False, None
        return True, s.autorizaciones.autorizar(actual, "admin", CLAVE_PRUEBA, para)

    monkeypatch.setattr(ua, "PEDIR", pedir)
    p = PantallaPagos(servicios, admin)
    assert not p.desbloqueado and p.panel_bloqueado.isVisibleTo(p)
    assert not p.desbloquear() and p.cierre is None and pedidas == ["modulo_pagos"]
    respuesta[0] = True
    assert p.desbloquear() and p.cierre is not None
    p.bloquear()
    assert not p.desbloqueado and not p.pestanas.isVisibleTo(p)


def test_ficha_muestra_los_pagos_solo_con_clave(qapp, servicios, admin, recepcion, plan,
                                                monkeypatch):
    import gimnasio.ui.autorizacion as ua
    from gimnasio.servicios.clientes import DatosCliente
    from gimnasio.servicios.pagos import DatosPago
    from gimnasio.ui.cliente_ficha import DialogoFicha

    c = servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="9988776655", nombres="Luis", apellidos="Mora",
        sexo="M"))
    servicios.pagos.registrar_membresia(admin, c.id, plan.id, pago=DatosPago(plan.precio))
    for actual in (admin, recepcion):
        respuesta = [False]
        monkeypatch.setattr(ua, "PEDIR", lambda _p, s, a, para: (
            (True, s.autorizaciones.autorizar(a, "admin", CLAVE_PRUEBA, para))
            if respuesta[0] else (False, None)))
        f = DialogoFicha(servicios, actual, c.id)
        assert f._pila_pagos.currentWidget() is not f._pestana_pagos_real
        assert not f.desbloquear_pagos()
        respuesta[0] = True
        assert f.desbloquear_pagos()
        assert f._pila_pagos.currentWidget() is f._pestana_pagos_real
        f.cargar()  # tras registrar algo, sigue desbloqueada en esta ficha
        assert f._pila_pagos.currentWidget() is f._pestana_pagos_real
        f.close()


# --- módulo Clientes (datos confidenciales) -----------------------------------------

def test_lista_de_clientes_de_recepcion_necesita_la_clave(servicios, recepcion, cliente):
    """La regla está en el servicio, no solo en la pantalla."""
    for consulta in (lambda a: servicios.clientes.buscar(recepcion, autorizacion=a),
                     lambda a: servicios.clientes.resumen(recepcion, a)):
        with pytest.raises(ErrorAutorizacion, match="módulo de Clientes"):
            consulta(None)
        with pytest.raises(ErrorAutorizacion):  # la de otro módulo no sirve
            consulta(clave(servicios, recepcion, PARA_MODULO_PAGOS))
    aut = clave(servicios, recepcion, PARA_MODULO_CLIENTES)
    assert servicios.clientes.buscar(recepcion, autorizacion=aut).total == 1
    assert servicios.clientes.buscar(recepcion, autorizacion=aut).total == 1  # sin límite de usos
    assert servicios.clientes.resumen(recepcion, aut).total == 1
    servicios.autorizaciones.revocar(aut)
    with pytest.raises(ErrorAutorizacion):
        servicios.clientes.buscar(recepcion, autorizacion=aut)
    # Ver la ficha del cliente que pasa por Recepción (F4) y buscarlo no cambian.
    assert servicios.clientes.obtener_ficha(recepcion, cliente).id == cliente
    ficha = servicios.clientes.obtener_ficha(recepcion, cliente)
    assert [f.id for f in servicios.clientes.buscar_rapido(recepcion, ficha.codigo)] == [cliente]
    assert [f.id for f in servicios.clientes.buscar_rapido(recepcion, ficha.documento)] == [cliente]


@pytest.mark.parametrize("rol", ["admin", "recepcion"])
def test_clientes_bloqueado_tambien_para_el_administrador(qapp, servicios, admin, recepcion,
                                                         cliente, monkeypatch, rol):
    """Al entrar al módulo se pide la clave a todos; mientras tanto no se consulta ni se
    muestra nada, y al salir se vuelve a bloquear y se borra la lista."""
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.clientes import PantallaClientes

    actual = admin if rol == "admin" else recepcion
    pedidas = []
    respuesta = [False]

    def pedir(_p, s, a, para):
        pedidas.append(para)
        if not respuesta[0]:
            return False, None
        return True, s.autorizaciones.autorizar(a, "admin", CLAVE_PRUEBA, para)

    monkeypatch.setattr(ua, "PEDIR", pedir)
    p = PantallaClientes(servicios, actual)
    assert not p.desbloqueado and p.panel_bloqueado.isVisibleTo(p)
    assert not p.contenido.isVisibleTo(p) and p.modelo.rowCount() == 0
    assert all(b.text() == "" for b in p.botones_resumen.values())
    assert not p.desbloquear() and p.modelo.rowCount() == 0
    assert pedidas == [PARA_MODULO_CLIENTES]
    respuesta[0] = True
    assert p.desbloquear() and p.contenido.isVisibleTo(p)
    assert p.modelo.rowCount() == 1 and p.botones_resumen["total"].text() == "Total: 1"
    aut = p.autorizacion
    p.bloquear()  # al salir del módulo
    assert not p.desbloqueado and p.autorizacion is None and p.modelo.rowCount() == 0
    assert p.panel_bloqueado.isVisibleTo(p) and not p.contenido.isVisibleTo(p)
    p.recargar()  # p. ej. tras cerrar una ficha: sigue bloqueada
    assert p.modelo.rowCount() == 0
    if rol == "recepcion":
        with pytest.raises(ErrorAutorizacion):
            servicios.clientes.buscar(recepcion, autorizacion=aut)
    assert p.desbloquear() and pedidas.count(PARA_MODULO_CLIENTES) == 3  # otra vez la clave


def test_busqueda_ctrl_k_pide_la_clave(qapp, servicios, admin, cliente, monkeypatch):
    import gimnasio.ui.autorizacion as ua
    from gimnasio.ui.ventana_principal import VentanaPrincipal

    pedidas = []
    respuesta = [False]

    def pedir(_p, s, a, para):
        pedidas.append(para)
        if not respuesta[0]:
            return False, None
        return True, s.autorizaciones.autorizar(a, "admin", CLAVE_PRUEBA, para)

    monkeypatch.setattr(ua, "PEDIR", pedir)
    v = VentanaPrincipal(servicios, admin)
    abiertas = []
    monkeypatch.setattr(v, "abrir_ficha", abiertas.append)
    codigo = servicios.clientes.obtener_ficha(admin, cliente).codigo
    v.busqueda.setText(codigo)
    assert v.buscar() is None and abiertas == [] and pedidas == [PARA_MODULO_CLIENTES]
    respuesta[0] = True
    assert v.buscar() == cliente and abiertas == [cliente] and len(pedidas) == 2
    # Dentro del módulo Clientes ya desbloqueado no se vuelve a pedir.
    v.ir_a("clientes")
    assert v.pantalla_clientes.desbloquear()
    antes = len(pedidas)
    v.busqueda.setText(codigo)
    assert v.buscar() == cliente and len(pedidas) == antes
    v.close()


def test_recepcion_activa_cliente_inactivo_con_clave_y_cobra_con_la_misma(
    servicios, admin, recepcion, plan, cliente, fabrica
):
    servicios.clientes.inactivar(admin, cliente, "Retiro")
    with pytest.raises(ErrorAutorizacion):
        servicios.clientes.activar(recepcion, cliente)
    with pytest.raises(ErrorAutorizacion):  # la clave de un pago no sirve para activar
        servicios.clientes.activar(recepcion, cliente, clave(servicios, recepcion, PARA_PAGO))
    aut = clave(servicios, recepcion, PARA_ACTIVACION)
    servicios.clientes.activar(recepcion, cliente, aut)
    assert servicios.clientes.obtener_ficha(admin, cliente).activo
    # La misma clave sirve para cobrarle la mensualidad, y solo una vez.
    servicios.pagos.registrar_membresia(recepcion, cliente, plan.id, autorizacion=aut,
                                        pago=DatosPago(120_000))
    with pytest.raises(ErrorAutorizacion):
        servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(1_000), concepto="otro",
                                       autorizacion=aut)
    usos = auditorias(fabrica, "operacion_autorizada")
    assert [u["operacion"] for u in usos] == ["activación", "membresía"]
    assert auditorias(fabrica, "cliente_activado")[0]["codigo"]


def test_admin_activa_sin_clave(servicios, admin, cliente):
    servicios.clientes.inactivar(admin, cliente, "Retiro")
    servicios.clientes.activar(admin, cliente)
    assert servicios.clientes.obtener_ficha(admin, cliente).activo
