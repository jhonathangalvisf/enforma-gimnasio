"""Fixtures comunes: cada prueba usa una base nueva creada con las migraciones."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from gimnasio.db.engine import crear_fabrica_sesiones, crear_motor
from gimnasio.db.migraciones import actualizar_esquema
from gimnasio.modelos import Casillero, Cliente, Usuario


# Al terminar, Qt destruye sus ventanas mientras Python se cierra. En Windows eso
# a veces falla después de que todas las pruebas pasaron, y el proceso termina con
# código 1 (pasó en GitHub con «515 passed» y con «594 passed»). Por eso, en Windows,
# apenas se imprime el resumen se sale directamente con el resultado real de pytest,
# antes de que los complementos de pytest se cierren y Python empiece a destruir Qt.
def _salir_con(resultado: int) -> None:
    import os
    import sys

    if sys.platform == "win32" and "PySide6" in sys.modules:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(resultado)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    # Envuelve a los demás: lo de después del `yield` corre cuando ya se imprimió el resumen.
    yield
    _salir_con(int(session.exitstatus))


@pytest.fixture(autouse=True)
def _clave_admin_simulada(request, monkeypatch):
    """Pagos e inscripciones de Recepción necesitan la clave de un administrador.
    Las pruebas que no tratan de eso la simulan; las que sí, llevan la marca
    `clave_admin_real` (ver tests/test_autorizaciones.py)."""
    if request.node.get_closest_marker("clave_admin_real"):
        return
    from gimnasio.servicios.autorizaciones import ServicioAutorizaciones

    monkeypatch.setattr(ServicioAutorizaciones, "verificar",
                        lambda self, actual, autorizacion, *paras: None)
    try:
        import gimnasio.ui.autorizacion as ui_autorizacion
    except ImportError:  # sin Qt
        return
    monkeypatch.setattr(ui_autorizacion, "PEDIR", lambda *args: (True, None))


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


def dejar_saldo_antiguo(fabrica, pago_id: int, monto: int, usuario_id: int | None = None) -> None:
    """Simula un saldo que quedó de antes de quitar los abonos (27/11/2026): baja el
    monto de un pago ya guardado. Hoy el sistema solo acepta pagos completos."""
    from gimnasio.modelos import Pago

    with fabrica() as s:
        pago = s.get(Pago, pago_id)
        pago.monto = monto
        if usuario_id is not None:  # quién cobró ese pago antiguo
            pago.usuario_id = usuario_id
        s.commit()
