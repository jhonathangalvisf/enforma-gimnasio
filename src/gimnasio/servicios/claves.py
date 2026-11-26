"""Hash y verificación de contraseñas con argon2 (nunca se guardan en texto plano)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from gimnasio.servicios.errores import ErrorValidacion

LONGITUD_MINIMA = 8
_hasher = PasswordHasher()
# Hash de relleno: se verifica contra él cuando el usuario no existe, para que la
# respuesta tarde lo mismo y no delate qué nombres de usuario existen.
_HASH_RELLENO = _hasher.hash("clave-de-relleno-no-usar")


def validar_clave(clave: str) -> None:
    if len(clave) < LONGITUD_MINIMA:
        raise ErrorValidacion(
            f"La contraseña debe tener al menos {LONGITUD_MINIMA} caracteres."
        )
    if clave.strip() != clave:
        raise ErrorValidacion("La contraseña no puede empezar ni terminar con espacios.")


def generar_hash(clave: str) -> str:
    return _hasher.hash(clave)


def verificar(hash_guardado: str | None, clave: str) -> bool:
    try:
        return _hasher.verify(hash_guardado or _HASH_RELLENO, clave)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_rehash(hash_guardado: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hash_guardado)
    except InvalidHashError:
        return True
