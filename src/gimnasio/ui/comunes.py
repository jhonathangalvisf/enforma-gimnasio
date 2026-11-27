"""Utilidades compartidas por las pantallas."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHeaderView, QLabel, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QWidget,
)

from gimnasio.servicios.errores import ErrorNegocio


def boton(texto: str, principal: bool = False) -> QPushButton:
    b = QPushButton(texto)
    # Sin botón "por defecto": Enter lo manejan los campos (p. ej. usuario -> contraseña),
    # así un Enter de más no dispara acciones por accidente.
    b.setAutoDefault(False)
    if principal:
        b.setProperty("principal", True)
    return b


def etiqueta(texto: str, nombre_objeto: str | None = None) -> QLabel:
    e = QLabel(texto)
    if nombre_objeto:
        e.setObjectName(nombre_objeto)
    e.setWordWrap(True)
    return e


def mostrar_error(padre: QWidget | None, error: Exception) -> None:
    """Errores de negocio se muestran tal cual; los inesperados con un texto general."""
    if isinstance(error, ErrorNegocio):
        texto = str(error)
    else:
        texto = "Ocurrió un error inesperado. Intente de nuevo; si continúa, avise al administrador."
    QMessageBox.warning(padre, "No se pudo completar", texto)


def confirmar(padre: QWidget | None, titulo: str, texto: str) -> bool:
    respuesta = QMessageBox.question(
        padre, titulo, texto,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return respuesta == QMessageBox.StandardButton.Yes


class Tabla(QTableWidget):
    """Tabla de solo lectura cuyas columnas se ajustan al contenido UNA vez por llenado.

    Con el modo «ajustar al contenido» de Qt, cada celda que se escribe en una tabla
    visible vuelve a medir hasta 1.000 filas de todas las columnas y a recalcular la
    pantalla: llenar 300 pagos tomaba ~25 s y la aplicación parecía congelada al cambiar
    de módulo. Aquí las columnas son de ancho normal (el usuario puede moverlas) y, al
    cambiar el número de filas, se programa un solo ajuste para cuando termine el llenado.
    """

    def __init__(self, filas: int, columnas: int):
        super().__init__(filas, columnas)
        self._ajuste_pendiente = False

    def setRowCount(self, filas: int) -> None:  # noqa: N802 (nombre de Qt)
        super().setRowCount(filas)
        if filas and not self._ajuste_pendiente:
            self._ajuste_pendiente = True
            QTimer.singleShot(0, self, self.ajustar_columnas)

    def ajustar_columnas(self) -> None:
        """Ancho de cada columna según su contenido (salvo las que se estiran)."""
        self._ajuste_pendiente = False
        cabecera = self.horizontalHeader()
        ultima = self.columnCount() - 1
        for columna in range(self.columnCount()):
            if cabecera.sectionResizeMode(columna) != QHeaderView.ResizeMode.Interactive:
                continue
            if columna == ultima and cabecera.stretchLastSection():
                continue
            self.resizeColumnToContents(columna)


def tabla(columnas: list[str]) -> QTableWidget:
    t = Tabla(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    t.horizontalHeader().setMinimumSectionSize(40)
    t.setSortingEnabled(True)
    return t


ROL_ORDEN = Qt.ItemDataRole.UserRole + 1


class _Celda(QTableWidgetItem):
    """Celda que ordena por una clave propia (p. ej. la fecha real, no el texto dd/mm/aaaa)."""

    def __lt__(self, otra: QTableWidgetItem) -> bool:
        a, b = self.data(ROL_ORDEN), otra.data(ROL_ORDEN)
        if a is not None and b is not None:
            return a < b
        return self.text().lower() < otra.text().lower()


def celda(texto: str, dato=None, orden=None) -> QTableWidgetItem:
    item = _Celda(texto)
    if dato is not None:
        item.setData(Qt.ItemDataRole.UserRole, dato)
    if orden is not None:
        item.setData(ROL_ORDEN, orden)
    return item


# --- pantallas pequeñas y escalado de Windows -----------------------------------------

def area_disponible(ventana: QWidget):
    """Parte de la pantalla que puede usar la ventana (sin la barra de tareas)."""
    pantalla = ventana.screen()
    return pantalla.availableGeometry() if pantalla is not None else None


def ajustar_a_pantalla(ventana: QWidget, margen: int = 16) -> None:
    """Si la ventana no cabe en la pantalla (portátil pequeño o Windows con escalado al
    125 % o 150 %), la reduce y la mueve para que se vea completa."""
    area = area_disponible(ventana)
    if area is None:
        return
    max_ancho, max_alto = area.width() - margen, area.height() - margen
    if ventana.minimumWidth() > max_ancho:
        ventana.setMinimumWidth(max_ancho)
    if ventana.minimumHeight() > max_alto:
        ventana.setMinimumHeight(max_alto)
    sugerido = ventana.minimumSizeHint()
    if sugerido.width() > max_ancho and ventana.minimumWidth() == 0:
        ventana.setMinimumWidth(max_ancho)
    if sugerido.height() > max_alto and ventana.minimumHeight() == 0:
        ventana.setMinimumHeight(max_alto)
    ancho, alto = min(ventana.width(), max_ancho), min(ventana.height(), max_alto)
    if (ancho, alto) != (ventana.width(), ventana.height()):
        ventana.resize(ancho, alto)
    marco = ventana.frameGeometry()
    x = min(max(marco.x(), area.left()), area.right() - marco.width() + 1)
    y = min(max(marco.y(), area.top()), area.bottom() - marco.height() + 1)
    if (x, y) != (marco.x(), marco.y()):
        ventana.move(max(x, area.left()), max(y, area.top()))


class FiltroAjusteDialogos(QObject):
    """Instalado en la aplicación: cada diálogo que se abre queda dentro de la pantalla."""

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (nombre de Qt)
        if (evento.type() == QEvent.Type.Show and isinstance(objeto, QDialog)
                and objeto.isWindow()):
            ajustar_a_pantalla(objeto)
        return False


class AreaPantalla(QScrollArea):
    """Área desplazable que contiene una pantalla del menú.

    La pantalla ocupa exactamente el espacio visible; solo si de verdad no cabe (su
    tamaño mínimo es mayor que el espacio) crece hasta ese mínimo y aparecen las barras.
    Se calcula a mano porque el ajuste automático de Qt (`setWidgetResizable`) a veces
    deja la pantalla mucho más ancha de lo visible cuando hay textos que se parten en
    varias líneas, y entonces lo de la derecha y lo de abajo queda cortado."""

    def __init__(self, pantalla: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # el foco sigue en la pantalla
        self.setWidget(pantalla)
        pantalla.installEventFilter(self)
        self._ajustando = False

    def ajustar(self) -> None:
        pantalla = self.widget()
        if pantalla is None or self._ajustando:
            return
        self._ajustando = True
        try:
            for _ in range(3):  # al aparecer una barra el espacio visible cambia
                visible = self.viewport().size()
                minimo = pantalla.minimumSizeHint().expandedTo(pantalla.minimumSize())
                ancho = max(visible.width(), minimo.width())
                alto = max(visible.height(), minimo.height())
                if (ancho, alto) == (pantalla.width(), pantalla.height()):
                    break
                pantalla.resize(ancho, alto)
        finally:
            self._ajustando = False

    def resizeEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().resizeEvent(evento)
        self.ajustar()

    def showEvent(self, evento) -> None:  # noqa: N802 (nombre de Qt)
        super().showEvent(evento)
        self.ajustar()

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (nombre de Qt)
        if objeto is self.widget() and evento.type() == QEvent.Type.LayoutRequest:
            QTimer.singleShot(0, self.ajustar)
        return False


class PilaPantallas(QStackedWidget):
    """Las pantallas del menú, cada una dentro de un área con barras de desplazamiento:
    si una pantalla no cabe, aparecen las barras en lugar de quedar cortada.
    `currentWidget()` devuelve la pantalla, no el área que la contiene."""

    def agregar(self, pantalla: QWidget) -> int:
        return self.addWidget(AreaPantalla(pantalla))

    def pantalla(self, indice: int) -> QWidget | None:
        w = self.widget(indice)
        return w.widget() if isinstance(w, QScrollArea) else w

    def currentWidget(self) -> QWidget | None:  # noqa: N802 (nombre de Qt)
        return self.pantalla(self.currentIndex())
