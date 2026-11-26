"""Diálogos de acceso: inicio de sesión, primer administrador y cambio de contraseña."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from gimnasio import __version__
from gimnasio.servicios.claves import LONGITUD_MINIMA
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio, ErrorValidacion
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.comunes import boton, etiqueta


def campo_clave(marcador: str = "") -> QLineEdit:
    c = QLineEdit()
    c.setEchoMode(QLineEdit.EchoMode.Password)
    c.setPlaceholderText(marcador)
    return c


class _DialogoBase(QDialog):
    def __init__(self, titulo: str, subtitulo: str, padre: QWidget | None = None):
        super().__init__(padre)
        self.setWindowTitle(titulo)
        self.setMinimumWidth(420)
        self._capa = QVBoxLayout(self)
        self._capa.setContentsMargins(28, 24, 28, 24)
        self._capa.setSpacing(12)
        self._capa.addWidget(etiqueta(titulo, "tituloPantalla"))
        if subtitulo:
            self._capa.addWidget(etiqueta(subtitulo, "textoSuave"))
        self.formulario = QFormLayout()
        self.formulario.setSpacing(10)
        self._capa.addLayout(self.formulario)
        self.error = etiqueta("", "mensajeError")
        self.error.hide()
        self._capa.addWidget(self.error)
        self._botones = QHBoxLayout()
        self._botones.addStretch()
        self._capa.addLayout(self._botones)

    def mostrar_error(self, texto: str) -> None:
        self.error.setText(texto)
        self.error.show()


class DialogoLogin(_DialogoBase):
    """Usuario y contraseña. Enter en el usuario pasa a la clave; Enter en la clave entra."""

    def __init__(self, servicios: Servicios, nombre_gimnasio: str = "Enforma",
                 aviso: str = "", padre: QWidget | None = None):
        super().__init__(nombre_gimnasio, "Inicie sesión para continuar.", padre)
        self.setWindowTitle(f"{nombre_gimnasio} — Iniciar sesión")
        self._servicios = servicios
        self.usuario_actual: UsuarioActual | None = None
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("usuario")
        self.campo_clave = campo_clave("contraseña")
        self.formulario.addRow("Usuario", self.campo_usuario)
        self.formulario.addRow("Contraseña", self.campo_clave)
        if aviso:
            self.mostrar_error(aviso)
        self.boton_entrar = boton("Entrar", principal=True)
        self.boton_salir = boton("Salir")
        self._botones.addWidget(self.boton_salir)
        self._botones.addWidget(self.boton_entrar)
        self.boton_entrar.clicked.connect(self.entrar)
        self.boton_salir.clicked.connect(self.reject)
        self.campo_usuario.returnPressed.connect(self.campo_clave.setFocus)
        self.campo_clave.returnPressed.connect(self.entrar)
        self._capa.addWidget(etiqueta(f"Versión {__version__}", "textoSuave"))
        self.campo_usuario.setFocus()

    def entrar(self) -> None:
        if not self.campo_usuario.text().strip() or not self.campo_clave.text():
            self.mostrar_error("Escriba el usuario y la contraseña.")
            return
        try:
            self.usuario_actual = self._servicios.sesion.iniciar_sesion(
                self.campo_usuario.text(), self.campo_clave.text()
            )
        except ErrorNegocio as e:
            self.campo_clave.clear()
            self.campo_clave.setFocus()
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoPrimerAdministrador(_DialogoBase):
    """Solo aparece cuando la base no tiene ningún usuario (primer arranque)."""

    def __init__(self, servicios: Servicios, padre: QWidget | None = None):
        super().__init__(
            "Bienvenido a Enforma",
            "Es la primera vez que se abre el sistema. Cree la cuenta del administrador: "
            "con ella podrá crear después los usuarios de recepción.",
            padre,
        )
        self._servicios = servicios
        self.usuario_actual: UsuarioActual | None = None
        self.campo_nombre = QLineEdit()
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("por ejemplo: admin")
        self.campo_clave = campo_clave(f"mínimo {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = campo_clave()
        self.formulario.addRow("Nombre completo", self.campo_nombre)
        self.formulario.addRow("Usuario", self.campo_usuario)
        self.formulario.addRow("Contraseña", self.campo_clave)
        self.formulario.addRow("Repetir contraseña", self.campo_confirmar)
        self.boton_crear = boton("Crear administrador", principal=True)
        cancelar = boton("Salir")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_crear)
        cancelar.clicked.connect(self.reject)
        self.boton_crear.clicked.connect(self.crear)
        self.campo_confirmar.returnPressed.connect(self.crear)

    def crear(self) -> None:
        try:
            if self.campo_clave.text() != self.campo_confirmar.text():
                raise ErrorValidacion("Las contraseñas no coinciden.")
            self.usuario_actual = self._servicios.usuarios.crear_primer_administrador(
                self.campo_nombre.text(), self.campo_usuario.text(), self.campo_clave.text()
            )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()


class DialogoCambiarClave(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, obligatorio: bool = False,
                 padre: QWidget | None = None):
        super().__init__(
            "Cambiar contraseña",
            "El administrador le asignó una contraseña temporal. Elija una nueva para continuar."
            if obligatorio else "",
            padre,
        )
        self._servicios = servicios
        self._actual = actual
        self.usuario_actual: UsuarioActual | None = None
        self.campo_actual = campo_clave()
        self.campo_nueva = campo_clave(f"mínimo {LONGITUD_MINIMA} caracteres")
        self.campo_confirmar = campo_clave()
        self.formulario.addRow("Contraseña actual", self.campo_actual)
        self.formulario.addRow("Nueva contraseña", self.campo_nueva)
        self.formulario.addRow("Repetir nueva", self.campo_confirmar)
        guardar = boton("Guardar", principal=True)
        cancelar = boton("Cerrar sesión" if obligatorio else "Cancelar")
        self._botones.addWidget(cancelar)
        self._botones.addWidget(guardar)
        cancelar.clicked.connect(self.reject)
        guardar.clicked.connect(self.guardar)
        self.campo_confirmar.returnPressed.connect(self.guardar)

    def guardar(self) -> None:
        try:
            if self.campo_nueva.text() != self.campo_confirmar.text():
                raise ErrorValidacion("Las contraseñas nuevas no coinciden.")
            self.usuario_actual = self._servicios.sesion.cambiar_clave_propia(
                self._actual, self.campo_actual.text(), self.campo_nueva.text()
            )
        except ErrorNegocio as e:
            self.mostrar_error(str(e))
            return
        self.accept()

