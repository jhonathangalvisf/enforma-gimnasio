"""Convierte docs/MANUAL_INSTALACION.md en dist/Manual-Enforma.pdf (va en el instalador).

Usa Qt (ya es dependencia del programa) para leer el Markdown y escribir el PDF.
Uso:  python empaquetado/manual_pdf.py [--salida ruta.pdf]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "docs" / "MANUAL_INSTALACION.md"
SALIDA = RAIZ / "dist" / "Manual-Enforma.pdf"

ESTILO = """
body { font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; font-size: 10pt; color: #1f2933; }
h1 { color: #225ca5; font-size: 20pt; }
h2 { color: #225ca5; font-size: 14pt; margin-top: 14px; }
h3 { color: #2a3f5f; font-size: 11pt; }
table { border-collapse: collapse; }
td, th { border: 1px solid #c8d3e0; padding: 4px; }
th { background: #e8eef7; }
code { font-family: Consolas, 'DejaVu Sans Mono', monospace; }
"""


def generar(entrada: Path = ENTRADA, salida: Path = SALIDA) -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    documento = QTextDocument()
    documento.setDefaultStyleSheet(ESTILO)
    documento.setMarkdown(entrada.read_text(encoding="utf-8"))
    # setMarkdown no aplica la hoja de estilos: se pasa por HTML para que sí la use.
    html = documento.toHtml()
    salida.parent.mkdir(parents=True, exist_ok=True)
    escritor = QPdfWriter(str(salida))
    escritor.setTitle("Manual de instalación y respaldo de Enforma")
    escritor.setCreator("Enforma")
    escritor.setResolution(144)
    escritor.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.Letter),
                                       QPageLayout.Orientation.Portrait,
                                       QMarginsF(18, 18, 18, 18), QPageLayout.Unit.Millimeter))
    documento = QTextDocument()
    documento.documentLayout().setPaintDevice(escritor)  # tamaños de letra según el PDF
    documento.setDefaultStyleSheet(ESTILO)
    documento.setHtml(html)
    rect = escritor.pageLayout().paintRectPixels(escritor.resolution())
    documento.setPageSize(QSizeF(rect.width(), rect.height()))
    documento.print_(escritor)
    del app
    return salida


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analizador.add_argument("--salida", type=Path, default=SALIDA)
    opciones = analizador.parse_args()
    ruta = generar(salida=opciones.salida)
    print(f"Manual: {ruta} ({ruta.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
