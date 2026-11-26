"""Módulo Asistencia (sección 3.5): consultas con filtros, eliminación lógica con motivo,
reportes (del día, rango, cliente, franja horaria, ranking y ausentes) con exportación
a Excel y PDF e impresión. Cada línea muestra el casillero que tenía el cliente."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local
from gimnasio.servicios.asistencia import (
    LIMITE_CONSULTA, RESULTADOS, TIPOS_REPORTE, FiltrosAsistencia, ParametrosReporte, Reporte,
)
from gimnasio.servicios.clientes import SEXOS
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.pagos import abrir_archivo, campo_fecha, leer_fecha, pedir_motivo

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


class _Filtros(QWidget):
    """Sexo y plan, comunes a consultas y reportes."""

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self.sexo = _combo([("Todos los sexos", None)] + [(t, v) for v, t in SEXOS.items()])
        self.plan = _combo([("Todos los planes", None)] + [
            (nombre, pid) for pid, nombre in servicios.asistencia.planes(actual)
        ])


class PestanaRegistros(QWidget):
    registrar_manual = Signal()

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.pedir_motivo: Callable[[QWidget, str, str], str | None] = pedir_motivo
        self._admin = actual.puede(Permiso.REPORTES_TODOS)
        hoy = servicios.asistencia.hoy()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)

        fila = QHBoxLayout()
        self.desde = campo_fecha(hoy)
        self.hasta = campo_fecha(hoy)
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Código del cliente (opcional)")
        self.codigo.setMaximumWidth(220)
        self.resultado = _combo(
            [("Solo ingresos", None), ("Ingresos y rechazos", TODOS)]
            + [(t, v) for v, t in RESULTADOS.items()]
        )
        filtros = _Filtros(servicios, actual)
        self.sexo, self.plan = filtros.sexo, filtros.plan
        self.eliminadas = QCheckBox("Ver eliminadas")
        self.boton_consultar = boton("Consultar", principal=True)
        for texto, w in (("Desde", self.desde), ("Hasta", self.hasta), (None, self.codigo),
                         (None, self.resultado), (None, self.sexo), (None, self.plan),
                         (None, self.eliminadas), (None, self.boton_consultar)):
            if texto:
                fila.addWidget(QLabel(texto))
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        if not self._admin:
            # Recepción: el día de hoy o el historial de un cliente.
            for w in (self.desde, self.hasta):
                w.setEnabled(False)
                w.setToolTip("Recepción consulta el día de hoy o el historial de un cliente.")
            self.eliminadas.hide()

        self.tabla = tabla(["Fecha", "Hora", "Código", "Cliente", "Plan", "Resultado",
                            "Casillero", "Registró", "Estado"])
        capa.addWidget(self.tabla, 1)
        abajo = QHBoxLayout()
        self.total = etiqueta("", "textoSuave")
        abajo.addWidget(self.total, 1)
        self.boton_manual = boton("Registrar ingreso manual (documento o nombre)…")
        self.boton_eliminar = boton("Eliminar registro…")
        abajo.addWidget(self.boton_manual)
        abajo.addWidget(self.boton_eliminar)
        capa.addLayout(abajo)

        self.boton_consultar.clicked.connect(self.consultar)
        self.codigo.returnPressed.connect(self.consultar)
        self.boton_eliminar.clicked.connect(self.eliminar)
        self.boton_manual.clicked.connect(self.registrar_manual.emit)
        self.filas = []

    def filtros(self) -> FiltrosAsistencia:
        cliente_id = None
        codigo = self.codigo.text().strip()
        if codigo:
            cliente_id = self._servicios.asistencia.buscar_codigo(self._actual, codigo)
        resultado = self.resultado.currentData()
        desde, hasta = leer_fecha(self.desde), leer_fecha(self.hasta)
        if not self._admin:
            hoy = self._servicios.asistencia.hoy()
            desde = hasta = None if cliente_id else hoy
        return FiltrosAsistencia(
            desde=desde, hasta=hasta, cliente_id=cliente_id,
            resultado=None if resultado in (None, TODOS) else resultado,
            incluir_rechazos=resultado == TODOS, sexo=self.sexo.currentData(),
            plan_id=self.plan.currentData(),
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
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.reporte_actual: Reporte | None = None
        # Reemplazables en las pruebas.
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        self.abrir: Callable[[Path], None] = abrir_archivo
        hoy = servicios.asistencia.hoy()
        todos = actual.puede(Permiso.REPORTES_TODOS)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 10, 10, 10)

        fila = QHBoxLayout()
        self.tipo = _combo([(t, v) for v, t in TIPOS_REPORTE.items() if todos or v == "dia"])
        self.desde = campo_fecha(hoy)
        self.hasta = campo_fecha(hoy)
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Código del cliente")
        self.codigo.setMaximumWidth(180)
        self.dias = QSpinBox()
        self.dias.setRange(1, 3650)
        self.dias.setValue(30)
        self.dias.setSuffix(" días")
        self.limite = QSpinBox()
        self.limite.setRange(1, 1000)
        self.limite.setValue(50)
        self.limite.setPrefix("Top ")
        self.nunca = QCheckBox("Incluir los que nunca han venido")
        filtros = _Filtros(servicios, actual)
        self.sexo, self.plan = filtros.sexo, filtros.plan
        self.boton_generar = boton("Generar", principal=True)
        self.etiqueta_desde, self.etiqueta_hasta = QLabel("Desde"), QLabel("Hasta")
        for w in (self.tipo, self.etiqueta_desde, self.desde, self.etiqueta_hasta, self.hasta,
                  self.codigo, self.dias, self.limite, self.nunca, self.sexo, self.plan,
                  self.boton_generar):
            fila.addWidget(w)
        fila.addStretch()
        capa.addLayout(fila)
        if not todos:
            self.desde.setEnabled(False)

        self.subtitulo = etiqueta("", "textoSuave")
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

        self.tipo.currentIndexChanged.connect(self._al_cambiar_tipo)
        self.boton_generar.clicked.connect(self.generar)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_imprimir.clicked.connect(self.imprimir)
        self._al_cambiar_tipo()

    def _al_cambiar_tipo(self) -> None:
        tipo = self.tipo.currentData()
        rango = tipo in ("rango", "franja", "ranking", "cliente")
        self.etiqueta_desde.setVisible(tipo != "ausentes")
        self.desde.setVisible(tipo != "ausentes")
        self.etiqueta_desde.setText("Día" if tipo == "dia" else "Desde")
        self.etiqueta_hasta.setVisible(rango)
        self.hasta.setVisible(rango)
        self.codigo.setVisible(tipo == "cliente")
        self.dias.setVisible(tipo == "ausentes")
        self.nunca.setVisible(tipo == "ausentes")
        self.limite.setVisible(tipo == "ranking")
        self.plan.setVisible(tipo not in ("ausentes",))

    def parametros(self) -> ParametrosReporte:
        tipo = self.tipo.currentData()
        cliente_id = None
        if tipo == "cliente":
            codigo = self.codigo.text().strip()
            if not codigo:
                raise ErrorValidacion("Escriba el código del cliente.")
            cliente_id = self._servicios.asistencia.buscar_codigo(self._actual, codigo)
        return ParametrosReporte(
            tipo=tipo, desde=leer_fecha(self.desde), hasta=leer_fecha(self.hasta),
            cliente_id=cliente_id, dias=self.dias.value(), limite=self.limite.value(),
            incluir_nunca=self.nunca.isChecked(), sexo=self.sexo.currentData(),
            plan_id=self.plan.currentData(),
        )

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
        tipo = self.tipo.currentData()
        return f"asistencia_{tipo}_{leer_fecha(self.desde):%Y%m%d}.{formato}"

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
    registrar_manual = Signal()

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Asistencia", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Consulta, elimina (con motivo) y genera reportes de asistencia. Los intentos "
            "rechazados y los registros eliminados no cuentan en los reportes.", "textoSuave"))
        self.pestanas = QTabWidget()
        self.registros = PestanaRegistros(servicios, actual)
        self.reportes = PestanaReportes(servicios, actual)
        self.pestanas.addTab(self.registros, "Registros")
        self.pestanas.addTab(self.reportes, "Reportes")
        capa.addWidget(self.pestanas, 1)
        self.registros.registrar_manual.connect(self.registrar_manual.emit)

    def actualizar(self) -> None:
        self.registros.consultar()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.registros.consultar()
