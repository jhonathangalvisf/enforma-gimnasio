"""Punto de arranque: python -m gimnasio.app (o Enforma.exe empaquetado).

Actualiza la base de datos (migraciones) y abre la interfaz. Al cerrar hace la copia
de seguridad. Opciones:

- `--solo-migrar`: solo prepara la base, sin abrir ventanas.
- `--diagnostico [--reporte RUTA]`: revisa la instalación, DPAPI y la última copia.
- `--prueba-humo [--reporte RUTA]`: prueba el ejecutable con datos inventados.

Si Enforma ya está abierto, la ventana abierta pasa al frente y esta copia se cierra.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gimnasio import __version__
from gimnasio.config import carpeta_datos, ruta_base_datos
from gimnasio.registro import (
    cerrar_registro, configurar_registro, instalar_manejador_errores, registrar_arranque, registro,
    resumen_error,
)
from gimnasio.rutas import empaquetado, recurso

ID_APLICACION_WINDOWS = "Enforma.Gimnasio"  # agrupa la barra de tareas con el ícono propio


def _analizar(argumentos: list[str] | None) -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description="Sistema de gestión del gimnasio Enforma")
    analizador.add_argument("--solo-migrar", action="store_true",
                            help="crear o actualizar la base de datos y salir")
    analizador.add_argument("--diagnostico", action="store_true",
                            help="revisar la instalación, la protección DPAPI y la última copia")
    analizador.add_argument("--prueba-humo", action="store_true",
                            help="probar el ejecutable con datos inventados en una carpeta temporal")
    analizador.add_argument("--reporte", type=Path,
                            help="con --diagnostico o --prueba-humo: guardar el informe aquí")
    analizador.add_argument("--version", action="version", version=f"Enforma {__version__}")
    return analizador.parse_args(argumentos)


def _id_barra_tareas() -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APLICACION_WINDOWS)
        except Exception:
            pass


def _avisar_error(texto: str) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox
    if QApplication.instance() is None:
        return
    QMessageBox.critical(
        None, "Enforma",
        "Ocurrió un error inesperado. Lo que estaba haciendo puede no haberse guardado.\n\n"
        f"{texto}\n\nEl detalle quedó en la carpeta de datos (logs\\enforma.log). "
        "Si se repite, avise al administrador.",
    )


def main(argumentos: list[str] | None = None) -> int:
    opciones = _analizar(argumentos)
    datos = carpeta_datos()
    configurar_registro(datos)

    if opciones.diagnostico:
        from gimnasio import diagnostico
        return diagnostico.ejecutar(opciones.reporte)
    if opciones.prueba_humo:
        from gimnasio import prueba_humo
        return prueba_humo.ejecutar(opciones.reporte)

    from gimnasio.db.migraciones import actualizar_esquema

    if opciones.solo_migrar:
        actualizar_esquema()
        registro.info("Base de datos lista (--solo-migrar).")
        print(f"Base de datos lista en {ruta_base_datos()}")
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from gimnasio.ui.instancia import InstanciaUnica

    _id_barra_tareas()
    app = QApplication(sys.argv)
    app.setApplicationName("Enforma")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(QIcon(str(recurso("enforma.ico"))))

    instancia = InstanciaUnica(datos)
    if not instancia.adquirir():
        registro.info("Enforma ya estaba abierto: se trae su ventana al frente.")
        return 0

    registrar_arranque(__version__, empaquetado(), datos)
    instalar_manejador_errores(_avisar_error)
    try:
        actualizar_esquema()
    except Exception as e:  # base dañada, disco lleno, versión más nueva…
        registro.exception("No se pudo preparar la base de datos.")
        QMessageBox.critical(
            None, "Enforma",
            "No se pudo abrir la base de datos del gimnasio.\n\n"
            f"{resumen_error(e)}\n\nNo se modificó nada. Si el problema sigue, restaure la "
            "última copia de seguridad (ver el manual de instalación y respaldo).",
        )
        instancia.liberar()
        return 1

    from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
    from gimnasio.servicios.contenedor import crear_servicios
    from gimnasio.ui.aplicacion import Aplicacion

    motor = crear_motor()
    servicios = crear_servicios(crear_fabrica_sesiones(motor))
    aplicacion = Aplicacion(app, servicios)
    instancia.activar.connect(aplicacion.traer_al_frente)
    QTimer.singleShot(0, aplicacion.iniciar)
    registro.info("Interfaz iniciada.")
    codigo = app.exec()
    resultado = aplicacion.copia_al_cerrar()  # copia automática al cerrar (sección 8)
    registro.info("Copia al cerrar: %s", "exitosa" if resultado and resultado.exitoso
                  else "no se pudo hacer (ver Copias de seguridad)")
    motor.dispose()
    instancia.liberar()
    registro.info("Enforma cerrado.")
    cerrar_registro()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
