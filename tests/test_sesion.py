"""Inicio de sesión, bloqueo por intentos e inactividad (RF-A1, RF-A2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from gimnasio.modelos import Auditoria, Usuario
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorValidacion, UsuarioBloqueado
from gimnasio.servicios.sesion import ControlInactividad
from tests.conftest import CLAVE_PRUEBA


def acciones(sesion):
    return [a.accion for a in sesion.scalars(select(Auditoria).order_by(Auditoria.id))]


def test_clave_se_guarda_con_argon2(servicios, admin, sesion):
    usuario = sesion.get(Usuario, admin.id)
    assert usuario.hash_clave.startswith("$argon2")
    assert CLAVE_PRUEBA not in usuario.hash_clave


def test_login_correcto_sin_importar_mayusculas_del_usuario(servicios, admin, sesion, reloj):
    actual = servicios.sesion.iniciar_sesion("  ADMIN ", CLAVE_PRUEBA)
    assert actual.id == admin.id and actual.es_admin
    usuario = sesion.get(Usuario, admin.id)
    assert usuario.ultimo_login == reloj.ahora
    assert acciones(sesion)[-1] == "login_exitoso"


def test_login_usuario_inexistente_usa_mensaje_generico(servicios, admin, sesion):
    with pytest.raises(ErrorAutenticacion) as e:
        servicios.sesion.iniciar_sesion("nadie", "loquesea123")
    assert str(e.value) == "Usuario o contraseña incorrectos."
    assert acciones(sesion)[-1] == "login_fallido"


def test_clave_incorrecta_suma_intentos_y_bloquea_al_quinto(servicios, admin, sesion, reloj):
    for _ in range(4):
        with pytest.raises(ErrorAutenticacion) as e:
            servicios.sesion.iniciar_sesion("admin", "incorrecta")
        assert not isinstance(e.value, UsuarioBloqueado)
    with pytest.raises(UsuarioBloqueado) as e:
        servicios.sesion.iniciar_sesion("admin", "incorrecta")
    assert e.value.minutos_restantes == 15
    # Bloqueado, ni la clave correcta entra.
    reloj.avanzar(minutes=10)
    with pytest.raises(UsuarioBloqueado) as e:
        servicios.sesion.iniciar_sesion("admin", CLAVE_PRUEBA)
    assert e.value.minutos_restantes == 5
    assert "usuario_bloqueado" in acciones(sesion)
    # Pasado el bloqueo vuelve a entrar y los intentos quedan en cero.
    reloj.avanzar(minutes=5)
    servicios.sesion.iniciar_sesion("admin", CLAVE_PRUEBA)
    sesion.expire_all()
    usuario = sesion.get(Usuario, admin.id)
    assert usuario.intentos_fallidos == 0 and usuario.bloqueado_hasta is None


def test_login_correcto_reinicia_intentos(servicios, admin, sesion):
    for _ in range(3):
        with pytest.raises(ErrorAutenticacion):
            servicios.sesion.iniciar_sesion("admin", "incorrecta")
    servicios.sesion.iniciar_sesion("admin", CLAVE_PRUEBA)
    assert sesion.get(Usuario, admin.id).intentos_fallidos == 0


def test_intentos_y_minutos_de_bloqueo_configurables(servicios, admin, reloj):
    servicios.configuracion.guardar(admin, {"intentos_login_max": 3, "minutos_bloqueo": 2})
    for _ in range(2):
        with pytest.raises(ErrorAutenticacion):
            servicios.sesion.iniciar_sesion("admin", "incorrecta")
    with pytest.raises(UsuarioBloqueado) as e:
        servicios.sesion.iniciar_sesion("admin", "incorrecta")
    assert e.value.minutos_restantes == 2
    reloj.avanzar(minutes=2)
    assert servicios.sesion.iniciar_sesion("admin", CLAVE_PRUEBA)


def test_usuario_desactivado_no_entra(servicios, admin, recepcion):
    servicios.usuarios.desactivar(admin, recepcion.id)
    with pytest.raises(ErrorAutenticacion, match="desactivado"):
        servicios.sesion.iniciar_sesion("rita", CLAVE_PRUEBA)


def test_cerrar_sesion_queda_en_auditoria(servicios, admin, sesion):
    servicios.sesion.cerrar_sesion(admin)
    servicios.sesion.cerrar_sesion(admin, por_inactividad=True)
    assert acciones(sesion)[-2:] == ["logout", "cierre_por_inactividad"]


def test_cambiar_clave_propia(servicios, admin, recepcion):
    actual = servicios.sesion.iniciar_sesion("rita", CLAVE_PRUEBA)
    assert actual.debe_cambiar_clave  # creada por el admin: debe cambiarla
    with pytest.raises(ErrorAutenticacion):
        servicios.sesion.cambiar_clave_propia(actual, "mala-clave", "NuevaClave2")
    with pytest.raises(ErrorValidacion):
        servicios.sesion.cambiar_clave_propia(actual, CLAVE_PRUEBA, "corta")
    with pytest.raises(ErrorAutenticacion):
        servicios.sesion.cambiar_clave_propia(actual, CLAVE_PRUEBA, CLAVE_PRUEBA)
    nuevo = servicios.sesion.cambiar_clave_propia(actual, CLAVE_PRUEBA, "NuevaClave2")
    assert not nuevo.debe_cambiar_clave
    assert servicios.sesion.iniciar_sesion("rita", "NuevaClave2")
    with pytest.raises(ErrorAutenticacion):
        servicios.sesion.iniciar_sesion("rita", CLAVE_PRUEBA)


def test_auditoria_nunca_guarda_claves(servicios, admin, recepcion, sesion):
    with pytest.raises(ErrorAutenticacion):
        servicios.sesion.iniciar_sesion("rita", "OtraClave99")
    servicios.usuarios.restablecer_clave(admin, recepcion.id, "Temporal123")
    textos = " ".join(a.detalle_json or "" for a in sesion.scalars(select(Auditoria)))
    for clave in (CLAVE_PRUEBA, "OtraClave99", "Temporal123", "$argon2"):
        assert clave not in textos


def test_inactividad_vence_en_pantallas_administrativas(reloj):
    control = ControlInactividad(15, reloj)
    reloj.avanzar(minutes=14, seconds=59)
    assert not control.vencido()
    control.registrar_actividad()
    reloj.avanzar(minutes=14)
    assert not control.vencido()
    reloj.avanzar(minutes=1)
    assert control.vencido()


def test_inactividad_no_cierra_recepcion(reloj):
    control = ControlInactividad(15, reloj)
    reloj.avanzar(hours=3)
    assert not control.vencido(en_recepcion=True)
    assert control.vencido(en_recepcion=False)
