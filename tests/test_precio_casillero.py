"""Precio sugerido del casillero en $1, como los planes (decisión del gimnasio):
instalaciones nuevas y bases que lo tenían en $0 (migración 0011)."""

from __future__ import annotations

import pytest
from alembic import command
from sqlalchemy import text

from gimnasio.db.engine import crear_motor
from gimnasio.db.migraciones import configuracion_alembic


def test_instalacion_nueva_sugiere_un_peso(servicios, admin):
    assert servicios.configuracion.obtener("casillero_precio") == 1


@pytest.fixture
def url_0010(tmp_path):
    url = f"sqlite:///{(tmp_path / 'existente.db').as_posix()}"
    command.upgrade(configuracion_alembic(url), "0010")
    return url


@pytest.mark.parametrize("guardado, esperado", [("0", "1"), ("25000", "25000")])
def test_migracion_pasa_de_cero_a_un_peso(url_0010, guardado, esperado):
    motor = crear_motor(url_0010)
    with motor.begin() as c:
        c.execute(text("INSERT INTO config (clave, valor) VALUES ('casillero_precio', :v)"),
                  {"v": guardado})
    command.upgrade(configuracion_alembic(url_0010), "head")
    with motor.connect() as c:
        assert c.scalar(text("SELECT valor FROM config WHERE clave='casillero_precio'")) \
            == esperado
        cambios = c.scalar(text("SELECT COUNT(*) FROM auditoria "
                                "WHERE accion='configuracion_cambiada'"))
    assert cambios == (1 if guardado == "0" else 0)
    motor.dispose()


def test_migracion_sin_precio_guardado_no_hace_nada(url_0010):
    command.upgrade(configuracion_alembic(url_0010), "head")
    motor = crear_motor(url_0010)
    with motor.connect() as c:
        assert c.scalar(text("SELECT COUNT(*) FROM config WHERE clave='casillero_precio'")) == 0
    motor.dispose()
