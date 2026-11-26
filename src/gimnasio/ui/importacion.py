"""Pestaña «Importar datos» de Configuración (solo administrador, Fase 10).

Trae los clientes, vigencias, asistencias, casilleros e invitados del programa
anterior (carpeta DB3 con archivos .DBF). Primero se prueba sin guardar y se revisa
el informe en Excel; después se importa de verdad, una sola vez.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

from gimnasio.formato import fecha_hora_local
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.importacion import ResultadoImportacion
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.comunes import boton, confirmar, etiqueta, mostrar_error

TEXTO_AYUDA = (
    "Elija la carpeta DB3 del programa anterior (la que tiene ENCLIE.DBF). La carpeta "
    "original no se modifica: se copia y se lee la copia.\n"
    "1. Pulse «Probar sin guardar» y revise el informe en Excel (hoja «Problemas»).\n"
    "2. Si todo está bien, pulse «Importar de verdad». Antes se hace una copia de "
    "seguridad. Solo se puede importar una vez."
)


class PestanaImportacion(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.resultado: ResultadoImportacion | None = None
        capa = QVBoxLayout(self)
        capa.addWidget(etiqueta(TEXTO_AYUDA))
        fila = QHBoxLayout()
        self.campo_carpeta = QLineEdit()
        self.campo_carpeta.setPlaceholderText("Carpeta DB3 del programa anterior")
        self.boton_elegir = boton("Elegir carpeta…")
        self.boton_elegir.clicked.connect(self.elegir_carpeta)
        fila.addWidget(self.campo_carpeta, 1)
        fila.addWidget(self.boton_elegir)
        capa.addLayout(fila)
        botones = QHBoxLayout()
        self.boton_probar = boton("Probar sin guardar", principal=True)
        self.boton_probar.clicked.connect(self.probar)
        self.boton_importar = boton("Importar de verdad")
        self.boton_importar.clicked.connect(self.importar)
        self.boton_informe = boton("Abrir informe en Excel")
        self.boton_informe.clicked.connect(self.abrir_informe)
        self.boton_informe.setEnabled(False)
        for b in (self.boton_probar, self.boton_importar, self.boton_informe):
            botones.addWidget(b)
        botones.addStretch(1)
        capa.addLayout(botones)
        self.estado = etiqueta("")
        capa.addWidget(self.estado)
        self.resumen = QPlainTextEdit()
        self.resumen.setReadOnly(True)
        capa.addWidget(self.resumen, 1)
        self.actualizar_estado()

    def actualizar_estado(self) -> None:
        try:
            cuando = self._servicios.importacion.ya_importado(self._actual)
        except ErrorNegocio:
            cuando = None
        self.boton_importar.setEnabled(cuando is None)
        self.estado.setText(
            f"Los datos del programa anterior ya se importaron el {fecha_hora_local(cuando)}."
            if cuando else "Aún no se han importado los datos del programa anterior.")

    def elegir_carpeta(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(
            self, "Carpeta DB3 del programa anterior", self.campo_carpeta.text())
        if carpeta:
            self.campo_carpeta.setText(carpeta)

    def _carpeta(self) -> Path | None:
        texto = self.campo_carpeta.text().strip()
        if not texto:
            mostrar_error(self, ErrorNegocio("Elija la carpeta DB3 del programa anterior."))
            return None
        return Path(texto)

    def probar(self) -> None:
        self._ejecutar(guardar=False)

    def importar(self) -> None:
        if self._carpeta() is None:
            return
        if not confirmar(
            self, "Importar datos",
            "Se van a guardar los clientes, vigencias, asistencias, casilleros e invitados "
            "del programa anterior. Antes se hará una copia de seguridad. Esto se hace una "
            "sola vez. ¿Ya revisó el informe de la prueba?",
        ):
            return
        self._ejecutar(guardar=True)

    def _ejecutar(self, guardar: bool) -> None:
        carpeta = self._carpeta()
        if carpeta is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.resultado = self._servicios.importacion.importar(
                self._actual, carpeta, guardar=guardar)
        except ErrorNegocio as e:
            QApplication.restoreOverrideCursor()
            mostrar_error(self, e)
            return
        QApplication.restoreOverrideCursor()
        texto = self.resultado.texto
        if self.resultado.ruta_informe:
            texto += f"\n\nInforme: {self.resultado.ruta_informe}"
        if self.resultado.ruta_backup:
            texto += f"\nCopia de seguridad previa: {self.resultado.ruta_backup}"
        self.resumen.setPlainText(texto)
        self.boton_informe.setEnabled(self.resultado.ruta_informe is not None)
        self.actualizar_estado()

    def abrir_informe(self) -> None:
        if self.resultado and self.resultado.ruta_informe:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.resultado.ruta_informe)))
