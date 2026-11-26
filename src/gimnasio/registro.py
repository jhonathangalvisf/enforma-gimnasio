"""Registro de eventos y errores del programa en la carpeta de datos (`logs/`).

Sirve para diagnosticar problemas en el PC del gimnasio. Reglas:

- Nunca se escriben datos de clientes: solo eventos técnicos (arranque, versión,
  migraciones, copias de seguridad) y el rastro de los errores inesperados (tipo de
  error, archivo y línea del código). El mensaje del error se recorta.
- Rota solo: `enforma.log` de máximo 1 MB y 5 archivos anteriores.
- `fallos.log` recibe el volcado de `faulthandler` si el proceso se cae sin excepción
  de Python (por ejemplo, un fallo dentro de Qt).
"""

from __future__ import annotations

import faulthandler
import logging
import platform
import sys
import threading
import traceback
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOMBRE_REGISTRO = "enforma"
CARPETA_LOGS = "logs"
ARCHIVO_LOG = "enforma.log"
ARCHIVO_FALLOS = "fallos.log"
TAMANO_MAXIMO = 1_000_000
COPIAS = 5
LARGO_MAXIMO_MENSAJE = 200

registro = logging.getLogger(NOMBRE_REGISTRO)
_archivo_fallos = None  # se mantiene abierto mientras corre el programa


def carpeta_logs(carpeta_datos: Path) -> Path:
    return carpeta_datos / CARPETA_LOGS


def configurar_registro(carpeta_datos: Path, nivel: int = logging.INFO) -> Path:
    """Escribe el registro en `<datos>/logs/enforma.log`. Devuelve la ruta del archivo."""
    global _archivo_fallos
    carpeta = carpeta_logs(carpeta_datos)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / ARCHIVO_LOG
    for manejador in list(registro.handlers):  # reconfigurar no duplica líneas
        registro.removeHandler(manejador)
        manejador.close()
    manejador = RotatingFileHandler(ruta, maxBytes=TAMANO_MAXIMO, backupCount=COPIAS,
                                    encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    registro.addHandler(manejador)
    registro.setLevel(nivel)
    registro.propagate = False
    try:
        if _archivo_fallos is None:
            _archivo_fallos = open(carpeta / ARCHIVO_FALLOS, "a", encoding="utf-8")
            faulthandler.enable(_archivo_fallos)
    except (OSError, RuntimeError):
        pass  # sin volcado de fallos graves no se detiene el programa
    return ruta


def cerrar_registro() -> None:
    """Cierra los archivos del registro (al salir y en las pruebas)."""
    global _archivo_fallos
    for manejador in list(registro.handlers):
        registro.removeHandler(manejador)
        manejador.close()
    if _archivo_fallos is not None:
        try:
            faulthandler.disable()
            _archivo_fallos.close()
        except (OSError, RuntimeError):
            pass
        _archivo_fallos = None


def registrar_arranque(version: str, empaquetado: bool, carpeta_datos: Path) -> None:
    registro.info("Enforma %s iniciado (%s, Python %s, %s). Datos en %s",
                  version, "ejecutable" if empaquetado else "desarrollo",
                  platform.python_version(), platform.platform(terse=True), carpeta_datos)


def resumen_error(error: BaseException) -> str:
    """Tipo y mensaje recortado del error (el mensaje no debe llevar datos personales,
    pero por si acaso se acorta)."""
    mensaje = str(error).replace("\n", " ")
    if len(mensaje) > LARGO_MAXIMO_MENSAJE:
        mensaje = mensaje[:LARGO_MAXIMO_MENSAJE] + "…"
    return f"{type(error).__name__}: {mensaje}" if mensaje else type(error).__name__


def registrar_error(tipo, error, rastro) -> None:
    """Rastro del código (archivo, línea, función) sin variables locales."""
    pasos = "".join(traceback.format_tb(rastro)) if rastro else ""
    registro.error("Error inesperado: %s\n%s", resumen_error(error), pasos.rstrip())


def instalar_manejador_errores(avisar: Callable[[str], None] | None = None) -> None:
    """Los errores no atrapados se registran y, si hay interfaz, se avisa al usuario
    en lugar de cerrar el programa sin decir nada."""
    avisando = threading.Lock()

    def manejar(tipo, error, rastro):
        if issubclass(tipo, KeyboardInterrupt):
            sys.__excepthook__(tipo, error, rastro)
            return
        registrar_error(tipo, error, rastro)
        if avisar is not None and avisando.acquire(blocking=False):
            try:
                avisar(resumen_error(error))
            except Exception:  # el aviso nunca debe causar otro error
                pass
            finally:
                avisando.release()

    sys.excepthook = manejar
    threading.excepthook = lambda a: registrar_error(a.exc_type, a.exc_value, a.exc_traceback)
