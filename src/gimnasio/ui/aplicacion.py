"""Flujo de la aplicación: primer arranque, inicio de sesión, ventana principal,
regreso al inicio de sesión al cerrar sesión o por inactividad, y copias de seguridad
automáticas (a la hora diaria, en segundo plano, y al cerrar el programa)."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog

from gimnasio.servicios.backups import TIPO_AUTOMATICO, ErrorBackupNegocio, ResultadoBackup
from gimnasio.servicios.contenedor import Servicios
from gimnasio.servicios.permisos import UsuarioActual
from gimnasio.ui.backups import HiloBackup, ejecutar_con_espera
from gimnasio.ui.dialogos import DialogoCambiarClave, DialogoLogin, DialogoPrimerAdministrador
from gimnasio.ui.estilos import HOJA_ESTILOS
from gimnasio.ui.ventana_principal import VentanaPrincipal


INTERVALO_COPIA_DIARIA_MS = 60_000


class Aplicacion:
    def __init__(self, app: QApplication, servicios: Servicios):
        self.app = app
        self.servicios = servicios
        self.ventana: VentanaPrincipal | None = None
        app.setStyleSheet(HOJA_ESTILOS)
        app.setQuitOnLastWindowClosed(False)
        self.hilo_backup: HiloBackup | None = None
        self.ultimo_resultado: ResultadoBackup | None = None
        self._temporizador_backup = QTimer()
        self._temporizador_backup.setInterval(INTERVALO_COPIA_DIARIA_MS)
        self._temporizador_backup.timeout.connect(self.revisar_copia_diaria)
        self._temporizador_backup.start()

    def iniciar(self) -> None:
        # Planes de ejemplo (inactivos, sin precio) solo si la base no tiene ninguno.
        self.servicios.planes.crear_planes_ejemplo()
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
        aviso = "La sesión se cerró por inactividad." if por_inactividad else ""
        if self.ventana:
            aviso = self.ventana.aviso_cierre or aviso
            self.ventana.deleteLater()
            self.ventana = None
        QTimer.singleShot(0, lambda: self.mostrar_login(aviso))

    # --- copias automáticas ----------------------------------------------------
    def revisar_copia_diaria(self) -> bool:
        """Cada minuto: si ya pasó la hora diaria y no hay copia de hoy, la hace en
        segundo plano (Recepción sigue funcionando). Devuelve True si la inició."""
        if self.hilo_backup is not None:
            return False
        try:
            if not self.servicios.backups.toca_copia_diaria():
                return False
            actual = self.ventana.actual if self.ventana else None
            tarea = self.servicios.backups.preparar(actual, TIPO_AUTOMATICO)
        except ErrorBackupNegocio:
            # Sin contraseña: queda registrado como fallido y se reintenta en una hora.
            self.ultimo_resultado = self.servicios.backups.hacer_backup(None, TIPO_AUTOMATICO)
            self._avisar_resultado()
            return False
        except Exception:  # noqa: BLE001 - nunca interrumpir el trabajo de Recepción
            return False
        self.hilo_backup = HiloBackup(self.servicios.backups, tarea)
        self.hilo_backup.finished.connect(self._al_terminar_copia_diaria)
        self.hilo_backup.start()
        return True

    def _al_terminar_copia_diaria(self) -> None:
        hilo, self.hilo_backup = self.hilo_backup, None
        if hilo is None or hilo.resultado is None:
            return
        self.servicios.backups.registrar(hilo.resultado)
        self.ultimo_resultado = hilo.resultado
        hilo.deleteLater()
        self._avisar_resultado()

    def _avisar_resultado(self) -> None:
        resultado = self.ultimo_resultado
        if not self.ventana or resultado is None:
            return
        self.ventana.actualizar_aviso_backup()
        if resultado.exitoso:
            texto = "Copia de seguridad diaria hecha."
            if resultado.avisos:
                texto += " " + " ".join(resultado.avisos)
        else:
            texto = f"La copia de seguridad diaria falló: {resultado.error}"
        self.ventana.statusBar().showMessage(texto, 15_000)
        if self.ventana.pantalla_backups:
            self.ventana.pantalla_backups.actualizar()

    def copia_al_cerrar(self) -> ResultadoBackup:
        """Copia automática al cerrar el programa, la cierre quien la cierre."""
        self._temporizador_backup.stop()
        if self.hilo_backup is not None:
            self.hilo_backup.wait()
            self._al_terminar_copia_diaria()
        try:
            tarea = self.servicios.backups.preparar(None, TIPO_AUTOMATICO)
        except ErrorBackupNegocio:
            return self.servicios.backups.hacer_backup(None, TIPO_AUTOMATICO)
        self.ultimo_resultado = ejecutar_con_espera(
            self.servicios.backups, tarea, "Haciendo copia de seguridad antes de cerrar…")
        return self.ultimo_resultado
