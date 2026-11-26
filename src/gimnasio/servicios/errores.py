"""Errores de negocio. Sus mensajes están en español y se pueden mostrar al usuario."""

from __future__ import annotations


class ErrorNegocio(Exception):
    """Base de todos los errores que la interfaz muestra tal cual."""


class ErrorValidacion(ErrorNegocio):
    """Datos inválidos o una regla de negocio que impide la operación."""


class ErrorPermiso(ErrorNegocio):
    """El usuario actual no tiene permiso para la acción."""


class ErrorAutenticacion(ErrorNegocio):
    """Usuario o contraseña incorrectos, o usuario desactivado."""


class UsuarioBloqueado(ErrorAutenticacion):
    """Demasiados intentos fallidos: el usuario está bloqueado temporalmente."""

    def __init__(self, minutos_restantes: int):
        self.minutos_restantes = minutos_restantes
        unidad = "minuto" if minutos_restantes == 1 else "minutos"
        super().__init__(
            "Usuario bloqueado por intentos fallidos. "
            f"Intente de nuevo en {minutos_restantes} {unidad}."
        )
