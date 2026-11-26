"""Diagnóstico de la instalación: `Enforma.exe --diagnostico` (o el acceso directo
"Diagnóstico de Enforma" del menú Inicio, o `python scripts/diagnostico.py`).

Revisa sin modificar nada que la instalación esté completa y que este PC pueda
proteger la contraseña de las copias con DPAPI de Windows. Si hay copias, verifica
la más reciente restaurándola en una carpeta temporal. No muestra datos de clientes:
solo conteos y estados.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import closing
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from gimnasio import __version__
from gimnasio import config as cfg
from gimnasio import rutas

OK = "OK"
AVISO = "AVISO"
FALLA = "FALLA"


@dataclass
class Revision:
    nombre: str
    estado: str  # OK, AVISO o FALLA
    detalle: str


@dataclass
class Informe:
    revisiones: list[Revision]
    creado: datetime

    @property
    def correcto(self) -> bool:
        return all(r.estado != FALLA for r in self.revisiones)

    def texto(self) -> str:
        lineas = [
            f"Diagnóstico de Enforma {__version__} — {self.creado:%d/%m/%Y %H:%M}",
            "",
        ]
        for r in self.revisiones:
            lineas.append(f"[{r.estado:5}] {r.nombre}: {r.detalle}")
        lineas += ["", "Resultado: " + ("todo en orden." if self.correcto else
                                       "hay fallas; envíe este informe a soporte.")]
        return "\n".join(lineas)


# --- revisiones individuales ----------------------------------------------------
def revisar_archivos_programa() -> Revision:
    faltan = []
    for ruta in (rutas.carpeta_programa() / "migraciones" / "env.py",
                 rutas.recurso("alerta.wav"), rutas.recurso("enforma.ico"),
                 rutas.carpeta_ayuda() / "inicio.md"):
        if not ruta.is_file():
            faltan.append(ruta.name)
    if faltan:
        return Revision("Archivos del programa", FALLA,
                        "faltan " + ", ".join(faltan) + ". Reinstale Enforma.")
    return Revision("Archivos del programa", OK,
                    "completos" + (" (ejecutable)" if rutas.empaquetado() else " (desarrollo)"))


def revisar_zona_horaria() -> Revision:
    try:
        ahora = datetime.now(cfg.ZONA_HORARIA)
    except Exception as e:  # tzdata ausente en el ejecutable
        return Revision("Zona horaria", FALLA, f"no se pudo cargar America/Bogota ({e}).")
    return Revision("Zona horaria", OK, f"America/Bogota, hora local {ahora:%H:%M}")


def revisar_carpeta_datos(carpeta: Path) -> Revision:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba = carpeta / f".prueba_{secrets.token_hex(4)}"
        prueba.write_bytes(b"ok")
        prueba.unlink()
    except OSError as e:
        return Revision("Carpeta de datos", FALLA, f"{carpeta} no se puede escribir ({e}).")
    return Revision("Carpeta de datos", OK, str(carpeta))


def revisar_base(carpeta: Path) -> Revision:
    base = carpeta / "enforma.db"
    if not base.is_file():
        return Revision("Base de datos", AVISO,
                        "todavía no existe (se crea al abrir Enforma por primera vez).")
    try:
        with closing(sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True)) as c:
            integridad = c.execute("PRAGMA quick_check").fetchone()[0]
            revision = c.execute("SELECT version_num FROM alembic_version").fetchone()
            clientes = c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]
    except sqlite3.Error as e:
        return Revision("Base de datos", FALLA, f"no se pudo abrir ({e}).")
    revision = revision[0] if revision else "?"
    try:
        from gimnasio.servicios.backups import revisiones_conocidas
        conocidas = revisiones_conocidas()
    except Exception:
        conocidas = []
    if integridad != "ok":
        return Revision("Base de datos", FALLA, f"integridad: {integridad}. Restaure una copia.")
    if conocidas and revision != conocidas[-1]:
        estado, nota = AVISO, " (se actualiza al abrir Enforma)"
        if revision not in conocidas:
            estado, nota = FALLA, " (es de una versión más nueva del programa)"
        return Revision("Base de datos", estado, f"esquema {revision}{nota}")
    tamano = base.stat().st_size / 1_048_576
    return Revision("Base de datos", OK,
                    f"íntegra, esquema {revision}, {clientes} clientes, {tamano:.1f} MB")


def revisar_dpapi() -> Revision:
    """Prueba real de DPAPI: proteger y recuperar un texto al azar con el usuario actual."""
    from gimnasio.backup.protector import protector_del_sistema
    protector = protector_del_sistema()
    if not protector.protege_de_verdad:
        estado = FALLA if os.name == "nt" else AVISO
        return Revision("Protección DPAPI", estado,
                        "no disponible: este sistema no es Windows (solo desarrollo).")
    muestra = ("prueba-" + secrets.token_hex(8)).encode()
    try:
        protegido = protector.proteger(muestra)
        recuperado = protector.desproteger(protegido)
    except OSError as e:
        return Revision("Protección DPAPI", FALLA, f"Windows no pudo usar DPAPI ({e}).")
    if recuperado != muestra or muestra in protegido:
        return Revision("Protección DPAPI", FALLA, "el texto protegido no coincide.")
    return Revision("Protección DPAPI", OK,
                    f"funciona para el usuario de Windows {os.environ.get('USERNAME', '')}".strip())


def revisar_clave_guardada(carpeta: Path) -> Revision:
    from gimnasio.backup.protector import AlmacenClave
    almacen = AlmacenClave(carpeta)
    if not almacen.existe():
        return Revision("Contraseña de copias", AVISO,
                        "no se ha creado (el administrador la crea en Copias de seguridad).")
    clave = almacen.leer()
    if clave is None:
        return Revision("Contraseña de copias", FALLA,
                        "existe pero este usuario de Windows no la puede leer (¿se copió de "
                        "otro PC o usuario?). Créela de nuevo en Copias de seguridad.")
    if almacen.protector.protege_de_verdad and clave.encode("utf-8") in almacen.ruta.read_bytes():
        return Revision("Contraseña de copias", FALLA, "el archivo no está protegido.")
    if not almacen.protector.protege_de_verdad:
        return Revision("Contraseña de copias", AVISO, "guardada sin DPAPI (no es Windows).")
    return Revision("Contraseña de copias", OK, "guardada y protegida con DPAPI")


def destino_configurado(carpeta_datos: Path) -> Path | None:
    """Lee `backup_destino` de la base sin abrir la aplicación (solo lectura)."""
    base = carpeta_datos / "enforma.db"
    if not base.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True)) as c:
            fila = c.execute("SELECT valor FROM config WHERE clave = 'backup_destino'").fetchone()
    except sqlite3.Error:
        return None
    return Path(fila[0]) if fila and fila[0] else None


def buscar_ultima_copia(carpetas: list[Path]):
    from gimnasio.servicios.backups import TIPO_AUTOMATICO, TIPO_MANUAL, listar_carpeta
    copias = []
    for carpeta in carpetas:
        copias += [c for c in listar_carpeta(carpeta, str(carpeta))
                   if c.legible and c.tipo in (TIPO_AUTOMATICO, TIPO_MANUAL)]
    return max(copias, key=lambda c: c.creado) if copias else None


def revisar_ultima_copia(carpeta: Path) -> Revision:
    from gimnasio.backup.cifrado import ErrorBackup
    from gimnasio.backup.protector import AlmacenClave
    from gimnasio.formato import fecha_hora_local
    from gimnasio.servicios.backups import CARPETA_LOCAL, abrir_y_revisar

    carpetas = [carpeta / CARPETA_LOCAL]
    externo = destino_configurado(carpeta)
    if externo:
        carpetas.append(externo)
    ultima = buscar_ultima_copia(carpetas)
    if ultima is None:
        return Revision("Última copia de seguridad", AVISO, "no hay copias todavía.")
    cuando = fecha_hora_local(ultima.creado)
    clave = AlmacenClave(carpeta).leer()
    if clave is None:
        return Revision("Última copia de seguridad", AVISO,
                        f"del {cuando}; no se verificó porque no hay contraseña guardada.")
    with tempfile.TemporaryDirectory(prefix="enforma_diagnostico_") as temporal:
        try:
            resumen = abrir_y_revisar(ultima.ruta, clave, Path(temporal))
        except ErrorBackup as e:
            return Revision("Última copia de seguridad", FALLA, f"del {cuando}: {e}")
    return Revision("Última copia de seguridad", OK,
                    f"del {cuando}, se restauró en una carpeta temporal: {resumen.texto()}")


def diagnosticar(carpeta: Path | None = None, verificar_copia: bool = True) -> Informe:
    carpeta = Path(carpeta) if carpeta else cfg.carpeta_datos()
    revisiones = [
        Revision("Versión", OK, f"Enforma {__version__}"),
        revisar_archivos_programa(),
        revisar_zona_horaria(),
        revisar_carpeta_datos(carpeta),
        revisar_base(carpeta),
        revisar_dpapi(),
        revisar_clave_guardada(carpeta),
    ]
    if verificar_copia:
        revisiones.append(revisar_ultima_copia(carpeta))
    return Informe(revisiones, datetime.now(cfg.ZONA_HORARIA))


def ejecutar(reporte: Path | None = None) -> int:
    """Corre el diagnóstico, lo guarda en `<datos>/logs/diagnostico.txt` (o en `reporte`)
    y lo muestra: en la consola si hay, si no en una ventana."""
    from gimnasio.registro import carpeta_logs

    informe = diagnosticar()
    texto = informe.texto()
    destino = reporte or carpeta_logs(cfg.carpeta_datos()) / "diagnostico.txt"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto + "\n", encoding="utf-8")
    except OSError:
        pass
    if reporte is None:
        if sys.stdout is not None:  # el .exe de Windows no tiene consola
            print(texto)
        else:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            caja = QMessageBox(QMessageBox.Icon.Information if informe.correcto
                               else QMessageBox.Icon.Warning, "Diagnóstico de Enforma",
                               "Todo en orden." if informe.correcto else
                               "Se encontraron fallas.")
            caja.setInformativeText(f"{texto}\n\nEl informe se guardó en:\n{destino}")
            caja.exec()
            del app
    return 0 if informe.correcto else 1
