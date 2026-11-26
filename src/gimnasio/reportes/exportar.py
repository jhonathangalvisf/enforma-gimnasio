"""Exportación genérica de tablas a Excel (openpyxl) y PDF (reportlab).

Las fechas se escriben en formato dd/mm/aaaa y los montos enteros sin decimales.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

from gimnasio.config import FORMATO_FECHA, ZONA_HORARIA

FILAS_POR_TABLA_PDF = 400  # tablas por bloques: reportlab es más rápido así


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.astimezone(ZONA_HORARIA).strftime(f"{FORMATO_FECHA} %H:%M")
    if isinstance(valor, date):
        return valor.strftime(FORMATO_FECHA)
    return str(valor)


def exportar_excel(
    ruta: Path | str, titulo: str, encabezados: Sequence[str], filas: Sequence[Sequence]
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    libro = Workbook(write_only=False)
    hoja = libro.active
    hoja.title = titulo[:31]
    hoja.append(list(encabezados))
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="1F4E79")
    anchos = [len(e) for e in encabezados]
    for fila in filas:
        valores = []
        for i, valor in enumerate(fila):
            if isinstance(valor, datetime):
                valor = valor.astimezone(ZONA_HORARIA).replace(tzinfo=None)
            valores.append(valor)
            anchos[i] = max(anchos[i], min(len(_texto(valor)), 50))
        hoja.append(valores)
    for i, ancho in enumerate(anchos, start=1):
        letra = get_column_letter(i)
        hoja.column_dimensions[letra].width = ancho + 2
        for celda in hoja[letra][1:]:
            if isinstance(celda.value, datetime):
                celda.number_format = "dd/mm/yyyy hh:mm"
            elif isinstance(celda.value, date):
                celda.number_format = "dd/mm/yyyy"
            elif isinstance(celda.value, int):
                celda.number_format = "#,##0"
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = hoja.dimensions
    ruta = Path(ruta)
    libro.save(ruta)
    return ruta


def exportar_pdf(
    ruta: Path | str, titulo: str, subtitulo: str, encabezados: Sequence[str],
    filas: Sequence[Sequence],
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ruta = Path(ruta)
    documento = SimpleDocTemplate(
        str(ruta), pagesize=landscape(A4), title=titulo,
        leftMargin=1.2 * cm, rightMargin=1.2 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm,
    )
    estilos = getSampleStyleSheet()
    contenido = [Paragraph(titulo, estilos["Title"]), Paragraph(subtitulo, estilos["Normal"]),
                 Spacer(1, 0.4 * cm)]
    estilo_tabla = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F8")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CFD6DE")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ])
    textos = [[_texto(v)[:40] for v in fila] for fila in filas]
    if not textos:
        contenido.append(Paragraph("No hay datos con los filtros elegidos.", estilos["Normal"]))
    for inicio in range(0, len(textos), FILAS_POR_TABLA_PDF):
        bloque = [list(encabezados)] + textos[inicio:inicio + FILAS_POR_TABLA_PDF]
        tabla = Table(bloque, repeatRows=1)
        tabla.setStyle(estilo_tabla)
        contenido.append(tabla)

    def pie(lienzo, doc):
        lienzo.saveState()
        lienzo.setFont("Helvetica", 7)
        lienzo.drawRightString(doc.pagesize[0] - 1.2 * cm, 0.7 * cm, f"Página {doc.page}")
        lienzo.restoreState()

    documento.build(contenido, onFirstPage=pie, onLaterPages=pie)
    return ruta
