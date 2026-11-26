"""Comprueba que la última copia de seguridad se puede restaurar (sección 8).

Restaura la copia más reciente en una carpeta temporal (sin tocar los datos del
gimnasio), revisa que la base abre, que pasa `PRAGMA integrity_check`, que su versión
del esquema la conoce este programa y que tiene datos. Al final borra la carpeta.

Uso:
    python scripts/verificar_backup.py                    # última copia de %APPDATA%\\Enforma
    python scripts/verificar_backup.py --archivo E:\\copias\\enforma_2026-11-26_210000.enfbak
    python scripts/verificar_backup.py --carpeta E:\\copias  # la más reciente de esa carpeta

La contraseña se toma de la guardada en este PC; si no hay (o con --pedir-clave), se
pregunta sin mostrarla. Devuelve código 0 si la copia está bien y 1 si no.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from gimnasio import config as cfg  # noqa: E402
from gimnasio.backup.cifrado import ErrorBackup  # noqa: E402
from gimnasio.backup.protector import AlmacenClave  # noqa: E402
from gimnasio.formato import fecha_hora_local, tamano_archivo  # noqa: E402
from gimnasio.servicios.backups import (  # noqa: E402
    CARPETA_LOCAL, TIPO_AUTOMATICO, TIPO_MANUAL, abrir_y_revisar, listar_carpeta,
    revisiones_conocidas,
)


def destino_configurado(carpeta_datos: Path) -> Path | None:
    """Lee `backup_destino` de la base sin abrir la aplicación (solo lectura)."""
    base = carpeta_datos / "enforma.db"
    if not base.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True) as c:
            fila = c.execute("SELECT valor FROM config WHERE clave = 'backup_destino'").fetchone()
    except sqlite3.Error:
        return None
    return Path(fila[0]) if fila and fila[0] else None


def buscar_ultima(carpetas: list[Path]):
    copias = []
    for carpeta in carpetas:
        copias += [c for c in listar_carpeta(carpeta, str(carpeta))
                   if c.legible and c.tipo in (TIPO_AUTOMATICO, TIPO_MANUAL)]
    return max(copias, key=lambda c: c.creado) if copias else None


def verificar(ruta: Path, clave: str) -> bool:
    print(f"Copia: {ruta}  ({tamano_archivo(ruta.stat().st_size)})")
    inicio = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="enforma_verificar_") as temporal:
        try:
            resumen = abrir_y_revisar(ruta, clave, Path(temporal))
        except ErrorBackup as e:
            print(f"ERROR: {e}")
            return False
        with sqlite3.connect(Path(temporal) / "enforma.db") as c:
            tablas = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    segundos = time.perf_counter() - inicio
    print(f"  Integridad: {resumen.integridad}   Tablas: {tablas}   Esquema: {resumen.revision}")
    print(f"  Contenido: {resumen.texto()}")
    if resumen.revision not in revisiones_conocidas():
        print("ERROR: la copia es de una versión más nueva del programa.")
        return False
    print(f"OK: la copia se restauró en una carpeta temporal y está completa ({segundos:.1f} s).")
    return True


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--archivo", type=Path, help="copia .enfbak a verificar")
    analizador.add_argument("--carpeta", type=Path, action="append",
                            help="carpeta donde buscar la copia más reciente (se puede repetir)")
    analizador.add_argument("--datos", type=Path, default=None,
                            help="carpeta de datos de Enforma (por defecto la configurada)")
    analizador.add_argument("--pedir-clave", action="store_true",
                            help="preguntar la contraseña aunque haya una guardada")
    opciones = analizador.parse_args(argumentos)

    datos = opciones.datos or cfg.carpeta_datos()
    if opciones.archivo:
        ruta = opciones.archivo
        if not ruta.is_file():
            print(f"ERROR: no existe {ruta}")
            return 1
    else:
        carpetas = opciones.carpeta or [datos / CARPETA_LOCAL]
        if not opciones.carpeta:
            externo = destino_configurado(datos)
            if externo:
                carpetas.append(externo)
        ultima = buscar_ultima(carpetas)
        if ultima is None:
            print("ERROR: no se encontró ninguna copia en " + ", ".join(map(str, carpetas)))
            return 1
        ruta = ultima.ruta
        print(f"Última copia: {fecha_hora_local(ultima.creado)}")

    clave = None if opciones.pedir_clave else AlmacenClave(datos).leer()
    if clave is None:
        clave = getpass.getpass("Contraseña de las copias: ")
    return 0 if verificar(ruta, clave) else 1


if __name__ == "__main__":
    sys.exit(main())
