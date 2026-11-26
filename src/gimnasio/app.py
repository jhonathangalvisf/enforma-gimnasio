"""Punto de arranque: python -m gimnasio.app

Actualiza la base de datos (migraciones) y abre la interfaz. Con --solo-migrar
solo prepara la base, sin abrir ventanas. Al cerrar hace la copia de seguridad.
"""

from __future__ import annotations

import argparse
import sys

from gimnasio.config import ruta_base_datos
from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
from gimnasio.db.migraciones import actualizar_esquema


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description="Sistema de gestión del gimnasio Enforma")
    analizador.add_argument("--solo-migrar", action="store_true",
                            help="crear o actualizar la base de datos y salir")
    opciones = analizador.parse_args(argumentos)

    actualizar_esquema()
    if opciones.solo_migrar:
        print(f"Base de datos lista en {ruta_base_datos()}")
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gimnasio.servicios.contenedor import crear_servicios
    from gimnasio.ui.aplicacion import Aplicacion

    app = QApplication(sys.argv)
    app.setApplicationName("Enforma")
    motor = crear_motor()
    servicios = crear_servicios(crear_fabrica_sesiones(motor))
    aplicacion = Aplicacion(app, servicios)
    QTimer.singleShot(0, aplicacion.iniciar)
    codigo = app.exec()
    aplicacion.copia_al_cerrar()  # copia automática al cerrar (sección 8)
    motor.dispose()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
