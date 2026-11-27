"""Recibo de pago en PDF (RF-P4): ancho de media carta y 10 cm de alto, con logo y consecutivo.

No es factura electrónica (fuera de alcance): es un recibo de caja interno.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from reportlab.lib import colors
from reportlab.lib.units import inch, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from gimnasio.formato import fecha, fecha_hora_local, pesos

if TYPE_CHECKING:
    from gimnasio.servicios.pagos import DatosRecibo

ANCHO = 5.5 * inch          # ancho de media carta
ALTO = 100 * mm             # 10 cm de alto
MARGEN = 7 * mm
COLUMNA = 30 * mm           # donde empiezan los valores
PASO = 4.3 * mm             # alto de cada renglón


def crear_recibo_pdf(datos: DatosRecibo, destino: Path) -> Path:
    """Recibo de 10 cm de alto. Si un recibo trae muchos conceptos y no cabe, la hoja
    crece lo justo (nunca se corta información)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    medida = canvas.Canvas(str(destino), pagesize=(ANCHO, 1000 * mm))
    usado = _dibujar(medida, datos, 1000 * mm)
    alto = max(ALTO, usado + 9 * mm)  # 9 mm para el pie de página
    c = canvas.Canvas(str(destino), pagesize=(ANCHO, alto))
    c.setTitle(f"Recibo {datos.recibo}")
    c.setAuthor(datos.gimnasio_nombre)
    _dibujar(c, datos, alto)
    c.showPage()
    c.save()
    return destino


def _dibujar(c: canvas.Canvas, datos: DatosRecibo, alto: float) -> float:
    """Dibuja el recibo y devuelve cuánto alto ocupó el contenido (sin el pie)."""
    ancho = ANCHO
    y = alto - MARGEN
    # Encabezado: solo el logo (sin repetir el nombre). Sin logo, el nombre en texto.
    x_texto = MARGEN
    alto_logo = 13 * mm
    con_logo = False
    if datos.logo:
        try:
            imagen = ImageReader(str(datos.logo))
            iw, ih = imagen.getSize()
            ancho_logo = min(40 * mm, alto_logo * iw / ih)
            c.drawImage(imagen, MARGEN, y - alto_logo, ancho_logo, alto_logo,
                        preserveAspectRatio=True, mask="auto")
            x_texto = MARGEN + ancho_logo + 5 * mm
            con_logo = True
        except Exception:  # un logo dañado no debe impedir el recibo
            pass
    linea = y - 4 * mm
    if not con_logo:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(x_texto, linea, datos.gimnasio_nombre)
        linea -= 5 * mm
    c.setFont("Helvetica", 8)
    for texto in (
        f"NIT {datos.gimnasio_nit}" if datos.gimnasio_nit else "",
        datos.gimnasio_direccion,
        f"Tel. {datos.gimnasio_telefono}" if datos.gimnasio_telefono else "",
    ):
        if texto:
            c.drawString(x_texto, linea, texto)
            linea -= 3.6 * mm
    y = min(linea + 3.6 * mm, y - (alto_logo if con_logo else 6 * mm)) - 3 * mm

    # Título y número.
    c.setFillColor(colors.HexColor("#1f4e79"))
    c.rect(MARGEN, y - 7 * mm, ancho - 2 * MARGEN, 7 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(MARGEN + 3 * mm, y - 4.8 * mm, "RECIBO DE CAJA")
    c.drawRightString(ancho - MARGEN - 3 * mm, y - 4.8 * mm, f"N.º {datos.recibo}")
    c.setFillColor(colors.black)
    y -= 11 * mm

    def fila(etiqueta: str, valor: str, negrita: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(MARGEN, y, etiqueta)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold" if negrita else "Helvetica", 8.8)
        partes = _partir(valor, 58)
        for i, parte in enumerate(partes):
            c.drawString(MARGEN + COLUMNA, y - i * 3.8 * mm, parte)
        y -= (len(partes) - 1) * 3.8 * mm + PASO

    fila("Fecha de pago", fecha_hora_local(datos.fecha_hora))
    fila("Cliente", datos.cliente_nombre, negrita=True)
    fila("Código", f"{datos.cliente_codigo}   ·   {datos.cliente_documento}", negrita=False)
    if datos.lineas:
        # Recibo con varios conceptos (mensualidad + casillero): uno por renglón.
        for i, item in enumerate(datos.lineas):
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#555555"))
            c.drawString(MARGEN, y, "Conceptos" if i == 0 else "")
            c.setFillColor(colors.HexColor("#b42318") if item.anulado else colors.black)
            c.setFont("Helvetica", 8.8)
            texto = item.detalle + ("  (ANULADO)" if item.anulado else "")
            partes = _partir(texto, 46)
            for k, parte in enumerate(partes):
                c.drawString(MARGEN + COLUMNA, y - k * 3.8 * mm, parte)
            c.setFont("Helvetica-Bold", 8.8)
            c.drawRightString(ancho - MARGEN, y, pesos(item.monto))
            c.setFillColor(colors.black)
            y -= (len(partes) - 1) * 3.8 * mm + PASO
    else:
        fila("Concepto", datos.detalle)
    fila("Método de pago", datos.metodo + (f" · Ref. {datos.referencia}" if datos.referencia else ""))
    if datos.vigencia_hasta is not None:
        # Recuadro destacado con la nueva vigencia (hasta qué día puede entrar).
        c.setFillColor(colors.HexColor("#e8f3ec"))
        c.setStrokeColor(colors.HexColor("#1e7b45"))
        c.roundRect(MARGEN, y - 5.5 * mm, ancho - 2 * MARGEN, 8.5 * mm, 1.5 * mm,
                    stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#1e7b45"))
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGEN + 3 * mm, y - 2.6 * mm, "NUEVA VIGENCIA")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(MARGEN + COLUMNA, y - 2.8 * mm,
                     f"Del {fecha(datos.vigencia_desde)} al {fecha(datos.vigencia_hasta)}")
        c.setFillColor(colors.black)
        y -= 10.5 * mm
    else:
        # Pago que no es mensualidad: se aclara hasta cuándo está al día el cliente.
        fila("Vigencia actual",
             f"Hasta el {fecha(datos.vigente_hasta)} (este pago no la cambia)"
             if datos.vigente_hasta else "Sin membresía (este pago no la cambia)")
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.line(MARGEN, y + 2.6 * mm, ancho - MARGEN, y + 2.6 * mm)
    y -= 2 * mm
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(MARGEN, y, "TOTAL PAGADO" if datos.lineas else "VALOR PAGADO")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(MARGEN + COLUMNA, y - 0.6 * mm, pesos(datos.monto))
    # A la derecha del valor: precio y saldo de la membresía, y quién atendió.
    c.setFont("Helvetica", 8)
    derecha = []
    if datos.precio_membresia is not None:
        derecha.append(f"Valor membresía {pesos(datos.precio_membresia)}")
    if datos.saldo_despues is not None:
        derecha.append("Saldo pendiente " + (pesos(datos.saldo_despues)
                                             if datos.saldo_despues else "$ 0 (pagado)"))
    for i, texto in enumerate(derecha):
        c.setFont("Helvetica-Bold" if texto.startswith("Saldo") and datos.saldo_despues
                  else "Helvetica", 8)
        c.drawRightString(ancho - MARGEN, y - i * 3.8 * mm, texto)
    y -= max(7 * mm, len(derecha) * 3.8 * mm + 2 * mm)
    fila("Atendido por", datos.usuario)

    if datos.anulado:
        c.saveState()
        c.setFillColor(colors.HexColor("#b42318"))
        c.setFont("Helvetica-Bold", 44)
        c.translate(ancho / 2, alto / 2)
        c.rotate(20)
        c.setFillAlpha(0.25)
        c.drawCentredString(0, -15, "ANULADO")
        c.restoreState()
        c.setFillColor(colors.HexColor("#b42318"))
        c.setFont("Helvetica-Bold", 8)
        for parte in _partir(f"ANULADO: {datos.motivo_anulacion}", 80):
            c.drawString(MARGEN, y, parte)
            y -= 3.8 * mm
        c.setFillColor(colors.black)

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawCentredString(ancho / 2, 4.5 * mm,
                        "Gracias por su pago. Este documento no es una factura electrónica.")
    c.setFillColor(colors.black)
    return alto - y


def _partir(texto: str, ancho: int) -> list[str]:
    """Divide un texto largo en líneas de máximo `ancho` caracteres (por palabras)."""
    lineas, actual = [], ""
    for palabra in (texto or "").split():
        if actual and len(actual) + 1 + len(palabra) > ancho:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return lineas or [""]
