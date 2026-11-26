"""Recibo de pago en PDF (RF-P4), tamaño media carta, con logo y consecutivo.

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

MEDIA_CARTA = (5.5 * inch, 8.5 * inch)
MARGEN = 14 * mm


def crear_recibo_pdf(datos: DatosRecibo, destino: Path) -> Path:
    ancho, alto = MEDIA_CARTA
    destino.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(destino), pagesize=MEDIA_CARTA)
    c.setTitle(f"Recibo {datos.recibo}")
    c.setAuthor(datos.gimnasio_nombre)

    y = alto - MARGEN
    # Encabezado: logo a la izquierda, datos del gimnasio a la derecha.
    x_texto = MARGEN
    if datos.logo:
        try:
            imagen = ImageReader(str(datos.logo))
            iw, ih = imagen.getSize()
            alto_logo = 18 * mm
            ancho_logo = min(35 * mm, alto_logo * iw / ih)
            c.drawImage(imagen, MARGEN, y - alto_logo, ancho_logo, alto_logo,
                        preserveAspectRatio=True, mask="auto")
            x_texto = MARGEN + ancho_logo + 5 * mm
        except Exception:  # un logo dañado no debe impedir el recibo
            pass
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x_texto, y - 5 * mm, datos.gimnasio_nombre)
    c.setFont("Helvetica", 8.5)
    linea = y - 10 * mm
    for texto in (
        f"NIT {datos.gimnasio_nit}" if datos.gimnasio_nit else "",
        datos.gimnasio_direccion,
        f"Tel. {datos.gimnasio_telefono}" if datos.gimnasio_telefono else "",
    ):
        if texto:
            c.drawString(x_texto, linea, texto)
            linea -= 4 * mm
    y = min(linea, y - 20 * mm) - 4 * mm

    # Título y número.
    c.setFillColor(colors.HexColor("#1f4e79"))
    c.rect(MARGEN, y - 10 * mm, ancho - 2 * MARGEN, 10 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(MARGEN + 3 * mm, y - 6.8 * mm, "RECIBO DE CAJA")
    c.drawRightString(ancho - MARGEN - 3 * mm, y - 6.8 * mm, f"N.º {datos.recibo}")
    c.setFillColor(colors.black)
    y -= 16 * mm

    def fila(etiqueta: str, valor: str, negrita: bool = False) -> None:
        nonlocal y
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(MARGEN, y, etiqueta)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold" if negrita else "Helvetica", 9.5)
        for i, parte in enumerate(_partir(valor, 52)):
            c.drawString(MARGEN + 32 * mm, y - i * 4.2 * mm, parte)
        y -= max(1, len(_partir(valor, 52))) * 4.2 * mm + 2.2 * mm

    fila("Fecha de pago", fecha_hora_local(datos.fecha_hora))
    fila("Cliente", datos.cliente_nombre, negrita=True)
    fila("Código", datos.cliente_codigo, negrita=True)
    fila("Documento", datos.cliente_documento)
    fila("Concepto", datos.detalle)
    if datos.vigencia_hasta is not None:
        # Recuadro destacado con la nueva vigencia (hasta qué día puede entrar).
        c.setFillColor(colors.HexColor("#e8f3ec"))
        c.setStrokeColor(colors.HexColor("#1e7b45"))
        c.roundRect(MARGEN, y - 9 * mm, ancho - 2 * MARGEN, 12 * mm, 2 * mm, stroke=1, fill=1)
        c.setFillColor(colors.HexColor("#1e7b45"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGEN + 3 * mm, y - 1 * mm, "NUEVA VIGENCIA")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(MARGEN + 3 * mm, y - 6.5 * mm,
                     f"Del {fecha(datos.vigencia_desde)} al {fecha(datos.vigencia_hasta)}")
        c.setFont("Helvetica", 8)
        c.drawRightString(ancho - MARGEN - 3 * mm, y - 6.5 * mm, "puede entrar hasta ese día inclusive")
        c.setFillColor(colors.black)
        y -= 15 * mm
    fila("Método de pago", datos.metodo + (f" · Ref. {datos.referencia}" if datos.referencia else ""))
    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.line(MARGEN, y + 3 * mm, ancho - MARGEN, y + 3 * mm)
    y -= 3 * mm
    if datos.precio_membresia is not None:
        fila("Valor membresía", pesos(datos.precio_membresia))
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#555555"))
    c.drawString(MARGEN, y, "VALOR PAGADO")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGEN + 32 * mm, y - 1 * mm, pesos(datos.monto))
    y -= 9 * mm
    if datos.saldo_despues is not None:
        fila("Saldo pendiente", pesos(datos.saldo_despues) if datos.saldo_despues else "$ 0 (pagado)",
             negrita=bool(datos.saldo_despues))
    y -= 4 * mm
    fila("Atendido por", datos.usuario)

    if datos.anulado:
        c.saveState()
        c.setFillColor(colors.HexColor("#b42318"))
        c.setFont("Helvetica-Bold", 54)
        c.translate(ancho / 2, alto / 2)
        c.rotate(35)
        c.setFillAlpha(0.25)
        c.drawCentredString(0, 0, "ANULADO")
        c.restoreState()
        c.setFillColor(colors.HexColor("#b42318"))
        c.setFont("Helvetica-Bold", 9)
        for i, parte in enumerate(_partir(f"ANULADO: {datos.motivo_anulacion}", 70)):
            c.drawString(MARGEN, 30 * mm - i * 4.2 * mm, parte)
        c.setFillColor(colors.black)

    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawCentredString(ancho / 2, 14 * mm, "Gracias por su pago. Este documento no es una factura electrónica.")
    c.showPage()
    c.save()
    return destino


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
