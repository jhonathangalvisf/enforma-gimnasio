"""Criterio de aceptación 1: con 12.000 clientes la búsqueda responde en < 200 ms.

Genera la base con el script de datos de prueba (≈15 s) una vez por sesión de pruebas.
"""

from __future__ import annotations

import pytest

from scripts import medir_busqueda, seed_datos


@pytest.fixture(scope="module")
def base_12000(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("rendimiento") / "seed.db"
    seed_datos.main(["--db", str(ruta)])
    return f"sqlite:///{ruta.as_posix()}"


def test_busquedas_menores_a_200_ms(base_12000):
    resultados = medir_busqueda.medir(base_12000, repeticiones=3)
    lentas = [(n, round(m)) for n, _, m, _ in resultados if m >= medir_busqueda.META_MS]
    assert not lentas, f"Búsquedas lentas: {lentas}"
    totales = {n: t for n, t, _, _ in resultados}
    assert totales["Sin filtros (primera página)"] == 12_000
    assert totales["Código exacto"] == 1
