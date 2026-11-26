"""Mide Recepción y los reportes de asistencia sobre una base del seed (meta: < 200 ms).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_asistencia.py --db datos_prueba.db

Trabaja sobre una copia temporal de la base: los ingresos de la medición no quedan
guardados en la base de prueba.
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
from gimnasio.modelos import Cliente  # noqa: E402
from gimnasio.servicios.asistencia import FiltrosAsistencia, ParametrosReporte  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
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
            codigos = list(s.scalars(select(Cliente.codigo).order_by(func.random()).limit(50)))
        a = servicios.asistencia
        hoy = a.hoy()
        hace30 = hoy - timedelta(days=30)
        siguiente = iter(codigos)
        casos = (
            ("Ingreso por código (lector)",
             lambda: (a.registrar_ingreso(actual, next(siguiente), confirmar_duplicado=True), 1)),
            ("Resumen del día (lista lateral)", lambda: (a.resumen_del_dia(actual), 1)),
            ("Consulta de hoy", lambda: (None, a.consultar(
                actual, FiltrosAsistencia(desde=hoy, hasta=hoy)).total)),
            ("Consulta 30 días (1.ª página)", lambda: (None, a.consultar(
                actual, FiltrosAsistencia(desde=hace30, hasta=hoy)).total)),
            ("Reporte del día", lambda: (None, len(a.reporte(
                actual, ParametrosReporte("dia")).filas))),
            ("Reporte por franja (30 días)", lambda: (None, len(a.reporte(
                actual, ParametrosReporte("franja", hace30, hoy)).filas))),
            ("Ranking (30 días)", lambda: (None, len(a.reporte(
                actual, ParametrosReporte("ranking", hace30, hoy)).filas))),
            ("No vienen hace 30 días", lambda: (None, len(a.reporte(
                actual, ParametrosReporte("ausentes", dias=30)).filas))),
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
    parser = argparse.ArgumentParser(description="Mide Recepción y reportes de asistencia.")
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
