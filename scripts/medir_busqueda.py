"""Mide los tiempos de búsqueda de clientes (meta: < 200 ms con 12.000 clientes).

Uso:
    python scripts/seed_datos.py --db datos_prueba.db      # una sola vez
    python scripts/medir_busqueda.py --db datos_prueba.db

Cada búsqueda se repite varias veces y se informa la mediana y el peor tiempo,
incluyendo el conteo total y la primera página de 200 filas (lo que pide la pantalla).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from gimnasio.config import url_base_datos  # noqa: E402
from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor  # noqa: E402
from gimnasio.servicios.clientes import FiltrosClientes, Vigencia  # noqa: E402
from gimnasio.servicios.contenedor import crear_servicios  # noqa: E402
from gimnasio.servicios.permisos import ROL_ADMIN, UsuarioActual  # noqa: E402

META_MS = 200
CASOS: tuple[tuple[str, FiltrosClientes, str], ...] = (
    ("Sin filtros (primera página)", FiltrosClientes(), "apellidos"),
    ("Código exacto", FiltrosClientes(texto="004521"), "apellidos"),
    ("Código sin ceros", FiltrosClientes(texto="4521"), "apellidos"),
    ("Documento (prefijo)", FiltrosClientes(texto="1045"), "apellidos"),
    ("Teléfono (prefijo)", FiltrosClientes(texto="310 4"), "apellidos"),
    ("Apellido", FiltrosClientes(texto="gomez"), "apellidos"),
    ("Nombre y apellido", FiltrosClientes(texto="maria rodri"), "apellidos"),
    ("Correo", FiltrosClientes(texto="@example.com"), "apellidos"),
    ("Vigencia: por vencer", FiltrosClientes(vigencia=Vigencia.POR_VENCER), "vence"),
    ("Vigencia: vencida + activos", FiltrosClientes(vigencia=Vigencia.VENCIDA, estado="activo"), "vence"),
    ("Plan", FiltrosClientes(plan_id=1), "plan"),
    ("Cumpleaños del mes", FiltrosClientes(cumple_mes=11), "apellidos"),
    ("Sin asistir hace 30 días", FiltrosClientes(sin_asistir_dias=30), "apellidos"),
    ("Apellido ordenado por vence", FiltrosClientes(texto="gomez"), "vence"),
)


def medir(url: str, repeticiones: int = 5) -> list[tuple[str, int, float, float]]:
    motor = crear_motor(url)
    servicios = crear_servicios(crear_fabrica_sesiones(motor))
    actual = UsuarioActual(id=1, usuario="medicion", nombre_completo="Medición", rol=ROL_ADMIN)
    resultados = []
    for nombre, filtros, orden in CASOS:
        tiempos, total = [], 0
        servicios.clientes.buscar(actual, filtros, orden=orden)  # calienta la caché
        for _ in range(repeticiones):
            inicio = time.perf_counter()
            total = servicios.clientes.buscar(actual, filtros, orden=orden).total
            tiempos.append((time.perf_counter() - inicio) * 1000)
        resultados.append((nombre, total, statistics.median(tiempos), max(tiempos)))
    motor.dispose()
    return resultados


def main(argumentos: list[str] | None = None) -> list[tuple[str, int, float, float]]:
    parser = argparse.ArgumentParser(description="Mide la búsqueda de clientes.")
    parser.add_argument("--db", help="Base de datos con datos de prueba")
    parser.add_argument("--repeticiones", type=int, default=5)
    args = parser.parse_args(argumentos)
    url = f"sqlite:///{Path(args.db).resolve().as_posix()}" if args.db else url_base_datos()
    resultados = medir(url, args.repeticiones)
    print(f"{'Búsqueda':<32}{'Resultados':>11}{'Mediana':>10}{'Peor':>10}")
    for nombre, total, mediana, peor in resultados:
        marca = "" if peor < META_MS else "  ← supera la meta"
        print(f"{nombre:<32}{total:>11,}{mediana:>8.1f}ms{peor:>8.1f}ms{marca}".replace(",", "."))
    peor = max(r[3] for r in resultados)
    print(f"\nPeor tiempo: {peor:.1f} ms (meta: < {META_MS} ms)")
    return resultados


if __name__ == "__main__":
    main()
