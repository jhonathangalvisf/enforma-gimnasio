"""Pantalla de Clientes: búsqueda instantánea, filtros, tabla por páginas y exportación.

Los datos de los clientes son confidenciales: el módulo está bloqueado para todos
(también para el administrador) y cada vez que se entra un administrador escribe su
usuario y clave. Al salir del módulo se vuelve a bloquear y la lista se borra.

La tabla no carga los 12.000 clientes de una vez: pide páginas de 200 a medida que
el usuario baja (carga virtual) y el orden se hace en la base de datos.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha, leer_fecha
from gimnasio.servicios.clientes import (
    ESTADOS, NOMBRES_VIGENCIA, SEXOS, FilaCliente, FiltrosClientes, Vigencia,
)
from gimnasio.servicios.autorizaciones import PARA_MODULO_CLIENTES, Autorizacion
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual
from gimnasio.ui.comunes import boton, etiqueta, mostrar_error

TAMANO_PAGINA = 200
ESPERA_BUSQUEDA_MS = 250
AL_DIA = "al_dia"  # opción del filtro de vigencia: vigentes + por vencer
DIAS_SIN_ASISTIR = (7, 15, 30, 60, 90, 180)
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre")

# Texto + símbolo: no depender solo del color (accesibilidad).
TEXTO_VIGENCIA = {
    Vigencia.VIGENTE: "✔ Vigente",
    Vigencia.POR_VENCER: "⚠ Por vencer",
    Vigencia.VENCIDA: "✖ Vencida",
    Vigencia.SIN_MEMBRESIA: "— Sin membresía",
}
COLOR_VIGENCIA = {
    Vigencia.VIGENTE: "#1e7b34",
    Vigencia.POR_VENCER: "#9a6700",
    Vigencia.VENCIDA: "#b42318",
    Vigencia.SIN_MEMBRESIA: "#5b6775",
}


def texto_vigencia(vigencia: Vigencia, dias: int | None) -> str:
    texto = TEXTO_VIGENCIA[vigencia]
    if vigencia == Vigencia.POR_VENCER:
        texto += " (hoy)" if dias == 0 else f" ({dias} d)"
    return texto


class ModeloClientes(QAbstractTableModel):
    """Modelo de tabla con carga por páginas y orden en la base de datos."""

    COLUMNAS: tuple[tuple[str, str], ...] = (
        ("codigo", "Código"), ("nombres", "Nombres"), ("apellidos", "Apellidos"),
        ("documento", "Documento"), ("telefono", "Teléfono"), ("plan", "Plan"),
        ("vence", "Vence"), ("vigencia", "Vigencia"), ("estado", "Estado"),
    )

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        self.filas: list[FilaCliente] = []
        self.total = 0
        self.filtros = FiltrosClientes()
        self.orden = "apellidos"
        self.descendente = False
        self.autorizacion: Autorizacion | None = None  # la del módulo bloqueado
        self.habilitado = False  # mientras el módulo esté bloqueado no se consulta nada

    def vaciar(self) -> None:
        self.beginResetModel()
        self.filas = []
        self.total = 0
        self.endResetModel()

    # --- consultas ------------------------------------------------------------
    def consultar(self, filtros: FiltrosClientes | None = None) -> None:
        if filtros is not None:
            self.filtros = filtros
        if not self.habilitado:
            return
        pagina = self._servicios.clientes.buscar(
            self._actual, self.filtros, orden=self.orden, descendente=self.descendente,
            desde=0, limite=TAMANO_PAGINA, autorizacion=self.autorizacion,
        )
        self.beginResetModel()
        self.filas = list(pagina.filas)
        self.total = pagina.total
        self.endResetModel()

    def canFetchMore(self, padre=QModelIndex()) -> bool:  # noqa: N802 (nombre de Qt)
        return not padre.isValid() and len(self.filas) < self.total

    def fetchMore(self, padre=QModelIndex()) -> None:  # noqa: N802
        if padre.isValid() or len(self.filas) >= self.total or not self.habilitado:
            return
        pagina = self._servicios.clientes.buscar(
            self._actual, self.filtros, orden=self.orden, descendente=self.descendente,
            desde=len(self.filas), limite=TAMANO_PAGINA, autorizacion=self.autorizacion,
        )
        if not pagina.filas:
            self.total = len(self.filas)
            return
        inicio = len(self.filas)
        self.beginInsertRows(QModelIndex(), inicio, inicio + len(pagina.filas) - 1)
        self.filas.extend(pagina.filas)
        self.endInsertRows()

    def sort(self, columna: int, orden=Qt.SortOrder.AscendingOrder) -> None:
        self.orden = self.COLUMNAS[columna][0]
        self.descendente = orden == Qt.SortOrder.DescendingOrder
        self.consultar()

    # --- datos para Qt ------------------------------------------------------
    def rowCount(self, padre=QModelIndex()) -> int:  # noqa: N802
        return 0 if padre.isValid() else len(self.filas)

    def columnCount(self, padre=QModelIndex()) -> int:  # noqa: N802
        return 0 if padre.isValid() else len(self.COLUMNAS)

    def headerData(self, seccion, orientacion, rol=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientacion == Qt.Orientation.Horizontal and rol == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNAS[seccion][1]
        return None

    def data(self, indice: QModelIndex, rol=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        fila = self.filas[indice.row()]
        clave = self.COLUMNAS[indice.column()][0]
        if rol == Qt.ItemDataRole.DisplayRole:
            return self.texto(fila, clave)
        if rol == Qt.ItemDataRole.ForegroundRole:
            if clave == "vigencia":
                return QBrush(QColor(COLOR_VIGENCIA[fila.vigencia]))
            if clave == "estado" and fila.estado == "inactivo":
                return QBrush(QColor("#b42318"))
        if rol == Qt.ItemDataRole.UserRole:
            return fila.id
        return None

    @staticmethod
    def texto(fila: FilaCliente, clave: str) -> str:
        if clave == "documento":
            return f"{fila.tipo_documento} {fila.documento}"
        if clave == "vence":
            return fecha(fila.fecha_fin) if fila.fecha_fin else ""
        if clave == "vigencia":
            return texto_vigencia(fila.vigencia, fila.dias_restantes)
        if clave == "estado":
            return ESTADOS.get(fila.estado, fila.estado)
        return str(getattr(fila, clave) or "")


class PantallaClientes(QWidget):
    # Pide a la ventana principal abrir la ficha de un cliente.
    abrir_ficha = Signal(int)

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios = servicios
        self._actual = actual
        # Las pruebas reemplazan cómo se muestran los diálogos (exec bloquea).
        self._ejecutar: Callable[[QDialog], int] = lambda d: d.exec()
        self.autorizacion: Autorizacion | None = None
        self.desbloqueado = False
        exterior = QVBoxLayout(self)
        exterior.setContentsMargins(24, 20, 24, 20)
        exterior.setSpacing(10)
        exterior.addWidget(etiqueta("Clientes", "tituloPantalla"))

        # Candado: lo único que se ve hasta escribir la clave.
        self.panel_bloqueado = QWidget()
        bloqueo = QVBoxLayout(self.panel_bloqueado)
        bloqueo.addStretch()
        bloqueo.addWidget(etiqueta(
            "🔒 El módulo de Clientes necesita la clave de un administrador cada vez que "
            "se abre.", "textoSuave"), 0, Qt.AlignmentFlag.AlignCenter)
        self.boton_desbloquear = boton("Desbloquear con clave de administrador…",
                                       principal=True)
        self.boton_desbloquear.clicked.connect(self.desbloquear)
        bloqueo.addWidget(self.boton_desbloquear, 0, Qt.AlignmentFlag.AlignCenter)
        bloqueo.addStretch()
        exterior.addWidget(self.panel_bloqueado, 1)

        self.contenido = QWidget()
        exterior.addWidget(self.contenido, 1)
        capa = QVBoxLayout(self.contenido)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(10)

        cabecera = QHBoxLayout()
        cabecera.addStretch(1)
        self.boton_nuevo = boton("Nuevo cliente  (Ctrl+N)", principal=True)
        self.boton_ficha = boton("Ver ficha")
        cabecera.addWidget(self.boton_ficha)
        cabecera.addWidget(self.boton_nuevo)
        self.boton_excel = self.boton_pdf = None
        if actual.puede(Permiso.REPORTES_TODOS):
            self.boton_excel = boton("Exportar a Excel")
            self.boton_pdf = boton("Exportar a PDF")
            cabecera.addWidget(self.boton_excel)
            cabecera.addWidget(self.boton_pdf)
            self.boton_excel.clicked.connect(lambda: self.exportar("xlsx"))
            self.boton_pdf.clicked.connect(lambda: self.exportar("pdf"))
        capa.addLayout(cabecera)

        capa.addLayout(self._crear_resumen())

        self.campo_busqueda = QLineEdit()
        self.campo_busqueda.setPlaceholderText(
            "Buscar por código, nombre, apellido, documento, teléfono o correo"
        )
        self.campo_busqueda.setClearButtonEnabled(True)
        capa.addWidget(self.campo_busqueda)
        capa.addLayout(self._crear_filtros())

        self.mensaje = etiqueta("", "textoSuave")
        capa.addWidget(self.mensaje)

        self.modelo = ModeloClientes(servicios, actual)
        self.tabla = QTableView()
        self.tabla.setModel(self.modelo)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(28)
        cabeza = self.tabla.horizontalHeader()
        cabeza.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        cabeza.setStretchLastSection(True)
        for columna, ancho in enumerate((80, 170, 190, 140, 120, 120, 95, 140)):
            self.tabla.setColumnWidth(columna, ancho)
        self.tabla.setSortingEnabled(True)
        cabeza.setSortIndicator(2, Qt.SortOrder.AscendingOrder)  # apellidos
        self.tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        capa.addWidget(self.tabla, 1)

        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.setInterval(ESPERA_BUSQUEDA_MS)
        self._espera.timeout.connect(self.actualizar)
        self.campo_busqueda.textChanged.connect(lambda _: self._espera.start())
        self.campo_busqueda.returnPressed.connect(self._enter_en_busqueda)
        self.tabla.doubleClicked.connect(lambda _: self.ver_ficha())
        self.tabla.activated.connect(lambda _: self.ver_ficha())
        self.tabla.customContextMenuRequested.connect(self._menu_contextual)
        self.boton_ficha.clicked.connect(self.ver_ficha)
        self.boton_nuevo.clicked.connect(self.nuevo)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._si_desbloqueado(self.nuevo))
        QShortcut(QKeySequence("Ctrl+F"), self,
                  activated=self._si_desbloqueado(self.enfocar_busqueda))
        self.contenido.hide()

    def _si_desbloqueado(self, accion: Callable[[], None]) -> Callable[[], None]:
        return lambda: accion() if self.desbloqueado else None

    # --- bloqueo con clave ---------------------------------------------------------
    def desbloquear(self) -> bool:
        if self.desbloqueado:
            return True
        from gimnasio.ui.autorizacion import pedir_clave_siempre

        ok, autorizacion = pedir_clave_siempre(self, self._servicios, self._actual,
                                               PARA_MODULO_CLIENTES)
        if not ok:
            return False
        self.autorizacion = self.modelo.autorizacion = autorizacion
        self.desbloqueado = self.modelo.habilitado = True
        self.panel_bloqueado.hide()
        self.contenido.show()
        self.recargar()
        self.enfocar_busqueda()
        return True

    def bloquear(self) -> None:
        """Al salir del módulo se olvida la autorización, se borra la lista y se bloquea."""
        self._servicios.autorizaciones.revocar(self.autorizacion)
        self.autorizacion = self.modelo.autorizacion = None
        self.desbloqueado = self.modelo.habilitado = False
        self.contenido.hide()
        self.panel_bloqueado.show()
        self.modelo.vaciar()
        self.resumen = None
        for b in self.botones_resumen.values():
            b.setText("")
        self.mensaje.setText("")

    def _crear_filtros(self) -> QVBoxLayout:
        filas = QVBoxLayout()
        filas.setSpacing(6)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        segunda = QHBoxLayout()
        segunda.setSpacing(8)
        self.filtro_estado = QComboBox()
        self.filtro_estado.addItem("Estado: todos", None)
        for valor, texto in ESTADOS.items():
            self.filtro_estado.addItem(texto, valor)
        self.filtro_vigencia = QComboBox()
        self.filtro_vigencia.addItem("Vigencia: todas", None)
        self.filtro_vigencia.addItem("Al día (vigentes y por vencer)", AL_DIA)
        for valor, texto in NOMBRES_VIGENCIA.items():
            self.filtro_vigencia.addItem(texto, valor.value)
        self.filtro_sexo = QComboBox()
        self.filtro_sexo.addItem("Sexo: todos", None)
        for valor, texto in SEXOS.items():
            self.filtro_sexo.addItem(texto, valor)
        self.filtro_plan = QComboBox()
        self.filtro_plan.addItem("Plan: todos", None)
        try:
            for plan_id, nombre in self._servicios.clientes.planes(self._actual):
                self.filtro_plan.addItem(nombre, plan_id)
        except ErrorNegocio:
            pass
        self.filtro_cumple = QComboBox()
        self.filtro_cumple.addItem("Cumpleaños: todos", None)
        for numero, mes in enumerate(MESES, start=1):
            self.filtro_cumple.addItem(f"Cumplen en {mes.lower()}", numero)
        self.filtro_sin_asistir = QComboBox()
        self.filtro_sin_asistir.addItem("Sin asistir: cualquiera", None)
        for dias in DIAS_SIN_ASISTIR:
            self.filtro_sin_asistir.addItem(f"Sin asistir hace {dias} días o más", dias)
        self.filtro_sin_asistir.setToolTip("Incluye a quienes nunca han asistido.")
        self.filtro_desde = QLineEdit()
        self.filtro_desde.setPlaceholderText("dd/mm/aaaa")
        self.filtro_hasta = QLineEdit()
        self.filtro_hasta.setPlaceholderText("dd/mm/aaaa")
        for campo in (self.filtro_desde, self.filtro_hasta):
            campo.setFixedWidth(120)
            campo.editingFinished.connect(self.actualizar)
        for combo in (self.filtro_estado, self.filtro_vigencia, self.filtro_sexo,
                      self.filtro_plan, self.filtro_cumple):
            combo.currentIndexChanged.connect(lambda _: self.actualizar())
            fila.addWidget(combo)
        fila.addStretch()
        self.filtro_sin_asistir.currentIndexChanged.connect(lambda _: self.actualizar())
        segunda.addWidget(self.filtro_sin_asistir)
        segunda.addSpacing(12)
        segunda.addWidget(etiqueta("Registrados desde"))
        segunda.addWidget(self.filtro_desde)
        segunda.addWidget(etiqueta("hasta"))
        segunda.addWidget(self.filtro_hasta)
        segunda.addSpacing(12)
        limpiar = boton("Limpiar filtros")
        limpiar.clicked.connect(self.limpiar_filtros)
        segunda.addWidget(limpiar)
        segunda.addStretch()
        filas.addLayout(fila)
        filas.addLayout(segunda)
        return filas

    # --- filtros y consulta ----------------------------------------------------
    def filtros(self) -> FiltrosClientes:
        desde = leer_fecha(self.filtro_desde.text())
        hasta = leer_fecha(self.filtro_hasta.text())
        if desde and hasta and desde > hasta:
            raise ErrorValidacion("La fecha «desde» es posterior a la fecha «hasta».")
        vigencia = self.filtro_vigencia.currentData()
        return FiltrosClientes(
            texto=self.campo_busqueda.text(),
            estado=self.filtro_estado.currentData(),
            vigencia=Vigencia(vigencia) if vigencia and vigencia != AL_DIA else None,
            al_dia=vigencia == AL_DIA,
            sexo=self.filtro_sexo.currentData(),
            plan_id=self.filtro_plan.currentData(),
            registro_desde=desde, registro_hasta=hasta,
            cumple_mes=self.filtro_cumple.currentData(),
            sin_asistir_dias=self.filtro_sin_asistir.currentData(),
        )

    def _crear_resumen(self) -> QHBoxLayout:
        """Contadores siempre visibles; un clic filtra la lista (clientes activos)."""
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.botones_resumen: dict[str, QPushButton] = {}
        for clave, color in (("al_dia", COLOR_VIGENCIA[Vigencia.VIGENTE]),
                             ("por_vencer", COLOR_VIGENCIA[Vigencia.POR_VENCER]),
                             ("vencidos", COLOR_VIGENCIA[Vigencia.VENCIDA]),
                             ("sin_membresia", COLOR_VIGENCIA[Vigencia.SIN_MEMBRESIA]),
                             ("inactivos", "#b42318"), ("total", "#1d2733")):
            b = boton("")
            b.setStyleSheet(f"QPushButton {{ color: {color}; font-weight: 600; }}")
            b.setToolTip("Clic para ver estos clientes en la lista.")
            b.clicked.connect(lambda _=False, c=clave: self.filtrar_resumen(c))
            self.botones_resumen[clave] = b
            fila.addWidget(b)
        fila.addStretch()
        return fila

    def refrescar_resumen(self) -> None:
        if not self.desbloqueado:
            return
        try:
            r = self._servicios.clientes.resumen(self._actual, self.autorizacion)
        except ErrorNegocio:
            return
        self.resumen = r
        miles = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
        textos = {
            "al_dia": f"✔ Al día: {miles(r.al_dia)}",
            "por_vencer": f"⚠ Por vencer: {miles(r.por_vencer)}",
            "vencidos": f"✖ Vencidos: {miles(r.vencidos)}",
            "sin_membresia": f"— Sin membresía: {miles(r.sin_membresia)}",
            "inactivos": f"Inactivos: {miles(r.inactivos)}",
            "total": f"Total: {miles(r.total)}",
        }
        for clave, texto in textos.items():
            self.botones_resumen[clave].setText(texto)

    def filtrar_resumen(self, clave: str) -> None:
        estado, vigencia = {
            "al_dia": ("activo", AL_DIA),
            "por_vencer": ("activo", Vigencia.POR_VENCER.value),
            "vencidos": ("activo", Vigencia.VENCIDA.value),
            "sin_membresia": ("activo", Vigencia.SIN_MEMBRESIA.value),
            "inactivos": ("inactivo", None),
            "total": (None, None),
        }[clave]
        self.limpiar_filtros(actualizar=False)
        for combo, valor in ((self.filtro_estado, estado), (self.filtro_vigencia, vigencia)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(valor)))
            combo.blockSignals(False)
        self.actualizar()

    def recargar(self) -> None:
        """Después de un cambio de datos: lista y contadores."""
        self.refrescar_resumen()
        self.actualizar()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        if self.desbloqueado:
            # Recepción o Pagos pudieron cambiar vigencias mientras estaba oculta.
            self.refrescar_resumen()
        else:
            # Primero se ve el candado y enseguida se pide la clave.
            QTimer.singleShot(0, self.desbloquear)

    def hideEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().hideEvent(evento)
        self.bloquear()

    def actualizar(self) -> None:
        self._espera.stop()
        if not self.desbloqueado:
            return
        try:
            filtros = self.filtros()
        except (ValueError, ErrorNegocio) as e:
            self.mensaje.setText(str(e))
            self.mensaje.setStyleSheet("color: #b42318; font-weight: 600;")
            return
        self.mensaje.setStyleSheet("")
        try:
            self.modelo.consultar(filtros)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        total = self.modelo.total
        self.mensaje.setText(
            "Ningún cliente coincide con la búsqueda." if total == 0
            else f"{total:,} cliente{'s' if total != 1 else ''}".replace(",", ".")
        )
        if total:
            self.tabla.selectRow(0)

    def limpiar_filtros(self, actualizar: bool = True) -> None:
        for combo in (self.filtro_estado, self.filtro_vigencia, self.filtro_sexo,
                      self.filtro_plan, self.filtro_cumple, self.filtro_sin_asistir):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.filtro_desde.clear()
        self.filtro_hasta.clear()
        self.campo_busqueda.blockSignals(True)
        self.campo_busqueda.clear()
        self.campo_busqueda.blockSignals(False)
        if actualizar:
            self.actualizar()

    def enfocar_busqueda(self) -> None:
        self.campo_busqueda.setFocus()
        self.campo_busqueda.selectAll()

    def _enter_en_busqueda(self) -> None:
        self.actualizar()
        if self.modelo.total == 1:
            self.ver_ficha()
        elif self.modelo.total:
            self.tabla.setFocus()

    # --- acciones -------------------------------------------------------------
    def cliente_seleccionado(self) -> int | None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return None
        return self.modelo.filas[filas[0].row()].id

    def ver_ficha(self) -> None:
        cliente_id = self.cliente_seleccionado()
        if cliente_id is not None:
            self.abrir_ficha.emit(cliente_id)

    def nuevo(self) -> None:
        from gimnasio.ui.cliente_formulario import DialogoCliente

        dialogo = DialogoCliente(self._servicios, self._actual, padre=self)
        if self._ejecutar(dialogo) and dialogo.ficha:
            self.cobrar_inscripcion(dialogo.ficha, dialogo.quiere_casillero, dialogo.autorizacion)
            self.recargar()
            self.abrir_ficha.emit(dialogo.ficha.id)

    def cobrar_inscripcion(self, ficha, con_casillero: bool, autorizacion=None):
        """Después de inscribir: cobra la mensualidad y, si quiere, el casillero en el mismo
        recibo. Si el cliente ya tiene membresía vigente (p. ej. reactivado) no se abre."""
        from gimnasio.ui.pagos import DialogoMembresia

        if not self._actual.puede(Permiso.REGISTRAR_PAGOS) or ficha.estado != "activo":
            return None
        if ficha.vigencia in (Vigencia.VIGENTE, Vigencia.POR_VENCER) and not con_casillero:
            return None
        try:
            dialogo = DialogoMembresia(self._servicios, self._actual, ficha.id,
                                       f"{ficha.nombres} {ficha.apellidos}", padre=self,
                                       con_casillero=con_casillero,
                                       titulo="Inscripción: pagar mensualidad",
                                       autorizacion=autorizacion)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        self._ejecutar(dialogo)
        return dialogo

    def exportar(self, formato: str, ruta: str | None = None) -> int | None:
        try:
            filtros = self.filtros()
        except (ValueError, ErrorNegocio) as e:
            mostrar_error(self, e if isinstance(e, ErrorNegocio) else ErrorValidacion(str(e)))
            return None
        if ruta is None:
            extension = "Excel (*.xlsx)" if formato == "xlsx" else "PDF (*.pdf)"
            sugerido = str(Path.home() / f"clientes_{date.today():%Y%m%d}.{formato}")
            ruta, _ = QFileDialog.getSaveFileName(self, "Guardar lista de clientes",
                                                  sugerido, extension)
            if not ruta:
                return None
            if not ruta.lower().endswith(f".{formato}"):
                ruta += f".{formato}"
        # Con 12.000 clientes tarda unos segundos (Excel ~3 s, PDF ~5 s).
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = self._servicios.clientes.exportar(
                self._actual, filtros, ruta, formato,
                orden=self.modelo.orden, descendente=self.modelo.descendente,
            )
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return None
        except OSError:
            mostrar_error(self, ErrorValidacion(
                "No se pudo guardar el archivo. Revise que no esté abierto en otro programa."
            ))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.mensaje.setText(f"Se exportaron {n} clientes a {Path(ruta).name}.")
        return n

    def _menu_contextual(self, posicion) -> None:
        indice = self.tabla.indexAt(posicion)
        if not indice.isValid():
            return
        self.tabla.selectRow(indice.row())
        fila = self.modelo.filas[indice.row()]
        menu = QMenu(self)
        ver = QAction("Ver ficha", menu)
        ver.triggered.connect(self.ver_ficha)
        menu.addAction(ver)
        editar = QAction("Modificar datos", menu)
        editar.triggered.connect(lambda: self._modificar(fila.id))
        menu.addAction(editar)
        if self._actual.puede(Permiso.ACTIVAR_CLIENTES):
            menu.addSeparator()
            from gimnasio.ui.cliente_ficha import cambiar_estado

            texto = "Inactivar cliente…" if fila.estado == "activo" else "Activar cliente"
            estado = QAction(texto, menu)
            estado.triggered.connect(
                lambda: cambiar_estado(self, self._servicios, self._actual, fila.id)
                and self.recargar()
            )
            menu.addAction(estado)
        menu.exec(self.tabla.viewport().mapToGlobal(posicion))

    def _modificar(self, cliente_id: int) -> None:
        from gimnasio.ui.cliente_formulario import DialogoCliente

        try:
            ficha = self._servicios.clientes.obtener_ficha(self._actual, cliente_id)
        except ErrorNegocio as e:
            mostrar_error(self, e)
            return
        if DialogoCliente(self._servicios, self._actual, ficha, padre=self).exec():
            self.recargar()


class DialogoElegirCliente(QDialog):
    """Resultados de la búsqueda global cuando hay más de un cliente. Enter abre la ficha."""

    def __init__(self, filas: list[FilaCliente], texto: str, padre: QWidget | None = None,
                 texto_boton: str = "Abrir ficha"):
        super().__init__(padre)
        self.setWindowTitle("Elegir cliente")
        self.setMinimumWidth(620)
        self.cliente_id: int | None = None
        capa = QVBoxLayout(self)
        capa.setContentsMargins(20, 16, 20, 16)
        capa.addWidget(etiqueta(f"Clientes que coinciden con «{texto}»:", "textoSuave"))
        self.lista = QListWidget()
        for f in filas:
            estado = "  ·  INACTIVO" if f.estado == "inactivo" else ""
            item = QListWidgetItem(
                f"{f.codigo}   {f.nombre_completo}   ·   {f.tipo_documento} {f.documento}"
                f"   ·   {texto_vigencia(f.vigencia, f.dias_restantes)}{estado}"
            )
            item.setData(Qt.ItemDataRole.UserRole, f.id)
            self.lista.addItem(item)
        self.lista.setCurrentRow(0)
        self.lista.itemActivated.connect(lambda _: self.elegir())
        capa.addWidget(self.lista)
        botones = QHBoxLayout()
        botones.addStretch()
        cancelar = boton("Cancelar")
        abrir = boton(texto_boton, principal=True)
        cancelar.clicked.connect(self.reject)
        abrir.clicked.connect(self.elegir)
        botones.addWidget(cancelar)
        botones.addWidget(abrir)
        capa.addLayout(botones)
        self.lista.setFocus()

    def elegir(self) -> None:
        item = self.lista.currentItem()
        if item:
            self.cliente_id = item.data(Qt.ItemDataRole.UserRole)
            self.accept()
