"""Pantallas de casilleros (Qt offscreen): lista con filtros, asignar con pago y recibo,
renovar, liberar con motivo, mantenimiento, exportar, ficha del cliente y Recepción."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gimnasio.servicios.clientes import DatosCliente  # noqa: E402
from gimnasio.servicios.pagos import DatosPago  # noqa: E402
from gimnasio.ui.casilleros import (  # noqa: E402
    DialogoAsignarCasillero, DialogoCasillero, DialogoCrearVarios, DialogoHistorial,
    DialogoLiberarCasillero, DialogoRenovarCasillero, PantallaCasilleros,
)
from gimnasio.ui.cliente_ficha import PESTANA_CASILLERO, DialogoFicha  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402

HOY = date(2026, 11, 26)


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class Abridor:
    def __init__(self):
        self.rutas = []

    def __call__(self, ruta):
        self.rutas.append(ruta)


def nuevo_cliente(servicios, admin, n, sexo):
    return servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento=f"7080900{n:03d}", nombres="Carlos" if sexo == "M"
        else "Marta", apellidos=f"Pérez {n}", sexo=sexo, telefonos=[f"32012345{n:02d}"],
        fecha_nacimiento=date(1990, 1, 1))).id


@pytest.fixture
def catalogo(servicios, admin):
    servicios.casilleros.crear_rango(admin, 1, 2, "hombres")
    servicios.casilleros.crear_rango(admin, 3, 4, "mujeres")
    servicios.configuracion.guardar(admin, {"casillero_precio": 20_000})
    return {n: i for i, n, _ in servicios.casilleros.libres(admin)}


def fila_de(pantalla, numero):
    pantalla.seleccionar(numero)
    return pantalla.seleccionado()


def test_pantalla_lista_filtra_y_asigna_buscando_cliente(qapp, servicios, recepcion, admin,
                                                        catalogo):
    marta = nuevo_cliente(servicios, admin, 1, "F")
    p = PantallaCasilleros(servicios, recepcion).casilleros
    p.abrir = abridor = Abridor()
    p.actualizar()
    assert p.tabla.rowCount() == 4 and p.totales["disponibles"].text() == "4"
    assert p.boton_nuevo is None  # recepción no administra el catálogo

    def ejecutar(d):
        assert isinstance(d, DialogoAsignarCasillero)
        assert d.periodo.pago.monto.value() == 20_000 and d.periodo.cobrar.isChecked()
        d.campo_cliente.setText("Marta")
        assert d.buscar_cliente() == marta
        d.guardar()
        return d.result() == QtWidgets.QDialog.DialogCode.Accepted

    p.ejecutar = ejecutar
    assert fila_de(p, "003") is not None and p.boton_asignar.isEnabled()
    assert p.asignar()
    f = p.seleccionado()
    assert f.numero == "003" and f.cliente_id == marta and f.vence == date(2026, 12, 25)
    assert abridor.rutas and abridor.rutas[0].suffix == ".pdf"  # recibo del casillero
    assert p.boton_renovar.isEnabled() and not p.boton_asignar.isEnabled()
    p.estado.setCurrentIndex(p.estado.findData("ocupado"))
    assert p.tabla.rowCount() == 1
    p.estado.setCurrentIndex(0)
    p.sexo.setCurrentIndex(p.sexo.findData("M"))
    assert p.tabla.rowCount() == 0


def test_asignar_en_zona_de_otro_sexo_muestra_error(qapp, servicios, recepcion, admin, catalogo):
    carlos = nuevo_cliente(servicios, admin, 2, "M")
    d = DialogoAsignarCasillero(servicios, recepcion, casillero_id=catalogo["003"],
                                numero="003", zona="mujeres")
    d.campo_cliente.setText("Carlos")
    d.buscar_cliente()
    d.periodo.cobrar.setChecked(False)
    d.guardar()
    assert d.resultado is None and "zona mujeres" in d.error.text()
    assert carlos


def test_renovar_y_liberar_desde_la_pantalla(qapp, servicios, recepcion, admin, catalogo):
    marta = nuevo_cliente(servicios, admin, 1, "F")
    servicios.casilleros.asignar(admin, catalogo["004"], marta, dias=30)
    p = PantallaCasilleros(servicios, recepcion).casilleros
    p.abrir = Abridor()
    p.actualizar()

    def renovar(d):
        assert isinstance(d, DialogoRenovarCasillero)
        assert d.periodo.leer_inicio() == date(2026, 12, 26)
        d.periodo.cobrar.setChecked(False)
        d.guardar()
        return d.resultado is not None

    p.ejecutar = renovar
    fila_de(p, "004")
    assert p.renovar() and p.seleccionado().vence == date(2027, 1, 24)

    def liberar(d):
        assert isinstance(d, DialogoLiberarCasillero)
        d.campo_motivo.setCurrentIndex(3)  # «Otro» sin detalle: se exige el motivo
        d.guardar()
        assert "motivo" in d.error.text()
        d.campo_motivo.setCurrentIndex(1)
        d.campo_detalle.setText("se cambió de sede")
        d.guardar()
        return d.result() == QtWidgets.QDialog.DialogCode.Accepted

    p.ejecutar = liberar
    assert p.liberar()
    assert not p.seleccionado().ocupado
    hist = servicios.casilleros.historial(admin, catalogo["004"])
    assert hist[0].motivo == "El cliente ya no lo quiere usar: se cambió de sede"
    d = DialogoHistorial(servicios, recepcion, catalogo["004"], "004")
    assert d.tabla.rowCount() == 1


def test_admin_crea_edita_y_pone_en_mantenimiento(qapp, servicios, admin, catalogo, tmp_path):
    p = PantallaCasilleros(servicios, admin).casilleros
    p.actualizar()

    def crear(d):
        if isinstance(d, DialogoCrearVarios):
            d.desde.setValue(10)
            d.hasta.setValue(12)
            d.campo_zona.setCurrentIndex(d.campo_zona.findData("mixto"))
        elif isinstance(d, DialogoCasillero):
            d.campo_numero.setText("A-1")
        d.guardar()
        return d.result() == QtWidgets.QDialog.DialogCode.Accepted

    p.ejecutar = crear
    assert p.crear_varios() and p.nuevo()
    assert p.tabla.rowCount() == 8 and p.totales["total"].text() == "8"
    fila_de(p, "010")
    assert p.alternar_mantenimiento("Chapa dañada")
    assert p.seleccionado().estado == "mantenimiento" and p.boton_mantenimiento.text() == "Habilitar"
    assert not p.boton_asignar.isEnabled()
    assert p.alternar_mantenimiento()
    assert p.seleccionado().estado == "disponible"
    # Exportar la lista
    p.elegir_ruta = lambda sugerido, filtro: str(tmp_path / "lista")
    assert p.exportar("xlsx").name == "lista.xlsx"


def test_movimientos_del_dia(qapp, servicios, recepcion, admin, catalogo, tmp_path):
    marta = nuevo_cliente(servicios, admin, 1, "F")
    servicios.casilleros.asignar(recepcion, catalogo["003"], marta)
    pantalla = PantallaCasilleros(servicios, recepcion)
    m = pantalla.movimientos
    m.poner_dia(HOY)
    m.actualizar()
    assert m.tabla.rowCount() == 1 and m.tabla.item(0, 1).text() == "Asignado"
    assert "1 asignados" in m.resumen.text()
    m.abrir = abridor = Abridor()
    assert m.imprimir() is not None and abridor.rutas


def test_ficha_asigna_y_libera_casillero(qapp, servicios, recepcion, admin, catalogo):
    marta = nuevo_cliente(servicios, admin, 1, "F")
    f = DialogoFicha(servicios, recepcion, marta)
    f.abrir = Abridor()
    assert f.boton_asignar_casillero.isEnabled() and not f.boton_liberar_casillero.isEnabled()

    def asignar(d):
        # Solo se ofrecen los casilleros de su zona (mujeres).
        numeros = [d.campo_casillero.itemText(i)[:3] for i in range(d.campo_casillero.count())]
        assert numeros == ["003", "004"]
        d.periodo.pago.monto.setValue(15_000)
        d.guardar()
        return d.resultado is not None

    f.ejecutar = asignar
    assert f.asignar_casillero()
    assert f.pestanas.currentIndex() == PESTANA_CASILLERO
    assert "Casillero 003 pagado hasta el 25/12/2026" in f.etiqueta_casillero.text()
    assert f.boton_liberar_casillero.isEnabled()
    pagos = servicios.clientes.obtener_ficha(admin, marta).pagos
    assert pagos[0].concepto == "casillero" and pagos[0].monto == 15_000

    def liberar(d):
        d.guardar()
        return d.result() == QtWidgets.QDialog.DialogCode.Accepted

    f.ejecutar = liberar
    assert f.liberar_casillero()
    assert f.etiqueta_casillero.text() == "No tiene casillero asignado."


def test_recepcion_muestra_casillero_vencido(qapp, servicios, recepcion, admin, catalogo):
    from datetime import timedelta

    from gimnasio.ui.recepcion import PantallaRecepcion

    marta = nuevo_cliente(servicios, admin, 1, "F")
    plan = servicios.planes.crear(admin, "Mensual", 30, 100_000)
    servicios.pagos.registrar_membresia(admin, marta, plan.id, pago=DatosPago(100_000))
    servicios.casilleros.asignar(admin, catalogo["004"], marta,
                                 fecha_inicio=HOY - timedelta(days=50), dias=30)
    r = PantallaRecepcion(servicios, recepcion)
    codigo = servicios.clientes.obtener_ficha(admin, marta).codigo
    r.campo.setText(codigo)
    r.procesar()
    texto = r.tarjeta.extra.text()
    assert "Casillero 004 vencido hace 21 días" in texto and "sugerido liberar" in texto
    assert "CASILLERO VENCIDO" in r.tarjeta.titulo.text()


def test_menu_tiene_casilleros(qapp, servicios, recepcion):
    v = VentanaPrincipal(servicios, recepcion)
    try:
        assert "casilleros" in v.modulos_visibles()
        assert isinstance(v.pantalla_casilleros, PantallaCasilleros)
    finally:
        v.close()
