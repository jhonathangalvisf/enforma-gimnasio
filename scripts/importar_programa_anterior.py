"""Prueba la importación del programa anterior sobre una base de prueba (Fase 10).

La importación real se hace desde el programa (Configuración → Importar datos), que
pide la sesión del administrador y hace la copia de seguridad. Este script es para
ensayar con una base aparte, por ejemplo una copia o una base vacía:

    python scripts/importar_programa_anterior.py --origen "C:\\...\\ENFORMA PROGRAMA\\DB3" --db prueba_importacion.db
    python scripts/importar_programa_anterior.py --origen ... --db prueba_importacion.db --guardar

Sin --guardar no se guarda nada (modo prueba). Siempre deja el informe en Excel junto
a la base, en la carpeta «importaciones». La carpeta de origen no se modifica.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import select  # noqa: E402

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.db.migraciones import actualizar_esquema  # noqa: E402
from gimnasio.modelos import Usuario  # noqa: E402
from gimnasio.servicios.errores import ErrorNegocio  # noqa: E402
from gimnasio.servicios.importacion import ServicioImportacion  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402
from gimnasio.servicios.usuarios import ServicioUsuarios  # noqa: E402

CLAVE_TEMPORAL = "ImportarPrueba1"


def administrador(fabrica) -> UsuarioActual:
    """El primer administrador activo de la base; si no hay usuarios, crea uno de prueba."""
    with fabrica() as sesion:
        u = sesion.scalar(select(Usuario).where(Usuario.rol == ROL_ADMIN, Usuario.activo)
                          .order_by(Usuario.id))
    if u is None:
        print(f"La base no tiene usuarios: se crea el administrador «admin» "
              f"con la contraseña temporal {CLAVE_TEMPORAL}.")
        return ServicioUsuarios(fabrica).crear_primer_administrador(
            "Administrador", "admin", CLAVE_TEMPORAL)
    return UsuarioActual(id=u.id, usuario=u.usuario, nombre_completo=u.nombre_completo,
                         rol=u.rol)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--origen", required=True, help="Carpeta DB3 del programa anterior")
    p.add_argument("--db", required=True, help="Base de prueba (se crea si no existe)")
    p.add_argument("--guardar", action="store_true", help="Guardar (sin esto, solo prueba)")
    args = p.parse_args()

    ruta_db = Path(args.db).resolve()
    url = f"sqlite:///{ruta_db.as_posix()}"
    actualizar_esquema(url)
    motor = crear_motor(url)
    fabrica = crear_fabrica_sesiones(motor)
    servicio = ServicioImportacion(fabrica, carpeta_datos=ruta_db.parent)
    inicio = time.perf_counter()
    try:
        resultado = servicio.importar(administrador(fabrica), args.origen, guardar=args.guardar)
    except ErrorNegocio as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        motor.dispose()
    print(resultado.texto)
    print(f"Tiempo: {time.perf_counter() - inicio:.1f} s")
    print(f"Informe: {resultado.ruta_informe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
