"""La migración crea el esquema completo y coincide con los modelos."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from gimnasio.modelos import Base

TABLAS = {
    "usuarios", "clientes", "contactos", "planes", "membresias", "pagos", "asistencias",
    "casilleros", "casillero_asignaciones", "invitados", "invitado_asistencias", "alertas",
    "biometria", "auditoria", "backups_log", "config",
}

INDICES_OBLIGATORIOS = {
    ("clientes", ("codigo",)), ("clientes", ("qr_token",)), ("clientes", ("documento",)),
    ("clientes", ("apellidos", "nombres")), ("clientes", ("estado",)),
    ("contactos", ("valor",)), ("contactos", ("cliente_id",)),
    ("membresias", ("cliente_id", "fecha_fin")), ("membresias", ("fecha_fin",)),
    ("pagos", ("cliente_id",)), ("pagos", ("fecha_hora",)),
    ("asistencias", ("cliente_id", "fecha")), ("asistencias", ("fecha",)),
    ("invitados", ("documento",)), ("invitado_asistencias", ("invitado_id",)),
    ("auditoria", ("fecha_hora",)),
}


def test_migracion_crea_todas_las_tablas(motor):
    assert TABLAS <= set(inspect(motor).get_table_names())


def test_indices_obligatorios(motor):
    inspector = inspect(motor)
    existentes = {
        (tabla, tuple(ix["column_names"]))
        for tabla in TABLAS
        for ix in inspector.get_indexes(tabla)
    }
    faltantes = INDICES_OBLIGATORIOS - existentes
    assert not faltantes, f"Faltan índices: {faltantes}"


def test_indices_parciales_de_casilleros(motor):
    with motor.connect() as cx:
        sql = dict(cx.execute(text(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%activo'"
        )).all())
    for nombre in ("uq_casillero_activo", "uq_cliente_casillero_activo"):
        assert "UNIQUE" in sql[nombre] and "WHERE fecha_liberacion IS NULL" in sql[nombre]


def test_pragmas_wal_y_claves_foraneas(motor):
    with motor.connect() as cx:
        assert cx.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert cx.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_modelos_y_migracion_coinciden(motor):
    """Si alguien cambia un modelo sin crear la migración, esta prueba falla."""
    with motor.connect() as cx:
        diferencias = compare_metadata(MigrationContext.configure(cx), Base.metadata)
    assert diferencias == []
