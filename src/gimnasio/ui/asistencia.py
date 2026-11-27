"""Módulo Asistencia (sección 3.5), siempre de un cliente a la vez:

- Registrar ingreso: por código, con la misma tarjeta de Recepción (verde, amarillo o
  rojo) y el aviso de ingreso duplicado con confirmación.
- Historial del cliente: sus ingresos, con eliminación lógica con motivo.
- Reportes del cliente: exportación a Excel y PDF e impresión.

Nada se carga solo al abrir la pantalla: las consultas y los reportes se hacen cuando el
usuario los pide. Los reportes de todos los clientes (del día, rango, franja horaria,
ranking y ausentes) están en el módulo Reportes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QTabWidget,
    QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.servicios.asistencia import (
    LIMITE_CONSULTA, RESULTADOS, FiltrosAsistencia, ParametrosReporte, Reporte,
)
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.pagos import abrir_archivo, campo_fecha, leer_fecha, pedir_motivo
from gimnasio.ui.recepcion import PantallaRecepcion

TODOS = "__todos__"  # resultado: ingresos y rechazos


def _texto_celda(valor) -> str:
    """Fechas dd/mm/aaaa y números con formato colombiano (4.977 · 160,5)."""
    if isinstance(valor, date):
        return fecha(valor)
    if isinstance(valor, bool) or valor is None:
        return "" if valor is None else str(valor)
    if isinstance(valor, int):
        return f"{valor:,}".replace(",", ".")
    if isinstance(valor, float):
        return f"{valor:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return str(valor)


def _combo(opciones: list[tuple[str, object]]) -> QComboBox:
    c = QComboBox()
    for texto, dato in opciones:
        c.addItem(texto, dato)
    return c


class _RangoCliente:
    """Código del cliente y periodo (todo el historial o desde/hasta), comunes al
    historial y a los reportes. Recepción ve siempre todo el historial del cliente."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual, texto_codigo: str):
        self._servicios, self._actual = servicios, actual
        self.admin = actual.puede(Permiso.REPORTES_TODOS)
        hoy = servicios.asistencia.hoy()
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText(texto_codigo)
        self.codigo.setMaximumWidth(220)
        self.todo = QCheckBox("Todo el historial")
        self.todo.setChecked(True)
        self.desde = campo_fecha(hoy - timedelta(days=30))
        self.hasta = campo_fecha(hoy)
        self.todo.toggled.connect(self._al_cambiar_todo)
        if not self.admin:
            self.todo.setEnabled(False)
            self.todo.setToolTip("Recepción consulta todo el historial del cliente.")
        self._al_cambiar_todo()

    def _al_cambiar_todo(self) -> None:
        for w in (self.desde, self.hasta):
            w.setEnabled(not self.todo.isChecked())

    def widgets(self) -> list[tuple[str | None, QWidget]]:
        return [(None, self.codigo), (None, self.todo), ("Desde", self.desde),
                ("Hasta", self.hasta)]

    def cliente_id(self) -> int:
        codigo = self.codigo.text().strip()
        if not codigo:
            raise ErrorValidacion("Escriba el código del cliente.")
        return self._servicios.asistencia.buscar_codigo(self._actual, codigo)

    def periodo(self) -> tuple[date | None, date | None]:
        if self.todo.isChecked():
            return None, None
        return leer_fecha(self.desde), leer_fecha(self.hasta)


class PestanaIngreso(PantallaRecepcion):
    """Registro individual por código: la misma lógica y tarjeta de Recepción (semáforo,
    aviso de duplicado con Enter/Esc, Renovar F2, Autorizar F3, Ficha F4, búsqueda por
    documento o nombre F6), sin la lista de ingresos del día."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__(servicios, actual)
        self.layout().setContentsMargins(10, 10, 10, 10)
        titulo = self.findChild(QLabel, "tituloPantalla")
        if titulo is not None:
            titulo.hide()
        # Recepción ya no tiene listado lateral; aquí se ocultan además el contador y la
        # pantalla completa. Quedan los botones grandes de Registrar, Buscar (F6) y letra.
        self.contador.hide()
        self.boton_pantalla.hide()
        self.boton_manual = self.boton_buscar

    def actualizar_lista(self) -> None:
        """En Asistencia no se muestra el listado del día."""


class PestanaRegistros(QWidget):
    """Historial de un cliente: solo se consulta cuando el usuario lo pide."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.pedir_motivo: Callable[[QWidget, str, str], str | None] = pedir_motivo
        self._rango = _RangoCliente(servicios, actual, "Código del cliente")
        self._admin = self._rango.admin
        self.codigo, self.todo = self._rango.codigo, self._rango.todo
        self.desde, self.hasta = self._rango.desde, self._rango.hasta
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)

        fila = QHBoxLayout()
        self.resultado = _combo(
            [("Solo ingresos", None), ("Ingresos y rechazos", TODOS)]
            + [(t, v) for v, t in RESULTADOS.items()]
        )
        self.eliminadas = QCheckBox("Ver eliminadas")
        self.boton_consultar = boton("Consultar", principal=True)
        for texto, w in self._rango.widgets():
            if texto:
                fila.addWidget(QLabel(texto))
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        # Segunda fila: así los filtros caben en un portátil.
        fila = QHBoxLayout()
        for w in (self.resultado, self.eliminadas, self.boton_consultar):
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        if not self._admin:
            self.eliminadas.hide()

        self.tabla = tabla(["Fecha", "Hora", "Código", "Cliente", "Plan", "Resultado",
                            "Casillero", "Registró", "Estado"])
        capa.addWidget(self.tabla, 1)
        abajo = QHBoxLayout()
        self.total = etiqueta("Escriba el código del cliente y presione Consultar.",
                              "textoSuave")
        abajo.addWidget(self.total, 1)
        self.boton_eliminar = boton("Eliminar registro…")
        abajo.addWidget(self.boton_eliminar)
        capa.addLayout(abajo)

        self.boton_consultar.clicked.connect(self.consultar)
        self.codigo.returnPressed.connect(self.consultar)
        self.boton_eliminar.clicked.connect(self.eliminar)
        self.filas = []

    def filtros(self) -> FiltrosAsistencia:
        cliente_id = self._rango.cliente_id()
        desde, hasta = self._rango.periodo() if self._admin else (None, None)
        resultado = self.resultado.currentData()
        return FiltrosAsistencia(
            desde=desde, hasta=hasta, cliente_id=cliente_id,
            resultado=None if resultado in (None, TODOS) else resultado,
            incluir_rechazos=resultado == TODOS,
            incluir_eliminadas=self._admin and self.eliminadas.isChecked(),
        )

    def consultar(self) -> None:
        try:
            pagina = self._servicios.asistencia.consultar(self._actual, self.filtros())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.filas = pagina.filas
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(len(pagina.filas))
        for i, f in enumerate(pagina.filas):
            valores = [
                celda(fecha(f.fecha), dato=f.id, orden=f.fecha_hora),
                celda(fecha_hora_local(f.fecha_hora)[-5:]), celda(f.codigo), celda(f.nombre),
                celda(f.plan), celda(RESULTADOS.get(f.resultado, f.resultado)),
                celda(f.casillero or ""), celda(f.usuario),
                celda(f"Eliminada: {f.motivo_eliminacion}" if f.eliminada else ""),
            ]
            for j, item in enumerate(valores):
                if f.eliminada or not f.efectiva:
                    item.setForeground(Qt.GlobalColor.darkRed)
                self.tabla.setItem(i, j, item)
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        texto = f"{pagina.total} registros"
        if pagina.total > len(pagina.filas):
            texto += f" (se muestran los {LIMITE_CONSULTA} más recientes; afine los filtros)"
        self.total.setText(texto)

    def seleccionado(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.tabla.item(filas[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def eliminar(self) -> None:
        asistencia_id = self.seleccionado()
        if asistencia_id is None:
            mostrar_error(self, ErrorValidacion("Seleccione el registro que desea eliminar."))
            return
        motivo = self.pedir_motivo(self, "Eliminar asistencia",
                                   "Motivo de la eliminación (queda en la auditoría):")
        if motivo is None:
            return
        try:
            self._servicios.asistencia.eliminar(self._actual, asistencia_id, motivo)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        self.consultar()


class PestanaReportes(QWidget):
    """Reporte de asistencia de un cliente; se genera solo al presionar Generar."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.reporte_actual: Reporte | None = None
        # Reemplazables en las pruebas.
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        self.abrir: Callable[[Path], None] = abrir_archivo
        self._rango = _RangoCliente(servicios, actual, "Código del cliente")
        self.codigo, self.todo = self._rango.codigo, self._rango.todo
        self.desde, self.hasta = self._rango.desde, self._rango.hasta
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)

        fila = QHBoxLayout()
        self.boton_generar = boton("Generar", principal=True)
        for texto, w in self._rango.widgets() + [(None, self.boton_generar)]:
            if texto:
                fila.addWidget(QLabel(texto))
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)

        self.subtitulo = etiqueta(
            "Escriba el código del cliente y presione Generar. Los reportes de todos los "
            "clientes están en el módulo Reportes.", "textoSuave")
        capa.addWidget(self.subtitulo)
        self.tabla = tabla([""])
        capa.addWidget(self.tabla, 1)
        abajo = QHBoxLayout()
        abajo.addStretch()
        self.boton_excel = boton("Exportar a Excel…")
        self.boton_pdf = boton("Exportar a PDF…")
        self.boton_imprimir = boton("Imprimir")
        for b in (self.boton_excel, self.boton_pdf, self.boton_imprimir):
            abajo.addWidget(b)
        capa.addLayout(abajo)

        self.boton_generar.clicked.connect(self.generar)
        self.codigo.returnPressed.connect(self.generar)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_imprimir.clicked.connect(self.imprimir)

    def parametros(self) -> ParametrosReporte:
        cliente_id = self._rango.cliente_id()
        desde, hasta = self._rango.periodo()
        return ParametrosReporte(tipo="cliente", desde=desde, hasta=hasta,
                                 cliente_id=cliente_id)

    def generar(self) -> Reporte | None:
        try:
            rep = self._servicios.asistencia.reporte(self._actual, self.parametros())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.reporte_actual = rep
        self.subtitulo.setText(f"{rep.titulo} · {rep.subtitulo}")
        self.tabla.setSortingEnabled(False)
        self.tabla.clear()
        self.tabla.setColumnCount(len(rep.encabezados))
        self.tabla.setHorizontalHeaderLabels(list(rep.encabezados))
        self.tabla.setRowCount(len(rep.filas))
        for i, fila in enumerate(rep.filas):
            for j, valor in enumerate(fila):
                orden = valor if isinstance(valor, (int, float, date)) else None
                self.tabla.setItem(i, j, celda(_texto_celda(valor), orden=orden))
        # Conserva el orden del reporte hasta que el usuario haga clic en una columna.
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        return rep

    @staticmethod
    def _elegir_ruta(sugerido: str, filtro: str) -> str | None:
        ruta, _ = QFileDialog.getSaveFileName(None, "Guardar reporte", sugerido, filtro)
        return ruta or None

    def _nombre(self, formato: str) -> str:
        codigo = "".join(c for c in self.codigo.text().strip() if c.isalnum()) or "cliente"
        return f"asistencia_{codigo}_{self._servicios.asistencia.hoy():%Y%m%d}.{formato}"

    def exportar(self, formato: str) -> Path | None:
        filtro = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
        sugerido = str(self._servicios.asistencia.carpeta_reportes() / self._nombre(formato))
        ruta = self.elegir_ruta(sugerido, filtro)
        if not ruta:
            return None
        if not ruta.lower().endswith(f".{formato}"):
            ruta += f".{formato}"
        try:
            parametros = self.parametros()
            destino = self._servicios.asistencia.exportar(self._actual, parametros, ruta, formato)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo guardar el archivo. Revise que no esté abierto en otro programa."))
            return None
        self.subtitulo.setText(f"Reporte guardado en {destino}")
        return destino

    def imprimir(self) -> Path | None:
        """Genera el PDF en la carpeta de reportes y lo abre para imprimir."""
        ruta = self._servicios.asistencia.carpeta_reportes() / self._nombre("pdf")
        try:
            destino = self._servicios.asistencia.exportar(
                self._actual, self.parametros(), ruta, "pdf")
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo crear el PDF. Cierre el reporte anterior si está abierto."))
            return None
        self.abrir(destino)
        return destino


class PantallaAsistencia(QWidget):
    abrir_ficha = Signal(int)

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Asistencia", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Registra el ingreso de un cliente por su código y consulta su historial o su "
            "reporte. Nada se carga hasta que usted lo pide. Los reportes de todos los "
            "clientes están en el módulo Reportes.", "textoSuave"))
        self.pestanas = QTabWidget()
        self.ingreso = PestanaIngreso(servicios, actual)
        self.registros = PestanaRegistros(servicios, actual)
        self.reportes = PestanaReportes(servicios, actual)
        self.pestanas.addTab(self.ingreso, "Registrar ingreso")
        self.pestanas.addTab(self.registros, "Historial del cliente")
        self.pestanas.addTab(self.reportes, "Reportes del cliente")
        capa.addWidget(self.pestanas, 1)
        self.ingreso.abrir_ficha.connect(self.abrir_ficha.emit)
