"""El script de datos de prueba genera una base coherente."""

from __future__ import annotations

from sqlalchemy import text

from gimnasio.db.engine import crear_motor
from gimnasio.formato import pesos
from scripts import seed_datos


def test_seed_pequeno_es_coherente(tmp_path):
    ruta = tmp_path / "seed.db"
    conteos = seed_datos.main(["--clientes", "300", "--db", str(ruta)])
    assert conteos["clientes"] == 300
    assert conteos["asistencias"] > 0 and conteos["pagos"] > 0

    motor = crear_motor(f"sqlite:///{ruta.as_posix()}")
    with motor.connect() as cx:
        def uno(sql):
            return cx.execute(text(sql)).scalar()

        assert uno("PRAGMA integrity_check") == "ok"
        assert uno("PRAGMA foreign_key_check") is None
        # Ningún cliente con dos casilleros activos ni casillero con dos dueños.
        assert uno("SELECT count(*) FROM (SELECT cliente_id FROM casillero_asignaciones "
                   "WHERE fecha_liberacion IS NULL GROUP BY cliente_id HAVING count(*) > 1)") == 0
        # Zonas por sexo (Fase 5) y vencimiento propio en las asignaciones activas.
        assert uno("SELECT count(*) FROM casillero_asignaciones a "
                   "JOIN casilleros k ON k.id = a.casillero_id "
                   "JOIN clientes c ON c.id = a.cliente_id WHERE a.fecha_liberacion IS NULL "
                   "AND ((k.zona = 'hombres' AND c.sexo <> 'M') "
                   "OR (k.zona = 'mujeres' AND c.sexo <> 'F'))") == 0
        assert uno("SELECT count(*) FROM casillero_asignaciones "
                   "WHERE fecha_liberacion IS NULL AND fecha_vencimiento IS NULL") == 0
        # Códigos de 6 dígitos secuenciales.
        assert uno("SELECT min(codigo) FROM clientes") == "000001"
        # RN-03: fecha_fin = inicio + duración - 1
        assert uno("SELECT count(*) FROM membresias m JOIN planes p ON p.id = m.plan_id "
                   "WHERE julianday(m.fecha_fin) - julianday(m.fecha_inicio) <> p.duracion_dias - 1") == 0
        # Los pagos con tarjeta o transferencia tienen referencia.
        assert uno("SELECT count(*) FROM pagos WHERE metodo <> 'efectivo' AND referencia IS NULL") == 0
    motor.dispose()


def test_seed_no_escribe_sobre_una_base_con_clientes(tmp_path):
    import pytest

    ruta = str(tmp_path / "seed.db")
    seed_datos.main(["--clientes", "20", "--db", ruta])
    with pytest.raises(SystemExit):
        seed_datos.main(["--clientes", "20", "--db", ruta])


def test_formato_pesos():
    assert pesos(120000) == "$ 120.000"
    assert pesos(0) == "$ 0"
