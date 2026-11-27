"""Mide cuánto tarda cada módulo en abrirse al cambiar de pantalla (y cada pestaña).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_pantallas.py --db datos_prueba.db

Abre la ventana principal como administrador (sin mostrarla en pantalla), recorre dos
veces todos los módulos del menú y sus pestañas, y avisa si alguno tarda más de la meta.
Trabaja sobre una copia temporal de la base.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402

META_MS = 500  # cambiar de módulo debe sentirse inmediato


def medir(ruta_db: Path) -> list[tuple[str, float]]:
    app = QApplication.instance() or QApplication([])
    from gimnasio.ui import pagos as pantalla_pagos
    from gimnasio.ui.ventana_principal import VentanaPrincipal

    # Pagos pide la clave de un administrador al entrar: en la medición se da por escrita
    # (sin la ventana modal, que dejaría el script esperando).
    pantalla_pagos.pedir_clave_siempre = lambda *_a, **_k: (True, None)

    resultados: list[tuple[str, float]] = []
    with tempfile.TemporaryDirectory() as carpeta:
        copia = Path(carpeta) / "medicion.db"
        shutil.copyfile(ruta_db, copia)
        motor = crear_motor(f"sqlite:///{copia.as_posix()}")
        servicios = crear_servicios(crear_fabrica_sesiones(motor), carpeta_datos=Path(carpeta))
        actual = UsuarioActual(id=1, usuario="medicion", nombre_completo="Medición",
                               rol=ROL_ADMIN)
        inicio = time.perf_counter()
        ventana = VentanaPrincipal(servicios, actual)
        ventana.show()
        app.processEvents()
        resultados.append(("Abrir la ventana principal", (time.perf_counter() - inicio) * 1000))
        for vuelta in (1, 2):  # la segunda vuelta es la que más se parece al uso diario
            for clave in ventana.modulos_visibles():
                inicio = time.perf_counter()
                ventana.ir_a(clave)
                app.processEvents()
                resultados.append((f"{vuelta}.ª vuelta · {clave}",
                                   (time.perf_counter() - inicio) * 1000))
                for pestanas in ventana.pantallas.currentWidget().findChildren(QTabWidget):
                    if not pestanas.isVisible():
                        continue
                    for i in range(1, pestanas.count()):
                        inicio = time.perf_counter()
                        pestanas.setCurrentIndex(i)
                        app.processEvents()
                        resultados.append((f"{vuelta}.ª vuelta · {clave} / {pestanas.tabText(i)}",
                                           (time.perf_counter() - inicio) * 1000))
                    pestanas.setCurrentIndex(0)
                    app.processEvents()
        ventana._cerrando_sesion = True  # sin registrar un cierre de sesión en la copia
        ventana._detener()
        ventana.close()
        motor.dispose()
    return resultados


def main(argumentos: list[str] | None = None) -> list[tuple[str, float]]:
    parser = argparse.ArgumentParser(description="Mide el cambio entre módulos y pestañas.")
    parser.add_argument("--db", required=True, help="Base de datos con datos de prueba")
    args = parser.parse_args(argumentos)
    resultados = medir(Path(args.db).resolve())
    for nombre, ms in resultados:
        marca = "" if ms < META_MS else "  ← supera la meta"
        print(f"{nombre:<60}{ms:>9.0f} ms{marca}")
    print(f"\nPeor tiempo: {max(ms for _, ms in resultados):.0f} ms (meta: < {META_MS} ms)")
    return resultados


if __name__ == "__main__":
    main()
