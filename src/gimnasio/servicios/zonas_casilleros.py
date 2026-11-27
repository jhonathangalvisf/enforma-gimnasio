"""Zonas de los casilleros del gimnasio Enforma (sin dependencias, la usa también el
importador del programa anterior)."""

from __future__ import annotations

# Distribución del gimnasio Enforma (casilleros del 1 al 411, rangos inclusive).
# Los que no estén en ningún rango son mixtos. Es la zona con la que se crean los
# casilleros en una instalación nueva, al importar el programa anterior y la que la
# migración 0010 aplica a las bases existentes; después el administrador puede
# cambiar la zona de un casillero a mano.
TOTAL_CASILLEROS_GIMNASIO = 411
RANGOS_ZONAS_GIMNASIO: dict[str, tuple[tuple[int, int], ...]] = {
    "mujeres": ((1, 49), (276, 294)),
    "hombres": ((50, 110), (251, 275), (307, 328)),
}


def zona_del_gimnasio(numero: int) -> str:
    """Zona que le corresponde a un casillero según la distribución del gimnasio."""
    for zona, rangos in RANGOS_ZONAS_GIMNASIO.items():
        if any(desde <= numero <= hasta for desde, hasta in rangos):
            return zona
    return "mixto"
