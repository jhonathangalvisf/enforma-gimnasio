"""Formato del archivo de backup cifrado (.enfbak).

Estructura del archivo:

    MAGICO (8 bytes) | largo del encabezado (4 bytes, big endian) | encabezado JSON | datos

- El **encabezado** va sin cifrar y solo tiene datos técnicos (fecha, tipo, versión del
  esquema, parámetros de scrypt, sal y nonce). Nunca datos de clientes. Permite listar
  las copias sin pedir la contraseña.
- Los **datos** son el zip cifrado con AES-256-GCM. La clave se deriva de la contraseña
  con scrypt. El encabezado completo se usa como "datos asociados" de GCM: si alguien
  cambia una letra del encabezado o del contenido, el descifrado falla.
"""

from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGICO = b"ENFBAK1\n"
VERSION_FORMATO = 1
EXTENSION = ".enfbak"
# scrypt: n=2^15, r=8, p=1 usa 32 MB de memoria y tarda ~0,1 s (recomendación OWASP).
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
_LARGO_MAXIMO_ENCABEZADO = 64 * 1024


class ErrorBackup(Exception):
    """Error al crear, leer o restaurar un backup. El mensaje se muestra al usuario."""


class ClaveIncorrecta(ErrorBackup):
    """La contraseña no corresponde o el archivo fue alterado (GCM no los distingue)."""


@dataclass(frozen=True)
class Encabezado:
    datos: dict  # lo que se escribió (creado_utc, tipo, revision, ...)
    crudo: bytes  # bytes exactos del encabezado (datos asociados de GCM)

    def get(self, clave: str, defecto=None):
        return self.datos.get(clave, defecto)


def _derivar_clave(clave: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    if not clave:
        raise ErrorBackup("La contraseña de backups no puede estar vacía.")
    return Scrypt(salt=sal, length=32, n=n, r=r, p=p).derive(clave.encode("utf-8"))


def cifrar(contenido: bytes, clave: str, metadatos: dict) -> bytes:
    """Devuelve el archivo .enfbak completo (encabezado + contenido cifrado)."""
    sal = os.urandom(16)
    nonce = os.urandom(12)
    encabezado = dict(metadatos)
    encabezado.update({
        "formato": VERSION_FORMATO,
        "kdf": {"nombre": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
                "sal": sal.hex()},
        "cifrado": "AES-256-GCM",
        "nonce": nonce.hex(),
    })
    crudo = json.dumps(encabezado, ensure_ascii=False, sort_keys=True).encode("utf-8")
    llave = _derivar_clave(clave, sal, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    cifrado = AESGCM(llave).encrypt(nonce, contenido, MAGICO + crudo)
    return MAGICO + struct.pack(">I", len(crudo)) + crudo + cifrado


def _separar(archivo: bytes) -> tuple[Encabezado, bytes]:
    if not archivo.startswith(MAGICO) or len(archivo) < len(MAGICO) + 4:
        raise ErrorBackup("El archivo no es una copia de seguridad de Enforma.")
    (largo,) = struct.unpack(">I", archivo[len(MAGICO):len(MAGICO) + 4])
    inicio = len(MAGICO) + 4
    if largo > _LARGO_MAXIMO_ENCABEZADO or inicio + largo > len(archivo):
        raise ErrorBackup("El archivo de copia está dañado (encabezado inválido).")
    crudo = archivo[inicio:inicio + largo]
    try:
        datos = json.loads(crudo.decode("utf-8"))
    except ValueError as e:
        raise ErrorBackup("El archivo de copia está dañado (encabezado ilegible).") from e
    if not isinstance(datos, dict) or datos.get("formato") != VERSION_FORMATO:
        raise ErrorBackup("La copia fue hecha con un formato que esta versión no reconoce.")
    return Encabezado(datos, crudo), archivo[inicio + largo:]


def leer_encabezado(ruta: Path) -> Encabezado:
    """Lee solo el encabezado (sin contraseña)."""
    with open(ruta, "rb") as f:
        inicio = f.read(len(MAGICO) + 4)
        if not inicio.startswith(MAGICO) or len(inicio) < len(MAGICO) + 4:
            raise ErrorBackup("El archivo no es una copia de seguridad de Enforma.")
        (largo,) = struct.unpack(">I", inicio[len(MAGICO):])
        if largo > _LARGO_MAXIMO_ENCABEZADO:
            raise ErrorBackup("El archivo de copia está dañado (encabezado inválido).")
        encabezado, _ = _separar(inicio + f.read(largo))
    return encabezado


def descifrar(archivo: bytes, clave: str) -> tuple[Encabezado, bytes]:
    encabezado, cifrado = _separar(archivo)
    kdf = encabezado.get("kdf") or {}
    try:
        sal = bytes.fromhex(kdf["sal"])
        nonce = bytes.fromhex(encabezado.get("nonce", ""))
        llave = _derivar_clave(clave, sal, int(kdf["n"]), int(kdf["r"]), int(kdf["p"]))
    except (KeyError, ValueError, TypeError) as e:
        raise ErrorBackup("El archivo de copia está dañado (parámetros inválidos).") from e
    try:
        contenido = AESGCM(llave).decrypt(nonce, cifrado, MAGICO + encabezado.crudo)
    except InvalidTag as e:
        raise ClaveIncorrecta(
            "La contraseña no es correcta o el archivo de copia fue modificado o está dañado."
        ) from e
    return encabezado, contenido
