"""Instancia única: Enforma no se abre dos veces en el mismo PC (sección 11).

Dos copias del programa escribiendo la misma base podrían repetir consecutivos o
pisar copias de seguridad. Al abrir:

1. Se toma un candado (`QLockFile`) en la carpeta de datos. Si el programa que lo
   tenía se cerró mal, Qt detecta que ese proceso ya no existe y lo libera solo.
2. El que lo consigue abre un canal local (`QLocalServer`) y sigue normalmente.
3. El que no lo consigue avisa por ese canal a la copia abierta, que trae su ventana
   al frente, y se cierra sin abrir nada.

En Windows además se crea un *mutex* con nombre fijo (`MUTEX_WINDOWS`), que el
instalador usa para pedir que se cierre Enforma antes de actualizar o desinstalar.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ARCHIVO_CANDADO = "enforma.lock"
MUTEX_WINDOWS = "EnformaGimnasioAplicacion"  # el mismo nombre va en AppMutex del instalador
MENSAJE_ACTIVAR = b"activar\n"


def nombre_canal(carpeta_datos: Path) -> str:
    """Un canal por carpeta de datos (las pruebas usan carpetas distintas)."""
    clave = str(Path(carpeta_datos).resolve()).lower().encode("utf-8")
    return "enforma-" + hashlib.sha1(clave).hexdigest()[:16]


def permitir_traer_al_frente() -> None:
    """Windows solo deja pasar al frente a otra ventana si el proceso que está en primer
    plano (este, recién abierto por el usuario) lo permite."""
    if sys.platform == "win32":
        try:
            import ctypes
            ASFW_ANY = -1
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            pass


def crear_mutex_windows():
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_WINDOWS)
    except Exception:
        return None


class InstanciaUnica(QObject):
    """`adquirir()` devuelve True si esta es la única copia abierta."""

    activar = Signal()

    def __init__(self, carpeta_datos: Path, padre: QObject | None = None):
        super().__init__(padre)
        carpeta_datos = Path(carpeta_datos)
        carpeta_datos.mkdir(parents=True, exist_ok=True)
        self.nombre = nombre_canal(carpeta_datos)
        self._candado = QLockFile(str(carpeta_datos / ARCHIVO_CANDADO))
        self._candado.setStaleLockTime(0)  # solo se libera si el proceso dueño ya no existe
        self._servidor: QLocalServer | None = None
        self._mutex = None

    @property
    def es_principal(self) -> bool:
        return self._servidor is not None

    def adquirir(self, espera_ms: int = 200) -> bool:
        if self._candado.tryLock(espera_ms):
            QLocalServer.removeServer(self.nombre)  # restos de un cierre inesperado
            servidor = QLocalServer(self)
            servidor.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            servidor.newConnection.connect(self._al_conectar)
            servidor.listen(self.nombre)
            self._servidor = servidor
            self._mutex = crear_mutex_windows()
            return True
        self.avisar_a_la_abierta()
        return False

    def avisar_a_la_abierta(self, espera_ms: int = 1500) -> bool:
        permitir_traer_al_frente()
        socket = QLocalSocket()
        socket.connectToServer(self.nombre)
        if not socket.waitForConnected(espera_ms):
            return False
        socket.write(MENSAJE_ACTIVAR)
        socket.flush()
        socket.waitForBytesWritten(espera_ms)
        socket.disconnectFromServer()
        return True

    def _al_conectar(self) -> None:
        while self._servidor is not None and self._servidor.hasPendingConnections():
            conexion = self._servidor.nextPendingConnection()
            conexion.disconnected.connect(conexion.deleteLater)
        self.activar.emit()

    def liberar(self) -> None:
        if self._servidor is not None:
            self._servidor.close()
            self._servidor = None
        if self._candado.isLocked():
            self._candado.unlock()
        if self._mutex:
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._mutex)
            except Exception:
                pass
            self._mutex = None
