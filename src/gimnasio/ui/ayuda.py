"""Módulo Ayuda (sección 3.9): lista de temas, buscador con resaltado y ayuda con F1.

- `VisorAyuda`: temas a la izquierda (o resultados de la búsqueda) y el texto a la derecha.
- `PantallaAyuda`: el visor dentro de la ventana principal (menú → Ayuda).
- `DialogoAyuda`: ventana aparte que abre F1 sin perder lo que se estaba haciendo.
- `tema_para()`: decide qué tema abre F1 según la ventana o pantalla activa.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

from gimnasio.servicios.ayuda import ESQUEMA_ENLACE, TEMA_INICIO, palabras
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.texto import normalizar
from gimnasio.ui.comunes import etiqueta

COLOR_RESALTADO = "#ffe08a"

# Tema de ayuda según el archivo de la pantalla o diálogo (gimnasio/ui/<archivo>.py).
TEMA_POR_ARCHIVO = {
    "recepcion": "recepcion",
    "clientes": "clientes",
    "cliente_ficha": "clientes",
    "cliente_formulario": "clientes",
    "asistencia": "asistencia",
    "casilleros": "casilleros",
    "invitados": "invitados",
    "pagos": "pagos",
    "reportes": "reportes",
    "configuracion": "configuracion",
    "dialogos": TEMA_INICIO,
}


def tema_para(widget: QWidget | None, subir: bool = True) -> str | None:
    """Recorre el widget y sus padres hasta encontrar a qué módulo pertenece.

    Un widget puede definir `TEMA_AYUDA` (atributo) o `tema_ayuda()` (método) para elegir
    su tema; si no, se usa el archivo de `gimnasio/ui/` donde está su clase.
    Con `subir=False` solo mira el widget dado, sin sus padres.
    """
    while widget is not None:
        metodo = getattr(widget, "tema_ayuda", None)
        if callable(metodo):
            tema = metodo()
            if tema:
                return tema
        tema = getattr(widget, "TEMA_AYUDA", None)
        if tema:
            return tema
        modulo = type(widget).__module__
        if modulo.startswith("gimnasio.ui."):
            tema = TEMA_POR_ARCHIVO.get(modulo.rsplit(".", 1)[-1])
            if tema:
                return tema
        widget = widget.parentWidget() if subir else None
    return None


def _sin_tildes_mismo_largo(texto: str) -> str:
    """Normaliza letra por letra para que cada posición siga correspondiendo al original."""
    return "".join((normalizar(c) or c)[:1] for c in texto)


class VisorAyuda(QWidget):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, tema: str = TEMA_INICIO):
        super().__init__()
        self._servicios, self._actual = servicios, actual
        self.tema_actual: str | None = None
        self._temas = {t.clave: t.titulo for t in servicios.ayuda.temas(actual)}

        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 0, 0, 0)
        izquierda = QVBoxLayout()
        self.buscador = QLineEdit()
        self.buscador.setObjectName("buscadorAyuda")
        self.buscador.setPlaceholderText("Buscar en la ayuda…")
        self.buscador.setClearButtonEnabled(True)
        self.lista = QListWidget()
        self.lista.setObjectName("temasAyuda")
        self.resumen = etiqueta("", "textoSuave")
        izquierda.addWidget(self.buscador)
        izquierda.addWidget(self.lista, 1)
        izquierda.addWidget(self.resumen)
        panel = QWidget()
        panel.setLayout(izquierda)
        panel.setFixedWidth(260)
        self.texto = QTextBrowser()
        self.texto.setObjectName("textoAyuda")
        self.texto.setOpenLinks(False)
        self.texto.document().setDocumentMargin(18)
        self.texto.anchorClicked.connect(self._al_hacer_clic_enlace)
        capa.addWidget(panel)
        capa.addWidget(self.texto, 1)

        self.buscador.textChanged.connect(self.buscar)
        self.buscador.returnPressed.connect(self._enter_buscador)
        self.lista.currentItemChanged.connect(self._al_elegir)
        self.lista.itemActivated.connect(lambda _: self.texto.setFocus())
        self._llenar_temas()
        self.mostrar(tema)

    # --- temas ----------------------------------------------------------------
    def _llenar_temas(self) -> None:
        self.lista.blockSignals(True)
        self.lista.clear()
        for clave, titulo in self._temas.items():
            item = QListWidgetItem(titulo)
            item.setData(Qt.ItemDataRole.UserRole, clave)
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        self.resumen.setText("F1 abre la ayuda de la pantalla en la que esté.")

    def temas_listados(self) -> list[str]:
        return [self.lista.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.lista.count())]

    def mostrar(self, clave: str) -> None:
        clave = self._servicios.ayuda.tema_contextual(self._actual, clave)
        try:
            contenido = self._servicios.ayuda.contenido(self._actual, clave)
        except ErrorNegocio as e:
            self.texto.setPlainText(str(e))
            return
        self.tema_actual = clave
        self.texto.setMarkdown(contenido)
        self._seleccionar_en_lista(clave)
        self.resaltar(self.buscador.text())
        titulo = self._temas.get(clave, "")
        ventana = self.window()
        if isinstance(ventana, DialogoAyuda):
            ventana.setWindowTitle(f"Ayuda — {titulo}")

    def _seleccionar_en_lista(self, clave: str) -> None:
        self.lista.blockSignals(True)
        for i in range(self.lista.count()):
            if self.lista.item(i).data(Qt.ItemDataRole.UserRole) == clave:
                self.lista.setCurrentRow(i)
                break
        else:
            self.lista.setCurrentRow(-1)
        self.lista.blockSignals(False)

    def _al_elegir(self, item: QListWidgetItem | None, _anterior=None) -> None:
        if item is not None:
            self.mostrar(item.data(Qt.ItemDataRole.UserRole))

    def _al_hacer_clic_enlace(self, url: QUrl) -> None:
        if url.scheme() == ESQUEMA_ENLACE:
            self.mostrar(url.path())

    # --- búsqueda -------------------------------------------------------------
    def buscar(self, consulta: str) -> list[str]:
        """Deja en la lista solo los temas que contienen las palabras y resalta el texto."""
        if not palabras(consulta):
            self._llenar_temas()
            if self.tema_actual:
                self._seleccionar_en_lista(self.tema_actual)
            self.resaltar("")
            return []
        resultados = self._servicios.ayuda.buscar(self._actual, consulta)
        self.lista.blockSignals(True)
        self.lista.clear()
        for r in resultados:
            item = QListWidgetItem(f"{r.titulo}  ({r.coincidencias})")
            item.setData(Qt.ItemDataRole.UserRole, r.clave)
            item.setToolTip(r.fragmento)
            self.lista.addItem(item)
        self.lista.blockSignals(False)
        if not resultados:
            self.resumen.setText(f"No se encontró «{consulta.strip()}» en la ayuda.")
            self.resaltar("")
            return []
        n = len(resultados)
        self.resumen.setText(f"{n} tema{'s' if n != 1 else ''} con «{consulta.strip()}».")
        claves = [r.clave for r in resultados]
        self.mostrar(claves[0])  # el tema más relevante, con las palabras resaltadas
        return claves

    def _enter_buscador(self) -> None:
        if self.lista.count():
            if self.lista.currentRow() < 0:
                self.lista.setCurrentRow(0)
            self.lista.setFocus()

    def resaltar(self, consulta: str) -> int:
        """Pinta cada aparición de las palabras buscadas (sin importar tildes ni
        mayúsculas) y lleva la vista a la primera. Devuelve cuántas pintó."""
        buscadas = palabras(consulta)
        selecciones: list[QTextEdit.ExtraSelection] = []
        formato = QTextCharFormat()
        formato.setBackground(QColor(COLOR_RESALTADO))
        documento = self.texto.document()
        bloque = documento.begin()
        while buscadas and bloque.isValid():
            normal = _sin_tildes_mismo_largo(bloque.text())
            for palabra in buscadas:
                inicio = normal.find(palabra)
                while inicio >= 0:
                    cursor = QTextCursor(documento)
                    cursor.setPosition(bloque.position() + inicio)
                    cursor.setPosition(bloque.position() + inicio + len(palabra),
                                       QTextCursor.MoveMode.KeepAnchor)
                    seleccion = QTextEdit.ExtraSelection()
                    seleccion.cursor, seleccion.format = cursor, formato
                    selecciones.append(seleccion)
                    inicio = normal.find(palabra, inicio + len(palabra))
            bloque = bloque.next()
        self.texto.setExtraSelections(selecciones)
        if selecciones:
            primero = QTextCursor(selecciones[0].cursor)
            primero.clearSelection()
            self.texto.setTextCursor(primero)
            self.texto.ensureCursorVisible()
        else:
            self.texto.moveCursor(QTextCursor.MoveOperation.Start)
        return len(selecciones)


class PantallaAyuda(QWidget):
    """Ayuda dentro de la ventana principal (menú lateral → Ayuda)."""

    TEMA_AYUDA = TEMA_INICIO

    def __init__(self, servicios: Servicios, actual: UsuarioActual):
        super().__init__()
        capa = QVBoxLayout(self)
        capa.setContentsMargins(24, 20, 24, 20)
        capa.addWidget(etiqueta("Ayuda", "tituloPantalla"))
        capa.addWidget(etiqueta(
            "Cómo funciona cada módulo, explicado paso a paso. Elija un tema o busque una "
            "palabra.", "textoSuave"))
        self.visor = VisorAyuda(servicios, actual)
        capa.addWidget(self.visor, 1)

    def tema_ayuda(self) -> str | None:
        return self.visor.tema_actual


class DialogoAyuda(QDialog):
    """Ventana de ayuda que abre F1. No es modal: se puede seguir trabajando al lado."""

    TEMA_AYUDA = TEMA_INICIO

    def __init__(self, servicios: Servicios, actual: UsuarioActual, tema: str,
                 padre: QWidget | None = None):
        super().__init__(padre)
        self.setWindowTitle("Ayuda")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(980, 680)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(14, 14, 14, 14)
        self.visor = VisorAyuda(servicios, actual, tema)
        capa.addWidget(self.visor)
        capa.addWidget(etiqueta("Esc cierra la ayuda.", "textoSuave"))
        self.visor.mostrar(tema)  # pone el título de la ventana

    def tema_ayuda(self) -> str | None:
        return self.visor.tema_actual
