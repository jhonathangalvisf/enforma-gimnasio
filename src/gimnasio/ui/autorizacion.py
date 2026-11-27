"""Ventana para que un administrador escriba su clave y autorice a Recepción a cobrar,
inscribir o abrir el módulo de Pagos (se pide cada vez). Para cobrar o inscribir, el
administrador no la ve (`pedir_autorizacion`); para ver los pagos se pide a todos
(`pedir_clave_siempre`)."""

from __future__ import annotations

from PySide6.QtWidgets import QLineEdit, QWidget

from gimnasio.servicios.autorizaciones import (
    DESCRIPCIONES, Autorizacion, necesita_autorizacion,
)
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.errores import ErrorNegocio
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.comunes import boton
from gimnasio.ui.dialogos import _DialogoBase


class DialogoClaveAdmin(_DialogoBase):
    def __init__(self, servicios: Servicios, actual: UsuarioActual, para: str,
                 padre: QWidget | None = None):
        super().__init__("Clave de administrador",
                         f"Para {DESCRIPCIONES[para]} se necesita que un administrador escriba "
                         "su usuario y contraseña.", padre)
        self._servicios, self._actual, self._para = servicios, actual, para
        self.autorizacion: Autorizacion | None = None
        self.campo_usuario = QLineEdit()
        self.campo_usuario.setPlaceholderText("usuario del administrador")
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.EchoMode.Password)
        self.formulario.addRow("Administrador", self.campo_usuario)
        self.formulario.addRow("Contraseña", self.campo_clave)
        cancelar = boton("Cancelar")
        self.boton_autorizar = boton("Autorizar", principal=True)
        self._botones.addWidget(cancelar)
        self._botones.addWidget(self.boton_autorizar)
        cancelar.clicked.connect(self.reject)
        self.boton_autorizar.clicked.connect(self.autorizar)
        self.campo_usuario.returnPressed.connect(self.campo_clave.setFocus)
        self.campo_clave.returnPressed.connect(self.autorizar)
        self.campo_usuario.setFocus()

    def autorizar(self) -> None:
        try:
            self.autorizacion = self._servicios.autorizaciones.autorizar(
                self._actual, self.campo_usuario.text(), self.campo_clave.text(), self._para)
        except ErrorNegocio as e:
            self.campo_clave.clear()
            self.campo_clave.setFocus()
            self.mostrar_error(str(e))
            return
        self.accept()


def _pedir_con_dialogo(padre: QWidget | None, servicios: Servicios, actual: UsuarioActual,
                       para: str) -> tuple[bool, Autorizacion | None]:
    dialogo = DialogoClaveAdmin(servicios, actual, para, padre)
    if dialogo.exec() and dialogo.autorizacion is not None:
        return True, dialogo.autorizacion
    return False, None


# Las pruebas reemplazan esta función para no abrir la ventana.
PEDIR = _pedir_con_dialogo


def pedir_autorizacion(padre: QWidget | None, servicios: Servicios, actual: UsuarioActual,
                       para: str) -> tuple[bool, Autorizacion | None]:
    """(seguir, autorización). Para un administrador: (True, None) sin preguntar.
    Si Recepción cancela: (False, None)."""
    if not necesita_autorizacion(actual):
        return True, None
    return PEDIR(padre, servicios, actual, para)


def pedir_clave_siempre(padre: QWidget | None, servicios: Servicios, actual: UsuarioActual,
                        para: str) -> tuple[bool, Autorizacion | None]:
    """Como `pedir_autorizacion`, pero pregunta también al administrador (para abrir lo
    que no debe quedar a la vista de cualquiera, como los pagos). Para un administrador
    los servicios no exigen el permiso devuelto: la clave cuida la sesión abierta."""
    return PEDIR(padre, servicios, actual, para)


def asegurar_autorizacion(dialogo, para: str) -> bool:
    """Para los diálogos de cobro e inscripción: pide la clave una vez y la guarda en
    `dialogo._autorizacion` hasta que la operación quede guardada (si falla por otro
    motivo, p. ej. falta la referencia, no se vuelve a pedir). Devuelve False si se
    canceló."""
    if getattr(dialogo, "_autorizacion", None) is not None:
        return True
    ok, autorizacion = pedir_autorizacion(dialogo, dialogo._servicios, dialogo._actual, para)
    dialogo._autorizacion = autorizacion
    return ok


def olvidar_autorizacion_si_falla(dialogo, error: Exception) -> None:
    """Si el error fue de la autorización (venció o ya se usó), la próxima vez se pide."""
    from gimnasio.servicios.autorizaciones import ErrorAutorizacion

    if isinstance(error, ErrorAutorizacion):
        dialogo._autorizacion = None
