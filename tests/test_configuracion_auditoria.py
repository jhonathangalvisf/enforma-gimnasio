"""Configuración (RF-K1) y visor de auditoría (RF-K3)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from gimnasio.modelos import Auditoria, Config
from gimnasio.servicios.configuracion import PARAMETROS
from gimnasio.servicios.errores import ErrorAutenticacion, ErrorValidacion


def test_valores_por_defecto(servicios):
    valores = servicios.configuracion.obtener_todos()
    assert set(valores) == {p.clave for p in PARAMETROS}
    assert valores["dias_por_vencer"] == 5
    assert valores["minutos_inactividad"] == 15
    assert valores["intentos_login_max"] == 5
    assert valores["asistencia_duplicada"] == "avisar"


def test_guardar_solo_registra_lo_que_cambia(servicios, admin, sesion):
    cambios = servicios.configuracion.guardar(
        admin, {"dias_por_vencer": "7", "minutos_inactividad": 15, "gimnasio_nit": " 900.123 "}
    )
    assert cambios == {"dias_por_vencer": 7, "gimnasio_nit": "900.123"}
    assert servicios.configuracion.obtener("dias_por_vencer") == 7
    registro = sesion.scalars(
        select(Auditoria).where(Auditoria.accion == "configuracion_cambiada")
    ).one()
    assert "dias_por_vencer" in registro.detalle_json
    assert "minutos_inactividad" not in registro.detalle_json
    # Guardar sin cambios no crea registros nuevos.
    assert servicios.configuracion.guardar(admin, {"dias_por_vencer": 7}) == {}


@pytest.mark.parametrize("cambios", [
    {"dias_por_vencer": 0},
    {"dias_por_vencer": "abc"},
    {"minutos_inactividad": 500},
    {"asistencia_duplicada": "ignorar"},
    {"gimnasio_nombre": "x" * 121},
    {"clave_inventada": 1},
])
def test_valores_invalidos_no_guardan_nada(servicios, admin, sesion, cambios):
    with pytest.raises(ErrorValidacion):
        servicios.configuracion.guardar(admin, {"gimnasio_nit": "123", **cambios})
    assert sesion.get(Config, "gimnasio_nit") is None


def test_consecutivo_de_recibos_no_retrocede(servicios, admin):
    servicios.configuracion.guardar(admin, {"recibo_siguiente": 100})
    with pytest.raises(ErrorValidacion, match="no puede ser menor"):
        servicios.configuracion.guardar(admin, {"recibo_siguiente": 99})
    servicios.configuracion.guardar(admin, {"recibo_siguiente": 150})


def test_logo_se_copia_a_la_carpeta_de_datos(servicios, admin, tmp_path):
    origen = tmp_path / "origen" / "mi logo.PNG"
    origen.parent.mkdir()
    origen.write_bytes(b"\x89PNG\r\n\x1a\nfalso")
    destino = servicios.configuracion.guardar_logo(admin, origen)
    assert destino.name == "logo.png" and destino.read_bytes() == origen.read_bytes()
    assert servicios.configuracion.ruta_logo() == destino
    with pytest.raises(ErrorValidacion):
        servicios.configuracion.guardar_logo(admin, tmp_path / "documento.pdf")
    servicios.configuracion.guardar_logo(admin, None)
    assert servicios.configuracion.ruta_logo() is None


def test_visor_de_auditoria_filtra(servicios, admin, recepcion, reloj):
    with pytest.raises(ErrorAutenticacion):
        servicios.sesion.iniciar_sesion("rita", "incorrecta")
    servicios.sesion.iniciar_sesion("admin", "ClaveSegura1")
    todos = servicios.auditoria.consultar(admin)
    assert todos[0].accion == "login_exitoso"  # más reciente primero
    fallidos = servicios.auditoria.consultar(admin, accion="login_fallido")
    assert len(fallidos) == 1 and fallidos[0].usuario == "rita"
    assert fallidos[0].descripcion == "Intento fallido de inicio de sesión"
    de_rita = servicios.auditoria.consultar(admin, usuario_id=recepcion.id)
    assert {f.accion for f in de_rita} == {"login_fallido"}
    assert servicios.auditoria.consultar(admin, texto="clave incorrecta")


def test_visor_de_auditoria_usa_dias_de_bogota(servicios, admin, reloj, sesion):
    # 26/11/2026 03:00 UTC = 25/11/2026 22:00 en Bogotá.
    from datetime import datetime, timezone

    from gimnasio.servicios import auditoria

    auditoria.registrar(sesion, "logout", "usuarios", usuario_id=admin.id,
                        momento=datetime(2026, 11, 26, 3, 0, tzinfo=timezone.utc))
    sesion.commit()
    del_25 = servicios.auditoria.consultar(admin, desde=date(2026, 11, 25), hasta=date(2026, 11, 25))
    assert [f.accion for f in del_25] == ["logout"]
    del_26 = servicios.auditoria.consultar(admin, desde=date(2026, 11, 26), hasta=date(2026, 11, 26))
    assert "logout" not in [f.accion for f in del_26]
