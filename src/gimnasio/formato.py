"""Formatos de presentación para Colombia: fechas dd/mm/aaaa y pesos sin decimales."""

from __future__ import annotations

from datetime import date, datetime

from gimnasio.config import FORMATO_FECHA, FORMATO_FECHA_HORA, ZONA_HORARIA


def fecha(valor: date) -> str:
    return valor.strftime(FORMATO_FECHA)


def fecha_hora_local(valor_utc: datetime) -> str:
    """Muestra en hora de Bogotá una marca de tiempo guardada en UTC."""
    return valor_utc.astimezone(ZONA_HORARIA).strftime(FORMATO_FECHA_HORA)


def pesos(valor: int) -> str:
    """120000 -> '$ 120.000'."""
    signo = "-" if valor < 0 else ""
    return f"{signo}$ {abs(int(valor)):,}".replace(",", ".")


def leer_fecha(texto: str) -> date | None:
    """'05/03/1990' -> date(1990, 3, 5). Vacío -> None. Lanza ValueError si no es válida."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, FORMATO_FECHA).date()
    except ValueError:
        raise ValueError(f"La fecha «{texto}» no es válida. Use el formato dd/mm/aaaa.") from None
