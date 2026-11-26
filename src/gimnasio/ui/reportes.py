"""Módulo Reportes (sección 3.8): lista de reportes por grupo, filtros según el reporte,
vista previa con totales y exportación a Excel, PDF e impresión.

Lo que puede ver cada rol lo decide `ServicioReportes`; aquí solo se muestra la lista
que el servicio devuelve y se bloquean las fechas cuando Recepción solo ve el día de hoy.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, fecha_hora_local, pesos
from gimnasio.servicios.casilleros import ESTADOS as ESTADOS_CASILLERO, SITUACIONES, ZONAS
from gimnasio.servicios.clientes import SEXOS
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.pagos import CONCEPTOS, METODOS
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.servicios.reportes import (
    DefinicionReporte, ParametrosReportes, ResultadoReporte,
)
from gimnasio.ui.comunes import boton, celda, etiqueta, mostrar_error, tabla
from gimnasio.ui.pagos import abrir_archivo, campo_fecha, leer_fecha

# Más filas que esto hacen lenta la tabla; la exportación siempre lleva todas.
LIMITE_VISTA_PREVIA = 2000

PERIODOS = ("Este mes", "Mes anterior", "Últimos 30 días", "Últimos 12 meses", "Este año",
            "Hoy", "Personalizado")


def periodo(nombre: str, hoy: date) -> tuple[date, date]:
    """Fechas (desde, hasta) de un periodo rápido."""
    inicio_mes = hoy.replace(day=1)
    if nombre == "Mes anterior":
        fin = inicio_mes - timedelta(days=1)
        return fin.replace(day=1), fin
    if nombre == "Últimos 30 días":
        return hoy - timedelta(days=29), hoy
    if nombre == "Últimos 12 meses":
        anio, mes = (inicio_mes.year, inicio_mes.month - 11) if inicio_mes.month > 11 else (
            inicio_mes.year - 1, inicio_mes.month + 1)
        return date(anio, mes, 1), hoy
    if nombre == "Este año":
        return date(hoy.year, 1, 1), hoy
    if nombre == "Hoy":
        return hoy, hoy
    return inicio_mes, hoy


def texto_valor(valor, dinero: bool = False) -> str:
    """Fechas dd/mm/aaaa, pesos $ 1.234 y números con formato colombiano."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    if dinero and isinstance(valor, int):
        return pesos(valor)
    if hasattr(valor, "tzinfo") and hasattr(valor, "hour"):
        return fecha_hora_local(valor)
    if isinstance(valor, date):
        return fecha(valor)
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


class PantallaReportes(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self._rep = servicios.reportes
        self.resultado: ResultadoReporte | None = None
        self.definicion: DefinicionReporte | None = None
        # Reemplazables en las pruebas.
        self.elegir_ruta: Callable[[str, str], str | None] = self._elegir_ruta
        self.abrir: Callable[[Path], None] = abrir_archivo
        self._todos = actual.puede(Permiso.REPORTES_TODOS)
        self._definiciones = {d.clave: d for d in self._rep.disponibles(actual)}

        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Reportes", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Elija un reporte, ajuste los filtros y presione Generar (o Enter). Todos se "
            "exportan a Excel y PDF y se imprimen desde el PDF." + (
                "" if self._todos else " Recepción ve los reportes básicos."),
            "textoSuave"))
        divisor = QSplitter(Qt.Orientation.Horizontal)
        capa.addWidget(divisor, 1)

        self.lista = QTreeWidget()
        self.lista.setHeaderHidden(True)
        self.lista.setMinimumWidth(260)
        grupos: dict[str, QTreeWidgetItem] = {}
        for d in self._definiciones.values():
            if d.grupo not in grupos:
                grupo = QTreeWidgetItem([d.grupo])
                letra = QFont()
                letra.setBold(True)
                grupo.setFont(0, letra)
                grupo.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.lista.addTopLevelItem(grupo)
                grupos[d.grupo] = grupo
            item = QTreeWidgetItem([d.titulo])
            item.setData(0, Qt.ItemDataRole.UserRole, d.clave)
            item.setToolTip(0, d.descripcion)
            grupos[d.grupo].addChild(item)
        self.lista.expandAll()
        divisor.addWidget(self.lista)

        derecha = QWidget()
        capa_der = QVBoxLayout(derecha)
        capa_der.setContentsMargins(12, 0, 0, 0)
        self.titulo = etiqueta("", "contadorTexto")
        self.descripcion = etiqueta("", "textoSuave")
        self.descripcion.setWordWrap(True)
        capa_der.addWidget(self.titulo)
        capa_der.addWidget(self.descripcion)
        capa_der.addLayout(self._crear_filtros())
        self.subtitulo = etiqueta("", "textoSuave")
        self.subtitulo.setWordWrap(True)
        capa_der.addWidget(self.subtitulo)
        self.tabla = tabla([""])
        capa_der.addWidget(self.tabla, 1)
        self.etiqueta_totales = QLabel("")
        self.etiqueta_totales.setWordWrap(True)
        letra = self.etiqueta_totales.font()
        letra.setBold(True)
        self.etiqueta_totales.setFont(letra)
        capa_der.addWidget(self.etiqueta_totales)
        abajo = QHBoxLayout()
        abajo.addStretch()
        self.boton_excel = boton("Exportar a Excel…")
        self.boton_pdf = boton("Exportar a PDF…")
        self.boton_imprimir = boton("Imprimir")
        for b in (self.boton_excel, self.boton_pdf, self.boton_imprimir):
            abajo.addWidget(b)
        capa_der.addLayout(abajo)
        divisor.addWidget(derecha)
        divisor.setStretchFactor(1, 1)

        self.lista.currentItemChanged.connect(self._al_elegir)
        self.lista.itemActivated.connect(lambda *_: self.generar())
        self.boton_generar.clicked.connect(self.generar)
        self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
        self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        self.boton_imprimir.clicked.connect(self.imprimir)
        for tecla in ("Return", "Enter"):
            QShortcut(QKeySequence(tecla), self, activated=self.generar,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.imprimir,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._activar_exportacion(False)
        primero = self.lista.topLevelItem(0)
        if primero and primero.childCount():
            self.lista.setCurrentItem(primero.child(0))

    # --- filtros --------------------------------------------------------------------
    def _crear_filtros(self) -> QVBoxLayout:
        hoy = self._rep.hoy()
        self.periodo = _combo([(p, p) for p in PERIODOS])
        self.desde, self.hasta = campo_fecha(hoy.replace(day=1)), campo_fecha(hoy)
        self.dia = campo_fecha(hoy)
        self.dias = QSpinBox()
        self.dias.setRange(0, 3650)
        self.dias.setSuffix(" días")
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Código del cliente")
        self.codigo.setMaximumWidth(170)
        self.limite = QSpinBox()
        self.limite.setRange(1, 1000)
        self.limite.setValue(50)
        self.limite.setPrefix("Top ")
        self.nunca = QCheckBox("Incluir los que nunca han venido")
        self.plan = _combo([("Todos los planes", None)] + [
            (nombre, pid) for pid, nombre in self._rep.planes(self._actual)])
        self.sexo = _combo([("Todos los sexos", None)] + [(t, v) for v, t in SEXOS.items()])
        self.metodo = _combo([("Todos los métodos", None)] + [(t, v) for v, t in METODOS.items()])
        self.usuario = _combo(([("Todos los usuarios", None)] if self._todos else []) + [
            (nombre, uid) for uid, nombre in self._rep.usuarios(self._actual)])
        self.concepto = _combo([("Todos los conceptos", None)] + [
            (t, v) for v, t in CONCEPTOS.items()])
        self.estado_casillero = _combo([("Todos los estados", None)] + [
            (t, v) for v, t in ESTADOS_CASILLERO.items()])
        self.zona = _combo([("Todas las zonas", None)] + [(t, v) for v, t in ZONAS.items()])
        self.sexo_ocupante = _combo([("Ocupados por cualquier sexo", None)] + [
            (f"Ocupados por sexo {t.lower()}", v) for v, t in SEXOS.items()])
        self.situacion = _combo([("Cualquier situación", None)] + [
            (t, v) for v, t in SITUACIONES.items()])
        self.boton_generar = boton("Generar", principal=True)

        self.etiqueta_periodo = QLabel("Periodo")
        self.etiqueta_desde, self.etiqueta_hasta = QLabel("Desde"), QLabel("Hasta")
        self.etiqueta_dia = QLabel("Día")
        self.etiqueta_dias = QLabel("Días")
        # filtro -> widgets que lo forman
        self._widgets = {
            "rango": (self.etiqueta_periodo, self.periodo, self.etiqueta_desde, self.desde,
                      self.etiqueta_hasta, self.hasta),
            "dia": (self.etiqueta_dia, self.dia),
            "dias": (self.etiqueta_dias, self.dias),
            "cliente": (self.codigo,), "anfitrion": (self.codigo,),
            "limite": (self.limite,), "nunca": (self.nunca,),
            "plan": (self.plan,), "sexo": (self.sexo,), "metodo": (self.metodo,),
            "usuario": (self.usuario,), "concepto": (self.concepto,),
            "estado_casillero": (self.estado_casillero,), "zona": (self.zona,),
            "sexo_ocupante": (self.sexo_ocupante,), "situacion": (self.situacion,),
        }
        fila1, fila2 = QHBoxLayout(), QHBoxLayout()
        for w in (self.etiqueta_periodo, self.periodo, self.etiqueta_desde, self.desde,
                  self.etiqueta_hasta, self.hasta, self.etiqueta_dia, self.dia,
                  self.etiqueta_dias, self.dias, self.codigo, self.limite, self.nunca):
            fila1.addWidget(w)
        fila1.addStretch()
        for w in (self.plan, self.sexo, self.metodo, self.usuario, self.concepto,
                  self.estado_casillero, self.zona, self.sexo_ocupante, self.situacion,
                  self.boton_generar):
            fila2.addWidget(w)
        fila2.addStretch()
        self.periodo.currentIndexChanged.connect(self._al_cambiar_periodo)
        self.desde.dateChanged.connect(self._fecha_editada)
        self.hasta.dateChanged.connect(self._fecha_editada)
        capa = QVBoxLayout()
        capa.addLayout(fila1)
        capa.addLayout(fila2)
        return capa

    def _al_cambiar_periodo(self) -> None:
        nombre = self.periodo.currentData()
        if nombre == "Personalizado":
            return
        desde, hasta = periodo(nombre, self._rep.hoy())
        self._poniendo_fechas = True
        self.desde.setDate(desde)
        self.hasta.setDate(hasta)
        self._poniendo_fechas = False

    def _fecha_editada(self) -> None:
        if not getattr(self, "_poniendo_fechas", False):
            self.periodo.blockSignals(True)
            self.periodo.setCurrentIndex(PERIODOS.index("Personalizado"))
            self.periodo.blockSignals(False)

    def _al_elegir(self, item: QTreeWidgetItem | None, _anterior=None) -> None:
        clave = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not clave:
            return
        self.elegir(clave)

    def elegir(self, clave: str) -> None:
        """Muestra los filtros del reporte (sin generarlo)."""
        d = self._definiciones[clave]
        self.definicion = d
        self._marcar_en_lista(clave)
        self.titulo.setText(d.titulo)
        nota = f" {d.nota_recepcion}" if d.nota_recepcion and not self._todos else ""
        self.descripcion.setText(d.descripcion + nota)
        visibles = {w for f in d.filtros for w in self._widgets.get(f, ())}
        for widgets in self._widgets.values():
            for w in widgets:
                w.setVisible(w in visibles)
        self.codigo.setPlaceholderText(
            "Código del anfitrión (opcional)" if "anfitrion" in d.filtros
            else "Código del cliente")
        # Valores por defecto de cada reporte.
        if clave == "clientes_por_vencer":
            self.dias.setValue(self._servicios.configuracion.obtener("dias_por_vencer"))
        elif "dias" in d.filtros:
            self.dias.setValue(30)
        if "rango" in d.filtros:
            inicial = "Últimos 12 meses" if clave == "clientes_mensual" else "Este mes"
            if not self._todos and d.solo_hoy_recepcion:
                inicial = "Hoy"
            self.periodo.setCurrentIndex(PERIODOS.index(inicial))
            self._al_cambiar_periodo()
        bloqueado = not self._todos and d.solo_hoy_recepcion
        for w in (self.periodo, self.desde, self.hasta, self.dia):
            w.setEnabled(not bloqueado)
        if bloqueado:
            self.dia.setDate(self._rep.hoy())
        self.resultado = None
        self.tabla.clear()
        self.tabla.setRowCount(0)
        self.tabla.setColumnCount(0)
        self.subtitulo.setText("Presione Generar para ver el reporte.")
        self.etiqueta_totales.setText("")
        self._activar_exportacion(False)

    def _marcar_en_lista(self, clave: str) -> None:
        for i in range(self.lista.topLevelItemCount()):
            grupo = self.lista.topLevelItem(i)
            for j in range(grupo.childCount()):
                item = grupo.child(j)
                if item.data(0, Qt.ItemDataRole.UserRole) == clave:
                    if self.lista.currentItem() is not item:
                        self.lista.blockSignals(True)
                        self.lista.setCurrentItem(item)
                        self.lista.blockSignals(False)
                    return

    def parametros(self) -> ParametrosReportes:
        d = self.definicion
        if d is None:
            raise ErrorValidacion("Elija un reporte.")
        filtros = set(d.filtros)
        cliente_id = anfitrion_id = None
        codigo = self.codigo.text().strip()
        if "cliente" in filtros:
            if not codigo:
                raise ErrorValidacion("Escriba el código del cliente.")
            cliente_id = self._rep.buscar_codigo(self._actual, codigo)
        if "anfitrion" in filtros and codigo:
            anfitrion_id = self._rep.buscar_codigo(self._actual, codigo)
        if "rango" in filtros:
            desde, hasta = leer_fecha(self.desde), leer_fecha(self.hasta)
        elif "dia" in filtros:
            desde = hasta = leer_fecha(self.dia)
        else:
            desde = hasta = None

        def valor(nombre: str, combo: QComboBox):
            return combo.currentData() if nombre in filtros else None

        return ParametrosReportes(
            desde=desde, hasta=hasta,
            dias=self.dias.value() if "dias" in filtros else None,
            cliente_id=cliente_id, anfitrion_id=anfitrion_id,
            plan_id=valor("plan", self.plan), sexo=valor("sexo", self.sexo),
            metodo=valor("metodo", self.metodo), usuario_id=valor("usuario", self.usuario),
            concepto=valor("concepto", self.concepto), limite=self.limite.value(),
            incluir_nunca=self.nunca.isChecked() and "nunca" in filtros,
            estado_casillero=valor("estado_casillero", self.estado_casillero),
            zona=valor("zona", self.zona), sexo_ocupante=valor("sexo_ocupante", self.sexo_ocupante),
            situacion=valor("situacion", self.situacion),
        )

    # --- generar y exportar -----------------------------------------------------------
    def generar(self) -> ResultadoReporte | None:
        if self.definicion is None:
            return None
        try:
            rep = self._rep.generar(self._actual, self.definicion.clave, self.parametros())
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self.resultado = rep
        self._mostrar(rep)
        self._activar_exportacion(True)
        return rep

    def _mostrar(self, rep: ResultadoReporte) -> None:
        aviso = ""
        if len(rep.filas) > LIMITE_VISTA_PREVIA:
            aviso = (f" · Vista previa: primeras {LIMITE_VISTA_PREVIA:,} de "
                     f"{len(rep.filas):,} filas; Excel y PDF llevan todas.").replace(",", ".")
        self.subtitulo.setText(f"{rep.titulo} · {rep.subtitulo}{aviso}")
        filas = rep.filas[:LIMITE_VISTA_PREVIA]
        self.tabla.setSortingEnabled(False)
        self.tabla.clear()
        self.tabla.setColumnCount(len(rep.encabezados))
        self.tabla.setHorizontalHeaderLabels(list(rep.encabezados))
        self.tabla.setRowCount(len(filas))
        derecha = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        for i, fila in enumerate(filas):
            for j, valor in enumerate(fila):
                orden = valor if isinstance(valor, (int, float, date)) else None
                item = celda(texto_valor(valor, j in rep.dinero), orden=orden)
                if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                    item.setTextAlignment(derecha)
                self.tabla.setItem(i, j, item)
        self.tabla.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.tabla.setSortingEnabled(True)
        if rep.totales:
            partes = [
                f"{rep.encabezados[j]}: {texto_valor(v, j in rep.dinero)}"
                for j, v in enumerate(rep.totales) if j > 0 and v not in ("", None)
            ]
            self.etiqueta_totales.setText("Totales · " + " · ".join(partes))
        else:
            self.etiqueta_totales.setText(rep.resumen)

    def _activar_exportacion(self, activo: bool) -> None:
        # Se puede exportar sin vista previa, pero así el usuario ve antes qué imprime.
        for b in (self.boton_excel, self.boton_pdf, self.boton_imprimir):
            b.setEnabled(activo)

    @staticmethod
    def _elegir_ruta(sugerido: str, filtro: str) -> str | None:
        ruta, _ = QFileDialog.getSaveFileName(None, "Guardar reporte", sugerido, filtro)
        return ruta or None

    def _nombre(self, formato: str) -> str:
        return f"{self.definicion.clave}_{self._rep.hoy():%Y%m%d}.{formato}"

    def exportar(self, formato: str) -> Path | None:
        if self.definicion is None:
            return None
        filtro = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
        sugerido = str(self._rep.carpeta_reportes() / self._nombre(formato))
        ruta = self.elegir_ruta(sugerido, filtro)
        if not ruta:
            return None
        if not ruta.lower().endswith(f".{formato}"):
            ruta += f".{formato}"
        return self._exportar_a(ruta, formato)

    def imprimir(self) -> Path | None:
        """Genera el PDF en la carpeta de reportes y lo abre para imprimir."""
        if self.definicion is None or not self.boton_imprimir.isEnabled():
            return None
        destino = self._exportar_a(self._rep.carpeta_reportes() / self._nombre("pdf"), "pdf")
        if destino:
            self.abrir(destino)
        return destino

    def _exportar_a(self, ruta, formato: str) -> Path | None:
        try:
            destino = self._rep.exportar(
                self._actual, self.definicion.clave, self.parametros(), ruta, formato)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo guardar el archivo. Revise que no esté abierto en otro programa."))
            return None
        self.subtitulo.setText(f"Reporte guardado en {destino}")
        return destino
