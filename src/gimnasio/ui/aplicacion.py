"""Flujo de la aplicación: primer arranque, inicio de sesión, ventana principal y
regreso al inicio de sesión al cerrar sesión o por inactividad."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.dialogos import DialogoCambiarClave, DialogoLogin, DialogoPrimerAdministrador
from gimnasio.ui.estilos import HOJA_ESTILOS
from gimnasio.ui.ventana_principal import VentanaPrincipal


class Aplicacion:
    def __init__(self, app: QApplication, servicios: Servicios):
        self.app = app
        self.servicios = servicios
        self.ventana: VentanaPrincipal | None = None
        app.setStyleSheet(HOJA_ESTILOS)
        app.setQuitOnLastWindowClosed(False)

    def iniciar(self) -> None:
        if not self.servicios.usuarios.hay_usuarios():
            dialogo = DialogoPrimerAdministrador(self.servicios)
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                self.app.quit()
                return
            self.abrir_ventana(dialogo.usuario_actual)
            return
        self.mostrar_login()

    def mostrar_login(self, aviso: str = "") -> None:
        nombre = self.servicios.configuracion.obtener("gimnasio_nombre") or "Enforma"
        dialogo = DialogoLogin(self.servicios, nombre, aviso)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            self.app.quit()
            return
        actual = dialogo.usuario_actual
        if actual.debe_cambiar_clave:
            cambio = DialogoCambiarClave(self.servicios, actual, obligatorio=True)
            if cambio.exec() != QDialog.DialogCode.Accepted:
                self.servicios.sesion.cerrar_sesion(actual)
                QTimer.singleShot(0, self.mostrar_login)
                return
            actual = cambio.usuario_actual
        self.abrir_ventana(actual)

    def abrir_ventana(self, actual: UsuarioActual) -> None:
        self.ventana = VentanaPrincipal(self.servicios, actual)
        self.ventana.sesion_cerrada.connect(self._al_cerrar_sesion)
        self.ventana.salir.connect(self.app.quit)
        self.ventana.showMaximized()

    def _al_cerrar_sesion(self, por_inactividad: bool) -> None:
        if self.ventana:
            self.ventana.deleteLater()
            self.ventana = None
        aviso = "La sesión se cerró por inactividad." if por_inactividad else ""
        QTimer.singleShot(0, lambda: self.mostrar_login(aviso))
