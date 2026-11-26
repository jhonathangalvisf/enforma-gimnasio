"""Permisos por rol (sección 2): se validan en servicios, no solo en la interfaz."""

from __future__ import annotations

import pytest

from gimnasio.servicios.errores import ErrorPermiso
from gimnasio.servicios.permisos import (
    PERMISOS_POR_ROL, ROL_ADMIN, ROL_RECEPCION, Permiso, UsuarioActual, exigir, tiene_permiso,
)
from tests.conftest import CLAVE_PRUEBA

SOLO_ADMIN = {
    Permiso.MODIFICAR_CLIENTE_COMPLETO, Permiso.ACTIVAR_CLIENTES, Permiso.ANULAR_PAGOS,
    Permiso.ELIMINAR_ASISTENCIA_CUALQUIERA, Permiso.REPORTES_TODOS,
    Permiso.ADMINISTRAR_CATALOGOS, Permiso.CONFIGURACION, Permiso.USUARIOS,
    Permiso.AUDITORIA, Permiso.BACKUPS,
}


def test_tabla_de_permisos_coincide_con_la_especificacion():
    assert PERMISOS_POR_ROL[ROL_ADMIN] == frozenset(Permiso)
    assert PERMISOS_POR_ROL[ROL_RECEPCION] == frozenset(Permiso) - SOLO_ADMIN


@pytest.mark.parametrize("permiso", sorted(SOLO_ADMIN, key=lambda p: p.value))
def test_recepcion_no_tiene_permisos_de_admin(permiso):
    assert not tiene_permiso(ROL_RECEPCION, permiso)
    assert tiene_permiso(ROL_ADMIN, permiso)


def test_sin_sesion_o_rol_desconocido_no_hay_permisos():
    with pytest.raises(ErrorPermiso, match="iniciar sesión"):
        exigir(None, Permiso.AYUDA)
    extraño = UsuarioActual(id=99, usuario="x", nombre_completo="X", rol="jefe")
    with pytest.raises(ErrorPermiso):
        exigir(extraño, Permiso.AYUDA)


def test_recepcion_no_puede_administrar_usuarios(servicios, recepcion, admin):
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.listar(recepcion)
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.crear(recepcion, "Intruso Uno", "intruso", "admin", CLAVE_PRUEBA)
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.desactivar(recepcion, admin.id)
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.restablecer_clave(recepcion, admin.id, CLAVE_PRUEBA)
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.editar(
            recepcion, recepcion.id, nombre_completo="Rita", usuario="rita", rol="admin"
        )


def test_recepcion_no_puede_ver_auditoria_ni_cambiar_configuracion(servicios, recepcion):
    with pytest.raises(ErrorPermiso):
        servicios.auditoria.consultar(recepcion)
    with pytest.raises(ErrorPermiso):
        servicios.configuracion.guardar(recepcion, {"dias_por_vencer": 3})
    with pytest.raises(ErrorPermiso):
        servicios.configuracion.guardar_logo(recepcion, None)
    # Leer parámetros sí puede (Recepción usa el umbral de "por vencer").
    assert servicios.configuracion.obtener("dias_por_vencer") == 5


def test_rol_falsificado_se_rechaza_contra_la_base(servicios, recepcion):
    """Aunque alguien construya un UsuarioActual con rol admin, el servicio relee la base."""
    falso = UsuarioActual(id=recepcion.id, usuario="rita", nombre_completo="Rita", rol="admin")
    with pytest.raises(ErrorPermiso):
        servicios.usuarios.listar(falso)
