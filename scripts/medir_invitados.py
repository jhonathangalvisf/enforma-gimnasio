"""Mide la pantalla de Invitados y sus reportes sobre una base del seed (meta: < 200 ms).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_invitados.py --db datos_prueba.db

Trabaja sobre una copia temporal: las visitas de la medición no quedan guardadas.
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sqlalchemy import func, select  # noqa: E402

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.modelos import Invitado  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
from gimnasio.servicios.invitados import ParametrosReporteInvitados  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402

META_MS = 200


def medir(ruta_db: Path, repeticiones: int = 5) -> list[tuple[str, int, float, float]]:
    with tempfile.TemporaryDirectory() as carpeta:
        copia = Path(carpeta) / "medicion.db"
        shutil.copyfile(ruta_db, copia)
        motor = crear_motor(f"sqlite:///{copia.as_posix()}")
        fabrica = crear_fabrica_sesiones(motor)
        servicios = crear_servicios(fabrica, carpeta_datos=Path(carpeta))
        actual = UsuarioActual(id=1, usuario="medicion", nombre_completo="Medición",
                               rol=ROL_ADMIN)
        with fabrica() as s:
            muestra = s.execute(select(Invitado.id, Invitado.documento, Invitado.nombre)
                                .order_by(func.random()).limit(60)).all()
        inv = servicios.invitados
        hoy = inv.hoy()
        hace90 = hoy - timedelta(days=90)
        ids = iter([m.id for m in muestra])
        apellido = muestra[0].nombre.split()[-1]
        casos = (
            ("Documento + Enter (ficha)",
             lambda: (None, inv.por_documento(actual, muestra[1].documento).total_visitas)),
            ("Registrar visita",
             lambda: (inv.registrar_visita(actual, next(ids), confirmar_duplicado=True), 1)),
            ("Lista de invitados (todos)", lambda: (None, len(inv.buscar(actual)))),
            (f"Buscar por nombre «{apellido[:12]}»",
             lambda: (None, len(inv.buscar(actual, apellido)))),
            ("Buscar por documento (prefijo)",
             lambda: (None, len(inv.buscar(actual, muestra[2].documento[:4])))),
            ("Reporte visitas (90 días)", lambda: (None, len(inv.reporte(
                actual, ParametrosReporteInvitados("visitas", hace90, hoy)).filas))),
            ("Reporte por invitado (90 días)", lambda: (None, len(inv.reporte(
                actual, ParametrosReporteInvitados("invitados", hace90, hoy)).filas))),
            ("Reporte por anfitrión (90 días)", lambda: (None, len(inv.reporte(
                actual, ParametrosReporteInvitados("anfitriones", hace90, hoy)).filas))),
        )
        resultados = []
        for nombre, funcion in casos:
            funcion()  # calienta la caché
            tiempos, total = [], 0
            for _ in range(repeticiones):
                inicio = time.perf_counter()
                _, total = funcion()
                tiempos.append((time.perf_counter() - inicio) * 1000)
            resultados.append((nombre, total, statistics.median(tiempos), max(tiempos)))
        motor.dispose()
    return resultados


def main(argumentos: list[str] | None = None) -> list[tuple[str, int, float, float]]:
    parser = argparse.ArgumentParser(description="Mide la pantalla y reportes de invitados.")
    parser.add_argument("--db", required=True, help="Base de datos con datos de prueba")
    parser.add_argument("--repeticiones", type=int, default=5)
    args = parser.parse_args(argumentos)
    resultados = medir(Path(args.db).resolve(), args.repeticiones)
    print(f"{'Operación':<34}{'Filas':>9}{'Mediana':>10}{'Peor':>10}")
    for nombre, total, mediana, peor in resultados:
        marca = "" if peor < META_MS else "  ← supera la meta"
        print(f"{nombre:<34}{total:>9,}{mediana:>8.1f}ms{peor:>8.1f}ms{marca}".replace(",", "."))
    print(f"\nPeor tiempo: {max(r[3] for r in resultados):.1f} ms (meta: < {META_MS} ms)")
    return resultados


if __name__ == "__main__":
    main()
