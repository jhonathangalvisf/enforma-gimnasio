"""Mide los reportes del módulo Reportes sobre una base del seed (meta: < 200 ms).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_reportes.py --db datos_prueba.db

Trabaja sobre una copia temporal. Mide solo la consulta (sin exportar).
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

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402
from gimnasio.servicios.reportes import CATALOGO, ParametrosReportes  # noqa: E402

META_MS = 200
# Periodo de cada medición: un mes (lo normal) y un año (lo máximo habitual).
PERIODOS = {"mes": 30, "año": 365}


def medir(ruta_db: Path, repeticiones: int = 3) -> list[tuple[str, int, float, float]]:
    with tempfile.TemporaryDirectory() as carpeta:
        copia = Path(carpeta) / "medicion.db"
        shutil.copyfile(ruta_db, copia)
        motor = crear_motor(f"sqlite:///{copia.as_posix()}")
        servicios = crear_servicios(crear_fabrica_sesiones(motor), carpeta_datos=Path(carpeta))
        actual = UsuarioActual(id=1, usuario="medicion", nombre_completo="Medición",
                               rol=ROL_ADMIN)
        rep = servicios.reportes
        hoy = rep.hoy()
        resultados = []
        for definicion in CATALOGO:
            periodos = PERIODOS if "rango" in definicion.filtros else {"": 0}
            for nombre_periodo, dias in periodos.items():
                p = ParametrosReportes(desde=hoy - timedelta(days=dias) if dias else hoy,
                                       hasta=hoy, cliente_id=1, dias=30 if "dias" in
                                       definicion.filtros else None)
                if definicion.clave == "clientes_por_vencer":
                    p = ParametrosReportes(dias=5)
                funcion = lambda c=definicion.clave, p=p: rep.generar(actual, c, p)  # noqa: E731
                funcion()  # calienta la caché
                tiempos, total = [], 0
                for _ in range(repeticiones):
                    inicio = time.perf_counter()
                    total = len(funcion().filas)
                    tiempos.append((time.perf_counter() - inicio) * 1000)
                etiqueta = definicion.titulo + (f" ({nombre_periodo})" if nombre_periodo else "")
                resultados.append((etiqueta, total, statistics.median(tiempos), max(tiempos)))
        motor.dispose()
    return resultados


def main(argumentos: list[str] | None = None) -> list[tuple[str, int, float, float]]:
    parser = argparse.ArgumentParser(description="Mide los reportes.")
    parser.add_argument("--db", required=True, help="Base de datos con datos de prueba")
    parser.add_argument("--repeticiones", type=int, default=3)
    args = parser.parse_args(argumentos)
    resultados = medir(Path(args.db).resolve(), args.repeticiones)
    print(f"{'Reporte':<56}{'Filas':>9}{'Mediana':>10}{'Peor':>10}")
    for nombre, total, mediana, peor in resultados:
        marca = "" if peor < META_MS else "  ← supera la meta"
        print(f"{nombre[:55]:<56}{total:>9,}{mediana:>8.1f}ms{peor:>8.1f}ms{marca}"
              .replace(",", "."))
    print(f"\nPeor tiempo: {max(r[3] for r in resultados):.1f} ms (meta: < {META_MS} ms)")
    return resultados


if __name__ == "__main__":
    main()
