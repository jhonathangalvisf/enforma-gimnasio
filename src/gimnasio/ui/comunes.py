"""Utilidades compartidas por las pantallas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QWidget,
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


def tabla(columnas: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
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
