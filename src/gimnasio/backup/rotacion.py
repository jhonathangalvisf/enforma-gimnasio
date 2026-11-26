"""Rotación de copias: 7 diarias, 4 semanales y 12 mensuales (sección 8).

Se conserva la copia **más reciente** de cada uno de los 7 días más recientes que
tienen copia, de cada una de las 4 semanas más recientes y de cada uno de los 12
meses más recientes (días, semanas y meses de Bogotá). Si el gimnasio cierra unos días,
no se pierden copias: se cuentan días *con copia*, no días del calendario.
Las copias que no entran en ningún grupo se borran.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TypeVar

from gimnasio.config import ZONA_HORARIA

DIARIAS = 7
SEMANALES = 4
MENSUALES = 12

T = TypeVar("T")


def a_conservar(
    copias: Iterable[T],
    fecha_de: Callable[[T], datetime],
    diarias: int = DIARIAS,
    semanales: int = SEMANALES,
    mensuales: int = MENSUALES,
) -> set[int]:
    """Índices (posición en `copias`) de las copias que se conservan."""
    lista = list(copias)
    orden = sorted(range(len(lista)), key=lambda i: fecha_de(lista[i]), reverse=True)
    conservar: set[int] = set()
    for cantidad, llave in (
        (diarias, lambda f: f.date()),
        (semanales, lambda f: tuple(f.isocalendar())[:2]),
        (mensuales, lambda f: (f.year, f.month)),
    ):
        vistos: set = set()
        for i in orden:  # de la más reciente a la más vieja
            grupo = llave(fecha_de(lista[i]).astimezone(ZONA_HORARIA))
            if grupo in vistos:
                continue
            if len(vistos) >= cantidad:
                break
            vistos.add(grupo)
            conservar.add(i)
    return conservar


def a_borrar(copias: Iterable[T], fecha_de: Callable[[T], datetime]) -> list[T]:
    lista = list(copias)
    conservar = a_conservar(lista, fecha_de)
    return [c for i, c in enumerate(lista) if i not in conservar]
