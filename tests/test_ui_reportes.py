"""Pantalla de Reportes (Qt offscreen): lista según el rol, filtros por reporte, fechas
bloqueadas para Recepción, vista previa con totales, exportar e imprimir."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402

from gimnasio.servicios.clientes import DatosCliente  # noqa: E402
from gimnasio.servicios.pagos import DatosPago  # noqa: E402
from gimnasio.ui import reportes as modulo  # noqa: E402
from gimnasio.ui.reportes import PantallaReportes  # noqa: E402
from gimnasio.ui.ventana_principal import VentanaPrincipal  # noqa: E402

HOY = date(2026, 11, 26)


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def sin_mensajes(monkeypatch):
    errores = []
    monkeypatch.setattr(modulo, "mostrar_error", lambda _p, e: errores.append(str(e)))
    return errores


@pytest.fixture
def datos(servicios, admin, recepcion):
    plan = servicios.planes.crear(admin, "Mensual", 30, 120_000).id
    cliente = servicios.clientes.registrar(admin, DatosCliente(
        tipo_documento="CC", documento="1020304050", nombres="Laura", apellidos="Ríos",
        sexo="F", telefonos=["3001234567"])).id
    servicios.pagos.registrar_membresia(admin, cliente, plan, fecha_inicio=date(2026, 11, 1),
                                        pago=DatosPago(120_000))
    servicios.pagos.registrar_pago(recepcion, cliente, DatosPago(20_000), concepto="otro")
    return cliente


def _claves(pantalla):
    claves = []
    for i in range(pantalla.lista.topLevelItemCount()):
        grupo = pantalla.lista.topLevelItem(i)
        for j in range(grupo.childCount()):
            claves.append(grupo.child(j).data(0, Qt.ItemDataRole.UserRole))
    return claves


def test_recepcion_ve_solo_basicos_y_fechas_de_hoy(qapp, servicios, recepcion, datos):
    pantalla = PantallaReportes(servicios, recepcion)
    claves = _claves(pantalla)
    assert "ingresos_metodo" not in claves and "clientes_morosos" not in claves
    # El cierre de caja de Recepción está en el módulo Pagos (con clave de administrador).
    assert "clientes_por_vencer" in claves and "cierre_caja" not in claves
    pantalla.elegir("asistencia_dia")
    assert not pantalla.dia.isEnabled()
    assert pantalla.generar() is not None

    pantalla.elegir("clientes_por_vencer")
    assert pantalla.dias.isVisibleTo(pantalla) and not pantalla.metodo.isVisibleTo(pantalla)
    assert pantalla.dias.value() == 5  # parámetro "por vencer"
    rep = pantalla.generar()
    assert pantalla.tabla.rowCount() == 1
    assert pantalla.tabla.item(0, rep.encabezados.index("Teléfono")).text() == "3001234567"


def test_admin_genera_ingresos_y_exporta(qapp, servicios, admin, datos, tmp_path):
    pantalla = PantallaReportes(servicios, admin)
    assert len(_claves(pantalla)) == len(servicios.reportes.disponibles(admin))
    pantalla.elegir("ingresos_usuario")
    assert pantalla.periodo.isVisibleTo(pantalla) and pantalla.metodo.isVisibleTo(pantalla)
    assert not pantalla.boton_excel.isEnabled()  # primero la vista previa
    rep = pantalla.generar()
    assert [f[0] for f in rep.filas] == ["admin", "rita"]
    columna_total = rep.encabezados.index("Total")
    assert pantalla.tabla.item(0, columna_total).text() == "$ 120.000"
    assert "Total: $ 140.000" in pantalla.etiqueta_totales.text()
    assert pantalla.boton_excel.isEnabled()

    pantalla.elegir_ruta = lambda sugerido, _f: str(tmp_path / "ingresos")
    destino = pantalla.exportar("xlsx")
    assert destino == tmp_path / "ingresos.xlsx" and destino.exists()
    abiertos = []
    pantalla.abrir = abiertos.append
    impreso = pantalla.imprimir()
    assert impreso.suffix == ".pdf" and abiertos == [impreso]


def test_periodo_rapido_y_validacion(qapp, servicios, admin, datos, sin_mensajes):
    pantalla = PantallaReportes(servicios, admin)
    pantalla.elegir("clientes_mensual")
    assert modulo.leer_fecha(pantalla.desde) == date(2025, 12, 1)
    pantalla.periodo.setCurrentIndex(modulo.PERIODOS.index("Mes anterior"))
    assert modulo.leer_fecha(pantalla.desde) == date(2026, 10, 1)
    assert modulo.leer_fecha(pantalla.hasta) == date(2026, 10, 31)
    pantalla.desde.setDate(date(2026, 11, 20))
    assert pantalla.periodo.currentData() == "Personalizado"
    pantalla.hasta.setDate(date(2026, 11, 1))
    assert pantalla.generar() is None and "posterior" in sin_mensajes[-1]

    pantalla.elegir("asistencia_cliente")
    assert pantalla.generar() is None and "código" in sin_mensajes[-1]
    pantalla.codigo.setText("1")
    assert pantalla.generar() is not None


def test_vista_previa_limitada(qapp, servicios, admin, monkeypatch):
    monkeypatch.setattr(modulo, "LIMITE_VISTA_PREVIA", 2)
    for i in range(3):
        servicios.clientes.registrar(admin, DatosCliente(
            tipo_documento="CC", documento=f"55500{i}", nombres=f"Nombre{i}", apellidos="Apellido",
            sexo="M"))
    pantalla = PantallaReportes(servicios, admin)
    pantalla.elegir("clientes_nuevos")
    rep = pantalla.generar()
    assert len(rep.filas) == 3 and pantalla.tabla.rowCount() == 2
    assert "primeras 2 de 3" in pantalla.subtitulo.text()


def test_ventana_principal_abre_reportes(qapp, servicios, recepcion):
    ventana = VentanaPrincipal(servicios, recepcion)
    ventana.ir_a("reportes")
    assert isinstance(ventana.pantalla_reportes, PantallaReportes)
    ventana._detener()
    ventana.close()
