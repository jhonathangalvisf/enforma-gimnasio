"""Protección real de la contraseña de copias con DPAPI (pendiente de la Fase 9).

Solo corre en Windows: en el workflow de GitHub Actions (windows-latest) y en el PC del
gimnasio con `pytest tests/test_dpapi_windows.py`. En Linux se omite; ahí las pruebas
de copias usan un protector sustituto.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DPAPI solo existe en Windows")

CLAVE = "copias-Enforma-ñandú-2026"


def test_proteger_y_recuperar():
    from gimnasio.backup.protector import ProtectorDPAPI, protector_del_sistema

    protector = protector_del_sistema()
    assert isinstance(protector, ProtectorDPAPI) and protector.protege_de_verdad
    protegido = protector.proteger(CLAVE.encode("utf-8"))
    assert CLAVE.encode("utf-8") not in protegido and len(protegido) > 100
    assert protector.desproteger(protegido).decode("utf-8") == CLAVE
    # Cada protección usa datos aleatorios: dos resultados distintos para la misma clave.
    assert protector.proteger(CLAVE.encode("utf-8")) != protegido


def test_almacen_guarda_el_archivo_protegido(tmp_path):
    from gimnasio.backup.protector import NOMBRE_ARCHIVO, AlmacenClave

    almacen = AlmacenClave(tmp_path)
    almacen.guardar(CLAVE)
    crudo = (tmp_path / NOMBRE_ARCHIVO).read_bytes()
    assert CLAVE.encode("utf-8") not in crudo
    assert AlmacenClave(tmp_path).leer() == CLAVE


def test_archivo_alterado_no_se_puede_leer(tmp_path):
    from gimnasio.backup.protector import NOMBRE_ARCHIVO, AlmacenClave

    AlmacenClave(tmp_path).guardar(CLAVE)
    ruta = tmp_path / NOMBRE_ARCHIVO
    datos = bytearray(ruta.read_bytes())
    datos[len(datos) // 2] ^= 0xFF
    ruta.write_bytes(bytes(datos))
    assert AlmacenClave(tmp_path).leer() is None  # se pide crearla de nuevo


def test_otra_entropia_no_descifra(tmp_path, monkeypatch):
    """La entropía propia de Enforma impide que otro programa del mismo usuario la lea
    llamando a DPAPI sin ella."""
    from gimnasio.backup import protector as modulo

    protegido = modulo.ProtectorDPAPI().proteger(CLAVE.encode("utf-8"))
    monkeypatch.setattr(modulo, "_ENTROPIA", b"otro-programa")
    with pytest.raises(OSError):
        modulo.ProtectorDPAPI().desproteger(protegido)


def test_diagnostico_reporta_dpapi_ok(tmp_path):
    from gimnasio import diagnostico
    from gimnasio.backup.protector import AlmacenClave

    assert diagnostico.revisar_dpapi().estado == diagnostico.OK
    AlmacenClave(tmp_path).guardar(CLAVE)
    assert diagnostico.revisar_clave_guardada(tmp_path).estado == diagnostico.OK


def test_servicio_de_copias_usa_dpapi(servicios, admin):
    servicios.backups.configurar_clave(admin, CLAVE, CLAVE)
    estado = servicios.backups.estado(admin)
    assert estado.clave_configurada and estado.clave_protegida
