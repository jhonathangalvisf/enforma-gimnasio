"""Normalización de texto para búsquedas: minúsculas y sin tildes ("José" = "jose")."""

from __future__ import annotations

import unicodedata


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c)).lower()
