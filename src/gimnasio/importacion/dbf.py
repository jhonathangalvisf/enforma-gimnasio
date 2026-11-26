"""Lector mínimo de tablas dBase III (.DBF), solo lectura.

El programa anterior guardaba cada tabla en un archivo .DBF: una cabecera con los
campos y luego registros de ancho fijo. Aquí solo se leen; nunca se escriben.
Los textos vienen en la página de códigos de MS-DOS (cp850).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

CODIFICACION = "cp850"


class ErrorDBF(Exception):
    """El archivo no es una tabla dBase válida o está dañado."""


@dataclass(frozen=True)
class Campo:
    nombre: str
    tipo: str  # C texto, N número, D fecha AAAAMMDD, L lógico (T/F), M memo
    largo: int
    decimales: int


@dataclass(frozen=True)
class TablaDBF:
    ruta: Path
    campos: list[Campo]
    registros: list[dict[str, str]]  # sin los marcados como borrados
    borrados: int

    @property
    def nombres_campos(self) -> set[str]:
        return {c.nombre for c in self.campos}


def leer_dbf(ruta: Path | str) -> TablaDBF:
    """Lee la tabla completa. Cada valor queda como texto sin espacios ni nulos.

    Los lógicos quedan en "T"/"F" (o vacío) y las fechas como "AAAAMMDD".
    """
    ruta = Path(ruta)
    datos = ruta.read_bytes()
    if len(datos) < 33:
        raise ErrorDBF(f"{ruta.name} está vacío o incompleto.")
    total, largo_cabecera, largo_registro = struct.unpack("<IHH", datos[4:12])
    campos: list[Campo] = []
    pos = 32
    while pos < len(datos) and datos[pos] != 0x0D:
        bloque = datos[pos:pos + 32]
        if len(bloque) < 32:
            raise ErrorDBF(f"La cabecera de {ruta.name} está dañada.")
        nombre = bloque[:11].split(b"\0")[0].decode("ascii", "replace").strip().upper()
        campos.append(Campo(nombre, chr(bloque[11]).upper(), bloque[16], bloque[17]))
        pos += 32
    if not campos or largo_registro <= 1:
        raise ErrorDBF(f"{ruta.name} no parece una tabla dBase.")
    registros: list[dict[str, str]] = []
    borrados = 0
    for i in range(total):
        inicio = largo_cabecera + i * largo_registro
        registro = datos[inicio:inicio + largo_registro]
        if len(registro) < largo_registro or registro[:1] == b"\x1a":
            break  # archivo cortado: se usa lo que alcanzó a leerse
        if registro[:1] == b"*":
            borrados += 1
            continue
        fila: dict[str, str] = {}
        p = 1
        for campo in campos:
            crudo = registro[p:p + campo.largo]
            fila[campo.nombre] = crudo.decode(CODIFICACION, "replace").replace("\0", "").strip()
            p += campo.largo
        registros.append(fila)
    return TablaDBF(ruta, campos, registros, borrados)


def buscar_archivo(carpeta: Path, nombre: str) -> Path | None:
    """Busca `nombre` en la carpeta sin importar mayúsculas (ENCLIE.DBF / enclie.dbf)."""
    objetivo = nombre.lower()
    for ruta in carpeta.iterdir():
        if ruta.is_file() and ruta.name.lower() == objetivo:
            return ruta
    return None
