"""Contenido de una copia: instantánea de la base + fotos + logo, en un zip.

- La base se copia con la API de backup de SQLite (`sqlite3.Connection.backup`), que
  da una copia coherente aunque el programa esté en uso (también lo que aún está en
  el archivo WAL). Luego se revisa con `PRAGMA integrity_check`.
- Las fotos de los clientes (`fotos/`) y el logo (`logo.*`) van dentro del mismo zip.
  Recibos y reportes no se copian: se pueden volver a generar.
- `manifiesto.json` resume qué tiene la copia (cuántos clientes, pagos, etc.).
"""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from gimnasio.backup.cifrado import ErrorBackup

NOMBRE_BASE = "enforma.db"
NOMBRE_MANIFIESTO = "manifiesto.json"
CARPETA_FOTOS = "fotos"
# Tablas que se cuentan en el resumen (sirve para comprobar que la copia "tiene datos").
TABLAS_RESUMEN = ("clientes", "membresias", "pagos", "asistencias", "casilleros",
                  "invitados", "usuarios")


@dataclass
class Resumen:
    revision: str | None
    conteos: dict[str, int] = field(default_factory=dict)
    fotos: int = 0
    integridad: str = ""

    @property
    def integra(self) -> bool:
        return self.integridad == "ok"

    @property
    def tiene_datos(self) -> bool:
        return self.conteos.get("usuarios", 0) > 0

    def como_dict(self) -> dict:
        return {"revision": self.revision, "conteos": self.conteos, "fotos": self.fotos,
                "integridad": self.integridad}

    def texto(self) -> str:
        nombres = {"clientes": "clientes", "membresias": "membresías", "pagos": "pagos",
                   "asistencias": "asistencias", "casilleros": "casilleros",
                   "invitados": "invitados", "usuarios": "usuarios"}
        partes = [f"{self.conteos.get(t, 0):,} {n}".replace(",", ".")
                  for t, n in nombres.items()]
        return ", ".join(partes) + f", {self.fotos} fotos"


def copiar_base(origen: Path, destino: Path) -> None:
    """Instantánea coherente de la base en uso (API de backup de SQLite)."""
    if not origen.is_file():
        raise ErrorBackup(f"No se encontró la base de datos en {origen}.")
    fuente = sqlite3.connect(origen, timeout=30)
    try:
        copia = sqlite3.connect(destino)
        try:
            fuente.backup(copia, pages=4096)
            # La copia queda en modo DELETE (un solo archivo, sin -wal ni -shm).
            copia.execute("PRAGMA journal_mode=DELETE")
        finally:
            copia.close()
    finally:
        fuente.close()


def revisar_base(ruta: Path) -> Resumen:
    """integrity_check, versión del esquema (Alembic) y conteos."""
    try:
        conexion = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise ErrorBackup(f"La base de la copia no se pudo abrir: {e}") from e
    try:
        try:
            filas = conexion.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError as e:
            raise ErrorBackup(f"La base de la copia está dañada: {e}") from e
        integridad = "ok" if filas == [("ok",)] else "; ".join(str(f[0]) for f in filas[:5])
        tablas = {f[0] for f in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        revision = None
        if "alembic_version" in tablas:
            fila = conexion.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = fila[0] if fila else None
        conteos = {t: conexion.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                   for t in TABLAS_RESUMEN if t in tablas}
        return Resumen(revision=revision, conteos=conteos, integridad=integridad)
    finally:
        conexion.close()


def _archivos_extra(carpeta_datos: Path) -> list[tuple[Path, str]]:
    """(ruta en disco, nombre dentro del zip) de fotos y logo."""
    archivos: list[tuple[Path, str]] = []
    fotos = carpeta_datos / CARPETA_FOTOS
    if fotos.is_dir():
        for ruta in sorted(fotos.rglob("*")):
            if ruta.is_file():
                archivos.append((ruta, f"{CARPETA_FOTOS}/{ruta.relative_to(fotos).as_posix()}"))
    for ruta in sorted(carpeta_datos.glob("logo.*")):
        if ruta.is_file():
            archivos.append((ruta, ruta.name))
    return archivos


def crear_paquete(ruta_base: Path, carpeta_datos: Path) -> tuple[bytes, Resumen]:
    """Arma el zip en memoria. Falla si la instantánea no pasa integrity_check."""
    with tempfile.TemporaryDirectory(prefix="enforma_backup_") as temporal:
        copia = Path(temporal) / NOMBRE_BASE
        copiar_base(ruta_base, copia)
        resumen = revisar_base(copia)
        if not resumen.integra:
            raise ErrorBackup(
                f"La revisión de integridad de la copia falló: {resumen.integridad}"
            )
        extras = _archivos_extra(carpeta_datos)
        resumen.fotos = sum(1 for _r, n in extras if n.startswith(f"{CARPETA_FOTOS}/"))
        memoria = io.BytesIO()
        with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(copia, NOMBRE_BASE)
            for ruta, nombre in extras:
                zf.write(ruta, nombre)
            zf.writestr(NOMBRE_MANIFIESTO, json.dumps(resumen.como_dict(), ensure_ascii=False))
    return memoria.getvalue(), resumen


def _nombre_seguro(nombre: str) -> bool:
    ruta = Path(nombre)
    return not ruta.is_absolute() and ".." not in ruta.parts and "\\" not in nombre


def extraer_paquete(contenido: bytes, carpeta: Path) -> Resumen:
    """Extrae el zip en `carpeta` y revisa la base. Devuelve su resumen."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
            nombres = zf.namelist()
            if NOMBRE_BASE not in nombres:
                raise ErrorBackup("La copia no contiene la base de datos.")
            for nombre in nombres:
                if not _nombre_seguro(nombre):
                    raise ErrorBackup("La copia contiene rutas no válidas.")
            zf.extractall(carpeta)
    except zipfile.BadZipFile as e:
        raise ErrorBackup("El contenido de la copia está dañado.") from e
    resumen = revisar_base(carpeta / NOMBRE_BASE)
    fotos = carpeta / CARPETA_FOTOS
    resumen.fotos = sum(1 for r in fotos.rglob("*") if r.is_file()) if fotos.is_dir() else 0
    return resumen


def reemplazar_datos(extraido: Path, ruta_base: Path, carpeta_datos: Path) -> None:
    """Pone la base, las fotos y el logo extraídos en lugar de los actuales.

    El motor de la base debe estar cerrado (sin conexiones) antes de llamar.
    """
    for sufijo in ("-wal", "-shm", "-journal"):
        sobrante = ruta_base.with_name(ruta_base.name + sufijo)
        if sobrante.exists():
            sobrante.unlink()
    nueva = ruta_base.with_name(ruta_base.name + ".restaurando")
    shutil.copy2(extraido / NOMBRE_BASE, nueva)
    nueva.replace(ruta_base)

    fotos_actuales = carpeta_datos / CARPETA_FOTOS
    fotos_nuevas = extraido / CARPETA_FOTOS
    anterior = carpeta_datos / (CARPETA_FOTOS + ".anterior")
    if anterior.exists():
        shutil.rmtree(anterior)
    if fotos_actuales.exists():
        fotos_actuales.rename(anterior)
    if fotos_nuevas.is_dir():
        shutil.copytree(fotos_nuevas, fotos_actuales)
    else:
        fotos_actuales.mkdir(parents=True, exist_ok=True)
    if anterior.exists():
        shutil.rmtree(anterior, ignore_errors=True)

    for logo in carpeta_datos.glob("logo.*"):
        logo.unlink()
    for logo in extraido.glob("logo.*"):
        shutil.copy2(logo, carpeta_datos / logo.name)
