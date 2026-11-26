"""Fixtures comunes: cada prueba usa una base nueva creada con las migraciones."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
from gimnasio.db.migraciones import actualizar_esquema
from gimnasio.modelos import Casillero, Cliente, Usuario


@pytest.fixture
def url_bd(tmp_path) -> str:
    url = f"sqlite:///{(tmp_path / 'prueba.db').as_posix()}"
    actualizar_esquema(url)
    return url


@pytest.fixture
def motor(url_bd):
    motor = crear_motor(url_bd)
    yield motor
    motor.dispose()


@pytest.fixture
def sesion(motor):
    with crear_fabrica_sesiones(motor)() as s:
        yield s


def nuevo_cliente(sesion: Session, n: int, **campos) -> Cliente:
    datos = dict(
        codigo=f"{n:06d}", qr_token=f"qr-{n}", tipo_documento="CC", documento=f"10{n:06d}",
        nombres="Prueba", apellidos=f"Cliente {n}", sexo="M",
        fecha_nacimiento=date(1990, 1, 1),
    )
    datos.update(campos)
    cliente = Cliente(**datos)
    sesion.add(cliente)
    sesion.flush()
    return cliente


@pytest.fixture
def datos_basicos(sesion):
    """Un usuario, tres clientes y tres casilleros."""
    usuario = Usuario(nombre_completo="Admin", usuario="admin", hash_clave="x", rol="admin")
    sesion.add(usuario)
    clientes = [nuevo_cliente(sesion, i) for i in (1, 2, 3)]
    casilleros = [Casillero(numero=f"{i:03d}", zona="mixto") for i in (1, 2, 3)]
    sesion.add_all(casilleros)
    sesion.commit()
    return usuario, clientes, casilleros
