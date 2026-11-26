"""Guarda la contraseña de backups en el PC para que las copias automáticas no la pidan.

En Windows se protege con DPAPI (`CryptProtectData`): solo el mismo usuario de Windows,
en el mismo PC, puede recuperarla. El archivo vive en la carpeta de datos
(`clave_backups.bin`) y **no** se incluye dentro de los backups.

Fuera de Windows (solo desarrollo y pruebas) no hay DPAPI: se guarda sin protección
real y se avisa en la pantalla. La aplicación del gimnasio corre en Windows.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

NOMBRE_ARCHIVO = "clave_backups.bin"
_ENTROPIA = b"Enforma-backups-v1"


class ProtectorClave(Protocol):
    protege_de_verdad: bool

    def proteger(self, datos: bytes) -> bytes: ...

    def desproteger(self, datos: bytes) -> bytes: ...


class ProtectorDPAPI:
    """DPAPI de Windows por medio de ctypes (sin dependencias extra)."""

    protege_de_verdad = True

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Blob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        self._ctypes = ctypes
        self._Blob = Blob
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def _blob(self, datos: bytes):
        buffer = self._ctypes.create_string_buffer(datos, len(datos))
        return self._Blob(len(datos), self._ctypes.cast(buffer, self._ctypes.POINTER(
            self._ctypes.c_char))), buffer

    def _llamar(self, funcion, datos: bytes, proteger: bool) -> bytes:
        entrada, _b1 = self._blob(datos)
        entropia, _b2 = self._blob(_ENTROPIA)
        salida = self._Blob()
        CRYPTPROTECT_UI_FORBIDDEN = 0x01
        descripcion = "Enforma" if proteger else None  # al desproteger es un parámetro de salida
        ok = funcion(self._ctypes.byref(entrada), descripcion, self._ctypes.byref(entropia),
                     None, None, CRYPTPROTECT_UI_FORBIDDEN, self._ctypes.byref(salida))
        if not ok:
            raise OSError("Windows no pudo proteger o recuperar la contraseña de backups.")
        try:
            return self._ctypes.string_at(salida.pbData, salida.cbData)
        finally:
            self._kernel32.LocalFree(salida.pbData)

    def proteger(self, datos: bytes) -> bytes:
        return self._llamar(self._crypt32.CryptProtectData, datos, True)

    def desproteger(self, datos: bytes) -> bytes:
        return self._llamar(self._crypt32.CryptUnprotectData, datos, False)


class ProtectorSinCifrar:
    """Solo para desarrollo fuera de Windows y pruebas: no protege nada."""

    protege_de_verdad = False

    def proteger(self, datos: bytes) -> bytes:
        return datos

    def desproteger(self, datos: bytes) -> bytes:
        return datos


def protector_del_sistema() -> ProtectorClave:
    if os.name == "nt":
        return ProtectorDPAPI()
    return ProtectorSinCifrar()


class AlmacenClave:
    """Lee y guarda la contraseña de backups protegida en la carpeta de datos."""

    def __init__(self, carpeta: Path, protector: ProtectorClave | None = None):
        self.ruta = carpeta / NOMBRE_ARCHIVO
        self.protector = protector or protector_del_sistema()

    def existe(self) -> bool:
        return self.ruta.is_file()

    def leer(self) -> str | None:
        if not self.existe():
            return None
        try:
            return self.protector.desproteger(self.ruta.read_bytes()).decode("utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            return None  # p. ej. la carpeta se copió a otro PC o a otro usuario de Windows

    def guardar(self, clave: str) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_bytes(self.protector.proteger(clave.encode("utf-8")))
        os.replace(temporal, self.ruta)
