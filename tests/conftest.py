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


class RelojFalso:
    """Reloj controlable para probar bloqueos e inactividad sin esperar."""

    def __init__(self):
        from datetime import datetime, timezone

        self.ahora = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.ahora

    def avanzar(self, **delta):
        from datetime import timedelta

        self.ahora += timedelta(**delta)


CLAVE_PRUEBA = "ClaveSegura1"


@pytest.fixture
def reloj():
    return RelojFalso()


@pytest.fixture
def servicios(motor, reloj, tmp_path):
    from gimnasio.servicios.contenedor import crear_servicios

    return crear_servicios(crear_fabrica_sesiones(motor), carpeta_datos=tmp_path, reloj=reloj)


@pytest.fixture
def admin(servicios):
    """Primer administrador creado como en el primer arranque."""
    return servicios.usuarios.crear_primer_administrador("Ana Admin", "admin", CLAVE_PRUEBA)


@pytest.fixture
def recepcion(servicios, admin):
    datos = servicios.usuarios.crear(admin, "Rita Recepción", "rita", "recepcion", CLAVE_PRUEBA)
    from gimnasio.servicios.permisos import UsuarioActual

    return UsuarioActual(id=datos.id, usuario=datos.usuario,
                         nombre_completo=datos.nombre_completo, rol=datos.rol)
