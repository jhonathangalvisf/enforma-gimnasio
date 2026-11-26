"""Servicio de Ayuda (sección 3.9): temas por rol, contenido en Markdown y buscador."""

from __future__ import annotations

import re

import pytest

from gimnasio.servicios.ayuda import (
    CARPETA_AYUDA, TEMAS, ServicioAyuda, texto_plano,
)
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.permisos import ROL_ADMIN, ROL_RECEPCION, UsuarioActual

ADMIN = UsuarioActual(1, "admin", "Ana Admin", ROL_ADMIN)
RECEPCION = UsuarioActual(2, "rita", "Rita Recepción", ROL_RECEPCION)


@pytest.fixture
def ayuda() -> ServicioAyuda:
    return ServicioAyuda()


def test_cada_tema_tiene_su_archivo_con_titulo(ayuda):
    for tema in TEMAS:
        ruta = CARPETA_AYUDA / f"{tema.clave}.md"
        assert ruta.exists(), ruta
        texto = ruta.read_text(encoding="utf-8")
        assert texto.startswith("# "), tema.clave
        assert len(texto_plano(texto)) > 500, f"{tema.clave}: contenido demasiado corto"


def test_temas_de_la_especificacion(ayuda):
    """RF-H1: clientes, asistencia, casilleros, invitados, pagos, recepción, reportes,
    backups y usuarios."""
    claves = {t.clave for t in ayuda.temas(ADMIN)}
    assert {"clientes", "asistencia", "casilleros", "invitados", "pagos", "recepcion",
            "reportes", "backups", "usuarios", "configuracion", "inicio"} <= claves


def test_cada_modulo_del_menu_tiene_tema():
    from gimnasio.ui.ventana_principal import MODULOS

    claves = {t.clave for t in TEMAS}
    for modulo in MODULOS:
        assert modulo.clave in claves or modulo.clave == "ayuda", modulo.clave


def test_recepcion_no_ve_temas_de_administrador(ayuda):
    claves = [t.clave for t in ayuda.temas(RECEPCION)]
    assert claves[0] == "inicio"
    assert {"recepcion", "clientes", "pagos", "reportes"} <= set(claves)
    assert not {"configuracion", "usuarios", "backups"} & set(claves)
    with pytest.raises(ErrorPermiso):
        ayuda.contenido(RECEPCION, "configuracion")
    assert ayuda.contenido(ADMIN, "configuracion").startswith("# Configuración")


def test_sin_sesion_no_hay_ayuda(ayuda):
    with pytest.raises(ErrorPermiso):
        ayuda.temas(None)


def test_tema_inexistente(ayuda):
    with pytest.raises(ErrorValidacion):
        ayuda.contenido(ADMIN, "no-existe")


def test_tema_contextual(ayuda):
    assert ayuda.tema_contextual(ADMIN, "casilleros") == "casilleros"
    assert ayuda.tema_contextual(RECEPCION, "configuracion") == "inicio"
    assert ayuda.tema_contextual(ADMIN, None) == "inicio"
    assert ayuda.tema_contextual(ADMIN, "ayuda") == "inicio"


def test_enlaces_entre_temas_apuntan_a_temas_que_existen(ayuda):
    claves = {t.clave for t in TEMAS}
    for tema in TEMAS:
        for destino in re.findall(r"\]\(tema:([a-z_]+)\)", ayuda.contenido(ADMIN, tema.clave)):
            assert destino in claves, f"{tema.clave} enlaza a «{destino}»"


def test_buscar_sin_tildes_ni_mayusculas(ayuda):
    con = [r.clave for r in ayuda.buscar(ADMIN, "Recepción")]
    sin = [r.clave for r in ayuda.buscar(ADMIN, "RECEPCION")]
    assert con == sin and con[0] == "recepcion"


def test_buscar_ordena_por_relevancia_y_trae_fragmento(ayuda):
    resultados = ayuda.buscar(ADMIN, "abono")
    assert resultados[0].clave == "pagos"
    assert resultados[0].coincidencias >= 3
    assert "abono" in resultados[0].fragmento.lower()


def test_buscar_exige_todas_las_palabras(ayuda):
    claves = [r.clave for r in ayuda.buscar(ADMIN, "casillero sugerido liberar")]
    assert claves[0] == "casilleros"
    assert "usuarios" not in claves
    assert ayuda.buscar(ADMIN, "palabraquenoexiste") == []
    assert ayuda.buscar(ADMIN, "   ") == []


def test_buscar_respeta_el_rol(ayuda):
    assert "configuracion" in [r.clave for r in ayuda.buscar(ADMIN, "prefijo")]
    assert "configuracion" not in [r.clave for r in ayuda.buscar(RECEPCION, "prefijo")]


def test_archivo_faltante_da_un_mensaje_claro(tmp_path):
    with pytest.raises(ErrorValidacion, match="inicio.md"):
        ServicioAyuda(tmp_path).contenido(ADMIN, "inicio")


def test_el_contenido_se_puede_cambiar_sin_tocar_la_logica(tmp_path):
    (tmp_path / "inicio.md").write_text("# Hola\n\nTexto **nuevo** de prueba.", encoding="utf-8")
    servicio = ServicioAyuda(tmp_path)
    assert "nuevo" in servicio.contenido(ADMIN, "inicio")


def test_texto_plano_quita_marcas():
    assert texto_plano("## Título\n\n**Negrita** y [enlace](tema:clientes) | celda |") == (
        "Título Negrita y enlace celda")
