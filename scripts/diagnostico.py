"""Diagnóstico de la instalación desde Python (igual que `Enforma.exe --diagnostico`).

Revisa archivos del programa, zona horaria, carpeta de datos, base, la protección
DPAPI de Windows (prueba real), la contraseña de copias guardada y la última copia.

Uso:
    python scripts/diagnostico.py                 # muestra el informe
    python scripts/diagnostico.py --reporte informe.txt
Devuelve 0 si no hay fallas y 1 si las hay.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from gimnasio import diagnostico  # noqa: E402


def main(argumentos: list[str] | None = None) -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--reporte", type=Path, help="guardar el informe en este archivo")
    opciones = analizador.parse_args(argumentos)
    codigo = diagnostico.ejecutar(opciones.reporte)
    if opciones.reporte:
        print(opciones.reporte.read_text(encoding="utf-8"))
    return codigo


if __name__ == "__main__":
    sys.exit(main())
