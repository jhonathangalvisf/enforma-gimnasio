"""Gestión de usuarios (RF-A3): crear, editar, desactivar, restablecer. Nunca borrar."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from gimnasio.modelos import Auditoria, Usuario
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.usuarios import ServicioUsuarios
from tests.conftest import CLAVE_PRUEBA


def test_primer_arranque_crea_admin_una_sola_vez(servicios):
    assert not servicios.usuarios.hay_usuarios()
    actual = servicios.usuarios.crear_primer_administrador("Ana Admin", "admin", CLAVE_PRUEBA)
    assert actual.es_admin and servicios.usuarios.hay_usuarios()
    with pytest.raises(ErrorValidacion, match="Ya existen usuarios"):
        servicios.usuarios.crear_primer_administrador("Otro", "otro", CLAVE_PRUEBA)


def test_crear_usuario_valida_datos(servicios, admin):
    with pytest.raises(ErrorValidacion):
        servicios.usuarios.crear(admin, "Lu", "lucia", "recepcion", CLAVE_PRUEBA)
    with pytest.raises(ErrorValidacion):
        servicios.usuarios.crear(admin, "Lucía Gómez", "lucía gómez", "recepcion", CLAVE_PRUEBA)
    with pytest.raises(ErrorValidacion):
        servicios.usuarios.crear(admin, "Lucía Gómez", "lucia", "jefe", CLAVE_PRUEBA)
    with pytest.raises(ErrorValidacion, match="8 caracteres"):
        servicios.usuarios.crear(admin, "Lucía Gómez", "lucia", "recepcion", "1234567")
    with pytest.raises(ErrorValidacion, match="Ya existe"):
        servicios.usuarios.crear(admin, "Otra Admin", "ADMIN", "admin", CLAVE_PRUEBA)
    creado = servicios.usuarios.crear(admin, "  Lucía   Gómez ", "Lucia", "recepcion", CLAVE_PRUEBA)
    assert creado.nombre_completo == "Lucía Gómez" and creado.usuario == "lucia"
    assert creado.debe_cambiar_clave


def test_editar_usuario_registra_cambios(servicios, admin, recepcion, sesion):
    servicios.usuarios.editar(
        admin, recepcion.id, nombre_completo="Rita Pérez", usuario="rita", rol="recepcion"
    )
    registro = sesion.scalars(select(Auditoria).order_by(Auditoria.id.desc())).first()
    assert registro.accion == "usuario_editado"
    assert "Rita Pérez" in registro.detalle_json and "Rita Recepción" in registro.detalle_json


def test_no_se_borran_usuarios_se_desactivan(servicios, admin, recepcion, sesion):
    assert not hasattr(ServicioUsuarios, "eliminar")
    datos = servicios.usuarios.desactivar(admin, recepcion.id)
    assert not datos.activo
    assert sesion.scalar(select(func.count(Usuario.id))) == 2
    assert servicios.usuarios.activar(admin, recepcion.id).activo


def test_siempre_queda_un_admin_activo(servicios, admin):
    with pytest.raises(ErrorValidacion, match="propio usuario"):
        servicios.usuarios.desactivar(admin, admin.id)
    with pytest.raises(ErrorValidacion, match="sí mismo"):
        servicios.usuarios.editar(
            admin, admin.id, nombre_completo="Ana Admin", usuario="admin", rol="recepcion"
        )
    otro = servicios.usuarios.crear(admin, "Beto Admin", "beto", "admin", CLAVE_PRUEBA)
    servicios.usuarios.desactivar(admin, otro.id)
    servicios.usuarios.activar(admin, otro.id)
    # Con otro admin activo sí se le puede cambiar el rol a uno de ellos.
    servicios.usuarios.editar(
        admin, otro.id, nombre_completo="Beto Admin", usuario="beto", rol="recepcion"
    )


def test_restablecer_clave_desbloquea_y_obliga_a_cambiarla(servicios, admin, recepcion, sesion):
    from gimnasio.servicios.errores import ErrorAutenticacion

    for _ in range(5):
        with pytest.raises(ErrorAutenticacion):
            servicios.sesion.iniciar_sesion("rita", "incorrecta")
    servicios.usuarios.restablecer_clave(admin, recepcion.id, "Temporal123")
    actual = servicios.sesion.iniciar_sesion("rita", "Temporal123")
    assert actual.debe_cambiar_clave


def test_usuario_desactivado_pierde_permisos_con_sesion_abierta(servicios, admin):
    otro = servicios.usuarios.crear(admin, "Beto Admin", "beto", "admin", CLAVE_PRUEBA)
    beto = servicios.sesion.iniciar_sesion("beto", CLAVE_PRUEBA)
    servicios.usuarios.desactivar(admin, otro.id)
    with pytest.raises(ErrorPermiso, match="desactivado"):
        servicios.usuarios.listar(beto)


def test_cambio_de_rol_aplica_de_inmediato(servicios, admin):
    otro = servicios.usuarios.crear(admin, "Beto Admin", "beto", "admin", CLAVE_PRUEBA)
    beto = servicios.sesion.iniciar_sesion("beto", CLAVE_PRUEBA)
    servicios.usuarios.editar(
        admin, otro.id, nombre_completo="Beto Admin", usuario="beto", rol="recepcion"
    )
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.listar(beto)
