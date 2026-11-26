"""Fase 11: rutas dentro del ejecutable, instancia única, registro de errores,
diagnóstico de la instalación, archivos de empaquetado y arranque."""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gimnasio import __version__, diagnostico, registro as reg, rutas  # noqa: E402
from gimnasio.db.migraciones import actualizar_esquema, configuracion_alembic  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
EMPAQUETADO = RAIZ / "empaquetado"


# --- rutas ----------------------------------------------------------------------
def test_rutas_en_desarrollo():
    assert not rutas.empaquetado()
    assert (rutas.carpeta_programa() / "migraciones" / "env.py").is_file()
    for nombre in ("alerta.wav", "enforma.ico", "icono.png", "logo_enforma.png"):
        assert rutas.recurso(nombre).is_file(), nombre
    assert (rutas.carpeta_ayuda() / "inicio.md").is_file()


def test_rutas_dentro_del_ejecutable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert rutas.empaquetado()
    assert rutas.carpeta_programa() == tmp_path
    assert rutas.recurso("alerta.wav") == tmp_path / "gimnasio" / "recursos" / "alerta.wav"
    assert rutas.carpeta_ayuda() == tmp_path / "gimnasio" / "ayuda"


def test_alembic_usa_la_carpeta_del_programa():
    cfg = configuracion_alembic()
    assert Path(cfg.get_main_option("script_location")) == rutas.carpeta_programa() / "migraciones"


def test_url_con_porcentaje_de_windows():
    """En Windows la URL de la base trae "C%3A/...": Alembic no debe fallar (restaurar)."""
    url = "sqlite:///C%3A/Users/gimnasio/AppData/Roaming/Enforma/enforma.db"
    assert configuracion_alembic(url).get_main_option("sqlalchemy.url") == url


def test_version_unica():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = {attr = "gimnasio.__version__"}' in texto


# --- archivos de empaquetado --------------------------------------------------------
def test_spec_incluye_todo_lo_que_el_programa_lee_en_disco():
    spec = (EMPAQUETADO / "enforma.spec").read_text(encoding="utf-8")
    for necesario in ("migraciones", "ayuda", "recursos", "tzdata",
                      "enforma.ico", "console=False", "collect_submodules"):
        assert necesario in spec, necesario


def test_instalador_inno_setup():
    from gimnasio.ui.instancia import MUTEX_WINDOWS

    iss = (EMPAQUETADO / "enforma.iss").read_text(encoding="utf-8")
    assert f"AppMutex={MUTEX_WINDOWS}" in iss  # pide cerrar Enforma antes de actualizar
    assert "Spanish.isl" in iss
    assert "{autodesktop}" in iss and "{group}" in iss  # accesos directos
    assert "--diagnostico" in iss
    # Los datos viven en %APPDATA%: el desinstalador nunca los borra.
    assert "{userappdata}" not in iss and "{app}\\datos" not in iss
    assert "AppId={{" in iss


def test_workflow_windows():
    flujo = (RAIZ / ".github" / "workflows" / "windows.yml").read_text(encoding="utf-8")
    for paso in ("windows-latest", "python-version: \"3.12\"", "pytest", "pyinstaller",
                 "ISCC", "--solo-migrar", "--diagnostico", "/VERYSILENT", "upload-artifact"):
        assert paso in flujo, paso


# --- registro de errores ------------------------------------------------------------
@pytest.fixture
def registro_temporal(tmp_path):
    ganchos = (sys.excepthook, __import__("threading").excepthook)
    ruta = reg.configurar_registro(tmp_path)
    yield ruta
    reg.cerrar_registro()
    sys.excepthook, __import__("threading").excepthook = ganchos


def _leer(ruta: Path) -> str:
    for manejador in reg.registro.handlers:
        manejador.flush()
    return ruta.read_text(encoding="utf-8")


def test_registro_en_la_carpeta_de_datos(registro_temporal, tmp_path):
    assert registro_temporal == tmp_path / "logs" / "enforma.log"
    reg.registrar_arranque("9.9.9", False, tmp_path)
    reg.configurar_registro(tmp_path)  # reconfigurar no duplica líneas
    reg.registro.info("segunda")
    texto = _leer(registro_temporal)
    assert "Enforma 9.9.9 iniciado" in texto and texto.count("segunda") == 1
    manejador = reg.registro.handlers[0]
    assert isinstance(manejador, logging.handlers.RotatingFileHandler)
    assert manejador.maxBytes == reg.TAMANO_MAXIMO and manejador.backupCount == reg.COPIAS


def test_error_inesperado_se_registra_sin_variables_y_avisa(registro_temporal):
    avisos = []
    reg.instalar_manejador_errores(avisos.append)

    def falla():
        documento_secreto = "1234567890"  # noqa: F841 (una variable local no debe salir)
        raise ValueError("x" * 500)

    try:
        falla()
    except ValueError:
        sys.excepthook(*sys.exc_info())
    texto = _leer(registro_temporal)
    assert "Error inesperado: ValueError" in texto
    assert "test_instalacion.py" in texto and "falla" in texto
    assert "1234567890" not in texto.replace('documento_secreto = "1234567890"', "")
    assert "x" * 201 not in texto  # el mensaje se recorta
    assert len(avisos) == 1 and avisos[0].startswith("ValueError")


def test_un_aviso_que_falla_no_produce_otro_error(registro_temporal):
    def aviso_roto(_texto):
        raise RuntimeError("sin ventana")

    reg.instalar_manejador_errores(aviso_roto)
    try:
        raise KeyError("a")
    except KeyError:
        sys.excepthook(*sys.exc_info())
    assert "KeyError" in _leer(registro_temporal)


# --- instancia única ----------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _esperar(condicion, segundos=3.0):
    from PySide6.QtCore import QCoreApplication

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        QCoreApplication.processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return False


def test_segunda_copia_no_abre_y_trae_la_primera_al_frente(qapp, tmp_path):
    from gimnasio.ui.instancia import InstanciaUnica

    primera = InstanciaUnica(tmp_path)
    assert primera.adquirir() and primera.es_principal
    llamadas = []
    primera.activar.connect(lambda: llamadas.append(1))
    segunda = InstanciaUnica(tmp_path)
    assert not segunda.adquirir(espera_ms=50)
    assert not segunda.es_principal
    assert _esperar(lambda: llamadas), "la primera copia no recibió el aviso"
    primera.liberar()
    tercera = InstanciaUnica(tmp_path)  # al cerrar la primera, se puede volver a abrir
    assert tercera.adquirir()
    tercera.liberar()


def test_instancias_de_carpetas_distintas_no_se_estorban(qapp, tmp_path):
    from gimnasio.ui.instancia import InstanciaUnica, nombre_canal

    a, b = InstanciaUnica(tmp_path / "a"), InstanciaUnica(tmp_path / "b")
    assert nombre_canal(tmp_path / "a") != nombre_canal(tmp_path / "b")
    assert a.adquirir() and b.adquirir()
    a.liberar()
    b.liberar()


def test_candado_de_un_programa_que_se_cerro_mal_no_bloquea(qapp, tmp_path):
    from gimnasio.ui.instancia import ARCHIVO_CANDADO, InstanciaUnica

    # Candado dejado por un proceso que ya no existe (PID imposible).
    (tmp_path / ARCHIVO_CANDADO).write_text("999999999\nEnforma\notro-equipo-no\n")
    instancia = InstanciaUnica(tmp_path)
    if not instancia.adquirir():
        # Qt solo descarta candados viejos del mismo equipo: con otro nombre de equipo
        # se mantiene por seguridad. Con el nombre de este equipo se libera solo.
        from PySide6.QtCore import QSysInfo

        (tmp_path / ARCHIVO_CANDADO).write_text(
            f"999999999\nEnforma\n{QSysInfo.machineHostName()}\n")
        assert instancia.adquirir()
    instancia.liberar()


def test_traer_al_frente_muestra_la_ventana_abierta(qapp, servicios, admin):
    from gimnasio.ui.aplicacion import Aplicacion

    aplicacion = Aplicacion(qapp, servicios)
    aplicacion.traer_al_frente()  # sin ventana todavía: no falla
    aplicacion.abrir_ventana(admin)
    aplicacion.ventana.showMinimized()
    aplicacion.traer_al_frente()
    assert aplicacion.ventana.isVisible() and not aplicacion.ventana.isMinimized()
    aplicacion.ventana.close()
    aplicacion._temporizador_backup.stop()


def test_version_visible(qapp, servicios, admin):
    from gimnasio.ui.dialogos import DialogoLogin
    from gimnasio.ui.ventana_principal import VentanaPrincipal

    ventana = VentanaPrincipal(servicios, admin)
    assert ventana.etiqueta_version.text() == f"Enforma {__version__}"
    login = DialogoLogin(servicios)
    textos = [w.text() for w in login.findChildren(type(ventana.etiqueta_version))]
    assert f"Versión {__version__}" in textos
    ventana.close()


# --- logo por defecto en los recibos --------------------------------------------------
def test_logo_de_enforma_por_defecto(servicios, admin, tmp_path):
    assert servicios.configuracion.ruta_logo() == rutas.recurso("logo_enforma.png")
    servicios.configuracion.guardar_logo(admin, None)  # el admin lo quita: sin logo
    assert servicios.configuracion.ruta_logo() is None


# --- diagnóstico ---------------------------------------------------------------------
def _estado(informe, nombre):
    return next(r for r in informe.revisiones if r.nombre == nombre)


def test_diagnostico_de_una_instalacion_nueva(tmp_path):
    informe = diagnostico.diagnosticar(tmp_path)
    assert informe.correcto
    assert _estado(informe, "Archivos del programa").estado == diagnostico.OK
    assert _estado(informe, "Zona horaria").estado == diagnostico.OK
    assert _estado(informe, "Base de datos").estado == diagnostico.AVISO
    assert _estado(informe, "Última copia de seguridad").estado == diagnostico.AVISO
    dpapi = _estado(informe, "Protección DPAPI").estado
    assert dpapi == (diagnostico.OK if os.name == "nt" else diagnostico.AVISO)
    assert "Resultado: todo en orden." in informe.texto()


def test_diagnostico_de_la_base(tmp_path):
    url = f"sqlite:///{(tmp_path / 'enforma.db').as_posix()}"
    actualizar_esquema(url)
    revision = diagnostico.revisar_base(tmp_path)
    assert revision.estado == diagnostico.OK and "0 clientes" in revision.detalle
    with sqlite3.connect(tmp_path / "enforma.db") as c:
        c.execute("UPDATE alembic_version SET version_num = 'zzzz_futura'")
    assert diagnostico.revisar_base(tmp_path).estado == diagnostico.FALLA


def test_diagnostico_verifica_la_ultima_copia(servicios, admin, sesion, tmp_path):
    from tests.conftest import nuevo_cliente

    nuevo_cliente(sesion, 1)
    sesion.commit()
    servicios.backups.configurar_clave(admin, "copias-Enforma-2026", "copias-Enforma-2026")
    assert servicios.backups.hacer_backup(admin, "manual").exitoso
    clave = diagnostico.revisar_clave_guardada(tmp_path)
    assert clave.estado == (diagnostico.OK if os.name == "nt" else diagnostico.AVISO)
    copia = diagnostico.revisar_ultima_copia(tmp_path)
    assert copia.estado == diagnostico.OK, copia.detalle
    assert "1 clientes" in copia.detalle or "clientes" in copia.detalle

    # Copia dañada: el diagnóstico la marca como falla.
    archivo = next((tmp_path / "backups").glob("*.enfbak"))
    datos = bytearray(archivo.read_bytes())
    datos[-10] ^= 0xFF
    archivo.write_bytes(bytes(datos))
    assert diagnostico.revisar_ultima_copia(tmp_path).estado == diagnostico.FALLA


def test_diagnostico_clave_ilegible(tmp_path):
    from gimnasio.backup.protector import NOMBRE_ARCHIVO

    (tmp_path / NOMBRE_ARCHIVO).write_bytes(b"\xff\xfe no es texto ni DPAPI")
    assert diagnostico.revisar_clave_guardada(tmp_path).estado == diagnostico.FALLA


def test_diagnostico_detecta_archivos_faltantes(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    revision = diagnostico.revisar_archivos_programa()
    assert revision.estado == diagnostico.FALLA and "Reinstale" in revision.detalle


# --- arranque ------------------------------------------------------------------------
def test_main_diagnostico_con_reporte(monkeypatch, tmp_path, registro_temporal):
    from gimnasio import app

    monkeypatch.setenv("ENFORMA_DATOS", str(tmp_path / "datos"))
    reporte = tmp_path / "informe.txt"
    assert app.main(["--diagnostico", "--reporte", str(reporte)]) == 0
    assert "Diagnóstico de Enforma" in reporte.read_text(encoding="utf-8")
    assert (tmp_path / "datos" / "logs" / "enforma.log").is_file()


def test_main_solo_migrar(monkeypatch, tmp_path, registro_temporal):
    from gimnasio import app

    monkeypatch.setenv("ENFORMA_DATOS", str(tmp_path / "datos"))
    monkeypatch.delenv("ENFORMA_DB_URL", raising=False)
    assert app.main(["--solo-migrar"]) == 0
    with sqlite3.connect(tmp_path / "datos" / "enforma.db") as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()


def test_manual_en_pdf(tmp_path):
    sys.path.insert(0, str(EMPAQUETADO))
    try:
        import manual_pdf
    finally:
        sys.path.remove(str(EMPAQUETADO))
    ruta = manual_pdf.generar(salida=tmp_path / "manual.pdf")
    datos = ruta.read_bytes()
    assert datos.startswith(b"%PDF") and len(datos) > 20_000
