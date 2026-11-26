"""Utilidades compartidas por las pantallas."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

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
