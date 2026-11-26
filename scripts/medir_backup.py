"""Mide cuánto tardan y pesan las copias con la base de prueba (12.000 clientes).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_backup.py --db datos_prueba.db

Trabaja sobre una copia de la base en una carpeta temporal: no toca `datos_prueba.db`.
Mide: crear la copia (instantánea + integrity_check + zip + cifrado + escritura),
verificarla (descifrar + extraer + integrity_check) y restaurarla.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from gimnasio.backup.protector import ProtectorSinCifrar  # noqa: E402
from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.formato import tamano_archivo  # noqa: E402
from gimnasio.servicios.backups import TIPO_MANUAL  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402

CLAVE = "medicion-backups-2026"


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description="Mide copias de seguridad")
    analizador.add_argument("--db", type=Path, required=True)
    opciones = analizador.parse_args(argumentos)
    with tempfile.TemporaryDirectory(prefix="enforma_medir_") as temporal:
        datos = Path(temporal)
        base = datos / "enforma.db"
        shutil.copy2(opciones.db, base)
        print(f"Base: {tamano_archivo(base.stat().st_size)}")
        motor = crear_motor(f"sqlite:///{base.as_posix()}")
        servicios = crear_servicios(crear_fabrica_sesiones(motor), carpeta_datos=datos,
                                    protector_clave=ProtectorSinCifrar())
        admin = UsuarioActual(id=1, usuario="admin", nombre_completo="Medición", rol=ROL_ADMIN)
        servicios.backups.configurar_clave(admin, CLAVE, CLAVE)

        inicio = time.perf_counter()
        resultado = servicios.backups.hacer_backup(admin, TIPO_MANUAL)
        crear = time.perf_counter() - inicio
        if not resultado.exitoso:
            print(f"ERROR: {resultado.error}")
            return 1
        [ruta] = resultado.rutas
        print(f"Crear copia: {crear:.2f} s, archivo {tamano_archivo(resultado.tamano)} "
              f"({resultado.resumen.texto()})")

        inicio = time.perf_counter()
        servicios.backups.verificar(admin, ruta, CLAVE)
        print(f"Verificar copia: {time.perf_counter() - inicio:.2f} s")

        inicio = time.perf_counter()
        servicios.backups.restaurar(admin, ruta, CLAVE)
        print(f"Restaurar (incluye copia previa de seguridad): "
              f"{time.perf_counter() - inicio:.2f} s")
        motor.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
