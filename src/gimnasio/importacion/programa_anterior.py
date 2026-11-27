"""Lee la carpeta DB3 del programa anterior y la convierte a datos del sistema nuevo.

Aquí no se toca la base de datos: solo se leen los .DBF, se limpian los valores y se
anota cada problema encontrado. El servicio de importación decide qué se guarda.

Tablas que se usan (las demás se ignoran):
- ENCLIE.DBF  clientes. IDCLIE es el código; CLIENTE viene como «APELLIDOS*NOMBRES».
              SEX: H = hombre, M = mujer. ACT: T = activo. FCHAINI/FCHAFIN: último periodo.
- ENPAGO.DBF  pagos del año. Los valores no son reales (casi todos $1.000): solo se usa
              la fecha de fin de las mensualidades para no perder una vigencia más larga.
- ENASIS.DBF  asistencias. Solo fecha y franja (M mañana, T tarde, N noche).
- ENCASI.DBF  casilleros. Zona según la distribución del gimnasio (1 al 411);
              fuera de ese rango, SEX vacío = mixto; IDCLIE + FCHAINI/FCHAFIN = ocupado.
- ENHUES.DBF  invitados. IDHUES es el documento; VISITAS es un contador.

Los datos de salud (enfermedades, fuma, etc.) y las medidas no se importan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from gimnasio.importacion.dbf import ErrorDBF, TablaDBF, buscar_archivo, leer_dbf
from gimnasio.servicios.zonas_casilleros import TOTAL_CASILLEROS_GIMNASIO, zona_del_gimnasio

TABLA_CLIENTES = "ENCLIE.DBF"
TABLA_PAGOS = "ENPAGO.DBF"
TABLA_ASISTENCIAS = "ENASIS.DBF"
TABLA_CASILLEROS = "ENCASI.DBF"
TABLA_INVITADOS = "ENHUES.DBF"

CAMPOS_OBLIGATORIOS = {
    TABLA_CLIENTES: {"IDCLIE", "CLIENTE", "CC", "SEX", "ACT", "FCHAINI", "FCHAFIN"},
    TABLA_PAGOS: {"IDCLIE", "SERV", "FCHAFIN"},
    TABLA_ASISTENCIAS: {"IDCLIE", "FCHASIS", "HORA"},
    TABLA_CASILLEROS: {"NUMCAS", "SEX", "IDCLIE", "FCHAINI", "FCHAFIN"},
    TABLA_INVITADOS: {"IDHUES", "HUESPED", "VISITAS", "FCHA1AVIS", "FCHAULVIS"},
}

# Hora aproximada (Bogotá) de cada franja de asistencia del programa anterior.
HORA_FRANJA = {"M": 7, "T": 15, "N": 19}
DIAS_PERIODO = 30  # para calcular un inicio cuando falta o está mal
MAXIMO_DIAS_FUTURO = 400  # una fecha de fin más lejana se toma como error de digitación
_ZONAS = {"H": "hombres", "M": "mujeres", "": "mixto"}
_SEXOS = {"H": "M", "M": "F"}


@dataclass
class Problema:
    tabla: str
    fila: int  # número de registro en el archivo (desde 1); 0 = toda la tabla
    referencia: str  # código del cliente, número de casillero o documento
    descripcion: str
    accion: str  # qué se hizo


@dataclass
class ClienteAntiguo:
    fila: int
    codigo: str  # 6 dígitos
    tipo_documento: str
    documento: str
    nombres: str
    apellidos: str
    sexo: str
    fecha_nacimiento: date | None
    direccion: str
    telefono: str
    emergencia_nombre: str
    emergencia_telefono: str
    activo: bool
    fecha_inicio: date | None
    fecha_fin: date | None  # None = sin membresía


@dataclass
class AsistenciaAntigua:
    fila: int
    codigo: str
    fecha: date
    hora: int  # hora local aproximada


@dataclass
class CasilleroAntiguo:
    fila: int
    numero: str
    zona: str
    codigo_cliente: str | None
    fecha_inicio: date | None
    fecha_fin: date | None


@dataclass
class InvitadoAntiguo:
    fila: int
    documento: str
    nombre: str
    visitas: int
    primera: date | None
    ultima: date | None


@dataclass
class DatosAntiguos:
    carpeta: Path
    clientes: list[ClienteAntiguo] = field(default_factory=list)
    asistencias: list[AsistenciaAntigua] = field(default_factory=list)
    casilleros: list[CasilleroAntiguo] = field(default_factory=list)
    invitados: list[InvitadoAntiguo] = field(default_factory=list)
    problemas: list[Problema] = field(default_factory=list)
    leidos: dict[str, int] = field(default_factory=dict)  # registros leídos por tabla

    def problema(self, tabla: str, fila: int, referencia: str, descripcion: str,
                 accion: str) -> None:
        self.problemas.append(Problema(tabla, fila, referencia, descripcion, accion))


class ErrorCarpeta(Exception):
    """La carpeta no tiene los datos del programa anterior."""


# --- limpieza de valores --------------------------------------------------------
def fecha_dbf(texto: str) -> date | None:
    """'20261126' -> date. Vacío o inválido -> None."""
    texto = (texto or "").strip()
    if not re.fullmatch(r"\d{8}", texto):
        return None
    try:
        return date(int(texto[:4]), int(texto[4:6]), int(texto[6:]))
    except ValueError:
        return None


def entero(texto: str) -> int | None:
    texto = (texto or "").strip()
    try:
        return int(float(texto)) if texto else None
    except ValueError:
        return None


def nombre_propio(texto: str) -> str:
    """'MARIA  DEL CARMEN' -> 'Maria Del Carmen'."""
    return " ".join(p.capitalize() for p in (texto or "").split())


def separar_nombre(texto: str) -> tuple[str, str, bool]:
    """«APELLIDOS*NOMBRES» -> (nombres, apellidos, separado_bien)."""
    texto = " ".join((texto or "").replace("*", " * ").split())
    if "*" in texto:
        apellidos, _, nombres = texto.partition("*")
        apellidos, nombres = apellidos.replace("*", " ").strip(), nombres.replace("*", " ").strip()
        if len(nombres) >= 2 and len(apellidos) >= 2:
            return nombre_propio(nombres), nombre_propio(apellidos), True
        texto = f"{apellidos} {nombres}".strip()
    palabras = texto.split()
    if len(palabras) >= 2:  # sin separador: se asume «apellido(s) nombre»
        return nombre_propio(palabras[-1]), nombre_propio(" ".join(palabras[:-1])), False
    if palabras and len(palabras[0]) >= 2:
        return nombre_propio(palabras[0]), "Sin Apellido", False
    return "Sin Nombre", "Sin Apellido", False


def limpiar_documento(texto: str) -> str | None:
    """Deja solo los dígitos de la cédula. None si no queda una cédula posible."""
    digitos = re.sub(r"\D", "", texto or "")
    return digitos if 5 <= len(digitos) <= 11 else None


def limpiar_telefono(texto: str) -> str | None:
    digitos = re.sub(r"\D", "", texto or "")
    return digitos if 7 <= len(digitos) <= 15 else None


# --- lectura ----------------------------------------------------------------------
def _abrir(datos: DatosAntiguos, nombre: str, obligatoria: bool = False) -> TablaDBF | None:
    ruta = buscar_archivo(datos.carpeta, nombre)
    if ruta is None:
        if obligatoria:
            raise ErrorCarpeta(
                f"No se encontró {nombre} en la carpeta elegida. Elija la carpeta DB3 "
                "del programa anterior."
            )
        datos.problema(nombre, 0, "", "No se encontró el archivo.", "No se importa esta tabla.")
        return None
    try:
        tabla = leer_dbf(ruta)
    except (ErrorDBF, OSError) as e:
        if obligatoria:
            raise ErrorCarpeta(f"No se pudo leer {nombre}: {e}") from e
        datos.problema(nombre, 0, "", f"No se pudo leer: {e}", "No se importa esta tabla.")
        return None
    faltan = CAMPOS_OBLIGATORIOS[nombre] - tabla.nombres_campos
    if faltan:
        mensaje = f"Al archivo le faltan columnas: {', '.join(sorted(faltan))}."
        if obligatoria:
            raise ErrorCarpeta(f"{nombre}: {mensaje}")
        datos.problema(nombre, 0, "", mensaje, "No se importa esta tabla.")
        return None
    datos.leidos[nombre] = len(tabla.registros)
    return tabla


def _codigo(texto: str) -> str | None:
    n = entero(texto)
    return f"{n:06d}" if n and 0 < n <= 999_999 else None


def leer_carpeta(carpeta: Path | str, hoy: date) -> DatosAntiguos:
    """Lee la carpeta DB3 completa. Lanza ErrorCarpeta si no están los clientes."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise ErrorCarpeta("La carpeta elegida no existe.")
    datos = DatosAntiguos(carpeta=carpeta)
    limite_fin = hoy + timedelta(days=MAXIMO_DIAS_FUTURO)
    tabla = _abrir(datos, TABLA_CLIENTES, obligatoria=True)
    fines_pagos = _fines_de_pagos(datos, limite_fin)
    _leer_clientes(datos, tabla, hoy, limite_fin, fines_pagos)
    codigos = {c.codigo for c in datos.clientes}
    _leer_asistencias(datos, hoy, codigos)
    _leer_casilleros(datos, limite_fin, codigos)
    _leer_invitados(datos, hoy)
    return datos


def _fines_de_pagos(datos: DatosAntiguos, limite_fin: date) -> dict[str, date]:
    """Fecha de fin más lejana de las mensualidades de cada cliente en ENPAGO."""
    tabla = _abrir(datos, TABLA_PAGOS)
    fines: dict[str, date] = {}
    if tabla is None:
        return fines
    for r in tabla.registros:
        codigo, fin = _codigo(r["IDCLIE"]), fecha_dbf(r["FCHAFIN"])
        if not codigo or not fin or fin > limite_fin:
            continue
        if r["SERV"].strip().upper() not in ("MENSUALIDAD", "QUINCENA", "SEMANA"):
            continue
        if fin > fines.get(codigo, date.min):
            fines[codigo] = fin
    return fines


def _leer_clientes(datos: DatosAntiguos, tabla: TablaDBF, hoy: date, limite_fin: date,
                   fines_pagos: dict[str, date]) -> None:
    t = TABLA_CLIENTES
    vistos: dict[str, int] = {}
    documentos: dict[str, ClienteAntiguo] = {}
    for fila, r in enumerate(tabla.registros, start=1):
        codigo = _codigo(r["IDCLIE"])
        if codigo is None:
            datos.problema(t, fila, r["IDCLIE"], "El cliente no tiene código.", "No se importa.")
            continue
        if codigo in vistos:
            datos.problema(t, fila, codigo,
                           f"Código repetido (ya estaba en el registro {vistos[codigo]}).",
                           "Se importa solo el primero; revise este cliente a mano.")
            continue
        vistos[codigo] = fila
        nombres, apellidos, separado = separar_nombre(r["CLIENTE"])
        if not separado:
            datos.problema(t, fila, codigo, f"Nombre sin separar apellidos y nombres: «{r['CLIENTE']}».",
                           f"Se guardó como nombres «{nombres}» y apellidos «{apellidos}».")
        sexo_antiguo = r["SEX"].strip().upper()
        sexo = _SEXOS.get(sexo_antiguo, "O")
        if sexo_antiguo not in _SEXOS:
            datos.problema(t, fila, codigo, f"Sexo desconocido «{r['SEX']}».",
                           "Se guardó como «Otro»; corríjalo en la ficha.")
        nacimiento = fecha_dbf(r.get("FCHANAC", ""))
        if nacimiento and not (hoy.year - 100 <= nacimiento.year and nacimiento <= hoy):
            nacimiento = None  # fechas de relleno o mal digitadas: no se reporta una por una
        activo = r["ACT"].strip().upper() in ("T", "Y")
        fin = fecha_dbf(r["FCHAFIN"])
        if r["FCHAFIN"] and (fin is None or fin > limite_fin or fin.year < 1990):
            datos.problema(t, fila, codigo, f"Fecha de vencimiento inválida «{r['FCHAFIN']}».",
                           "Se importa sin esa fecha.")
            fin = None
        fin_pago = fines_pagos.get(codigo)
        if fin_pago and (fin is None or fin_pago > fin):
            fin = fin_pago
        inicio = fecha_dbf(r["FCHAINI"])
        if fin and (inicio is None or inicio > fin or (fin - inicio).days > 400):
            inicio = fin - timedelta(days=DIAS_PERIODO - 1)
        acudiente = " ".join(r.get("ACUDIENTE", "").split())
        tel_acudiente = limpiar_telefono(r.get("TELACU", "")) or ""
        cliente = ClienteAntiguo(
            fila=fila, codigo=codigo, tipo_documento="CC", documento="",
            nombres=nombres, apellidos=apellidos, sexo=sexo, fecha_nacimiento=nacimiento,
            direccion=" ".join(r.get("DIRRES", "").split()),
            telefono=limpiar_telefono(r.get("TELRES", "")) or "",
            emergencia_nombre=nombre_propio(acudiente) if tel_acudiente else "",
            emergencia_telefono=tel_acudiente if acudiente else "",
            activo=activo, fecha_inicio=inicio if fin else None, fecha_fin=fin,
        )
        documento = limpiar_documento(r["CC"])
        if documento is None:
            if r["CC"].strip():
                datos.problema(t, fila, codigo, f"Documento inválido «{r['CC']}».",
                               "Queda «Sin documento»; escríbalo en la ficha.")
            else:
                datos.problema(t, fila, codigo, "No tiene documento.",
                               "Queda «Sin documento»; escríbalo en la ficha.")
        elif documento in documentos:
            otro = documentos[documento]
            # El documento se lo queda el más reciente (activo primero, luego vencimiento).
            if _prioridad(cliente) > _prioridad(otro):
                otro.documento = ""
                cliente.documento = documento
                documentos[documento] = cliente
                perdedor, ganador = otro, cliente
            else:
                perdedor, ganador = cliente, otro
            datos.problema(t, perdedor.fila, perdedor.codigo,
                           f"Documento {documento} repetido con el código {ganador.codigo}.",
                           f"El documento queda en el código {ganador.codigo}; este queda "
                           "«Sin documento». Si es la misma persona, inactívelo.")
        else:
            cliente.documento = documento
            documentos[documento] = cliente
        datos.clientes.append(cliente)
    for cliente in datos.clientes:
        if not cliente.documento:
            cliente.tipo_documento, cliente.documento = "SD", f"SD{cliente.codigo}"


def _prioridad(c: ClienteAntiguo) -> tuple:
    return (c.activo, c.fecha_fin or date.min, c.codigo)


def _leer_asistencias(datos: DatosAntiguos, hoy: date, codigos: set[str]) -> None:
    t = TABLA_ASISTENCIAS
    tabla = _abrir(datos, t)
    if tabla is None:
        return
    for fila, r in enumerate(tabla.registros, start=1):
        codigo, dia = _codigo(r["IDCLIE"]), fecha_dbf(r["FCHASIS"])
        if codigo not in codigos:
            datos.problema(t, fila, r["IDCLIE"], "La asistencia es de un cliente que no existe.",
                           "No se importa.")
            continue
        if dia is None or dia > hoy or dia.year < 1990:
            datos.problema(t, fila, codigo, f"Fecha de asistencia inválida «{r['FCHASIS']}».",
                           "No se importa.")
            continue
        hora = HORA_FRANJA.get(r["HORA"].strip().upper(), 12)
        datos.asistencias.append(AsistenciaAntigua(fila, codigo, dia, hora))


def _leer_casilleros(datos: DatosAntiguos, limite_fin: date, codigos: set[str]) -> None:
    t = TABLA_CASILLEROS
    tabla = _abrir(datos, t)
    if tabla is None:
        return
    numeros: set[str] = set()
    con_casillero: dict[str, str] = {}
    for fila, r in enumerate(tabla.registros, start=1):
        n = entero(r["NUMCAS"])
        if not n or n <= 0:
            datos.problema(t, fila, r["NUMCAS"], "Casillero sin número.", "No se importa.")
            continue
        numero = f"{n:03d}"
        if numero in numeros:
            datos.problema(t, fila, numero, "Número de casillero repetido.", "Se usa el primero.")
            continue
        numeros.add(numero)
        # La zona sale de la distribución del gimnasio; el dato SEX del programa anterior
        # solo se usa para casilleros por fuera del 1 al 411.
        zona = (zona_del_gimnasio(n) if n <= TOTAL_CASILLEROS_GIMNASIO
                else _ZONAS.get(r["SEX"].strip().upper(), "mixto"))
        casillero = CasilleroAntiguo(fila, numero, zona, None, None, None)
        datos.casilleros.append(casillero)
        codigo = _codigo(r["IDCLIE"])
        if not codigo:
            continue
        if codigo not in codigos:
            datos.problema(t, fila, numero, f"Asignado al cliente {codigo}, que no existe.",
                           "Se importa libre.")
            continue
        if codigo in con_casillero:
            datos.problema(t, fila, numero,
                           f"El cliente {codigo} ya tiene el casillero {con_casillero[codigo]}.",
                           "Se importa libre (un cliente, un casillero).")
            continue
        fin = fecha_dbf(r["FCHAFIN"])
        if fin is None or fin > limite_fin or fin.year < 1990:
            datos.problema(t, fila, numero, f"Fecha de vencimiento inválida «{r['FCHAFIN']}».",
                           "Se asigna sin fecha: renuévelo o libérelo.")
            fin = None
        inicio = fecha_dbf(r["FCHAINI"])
        if inicio is None or (fin and inicio > fin):
            inicio = fin - timedelta(days=DIAS_PERIODO - 1) if fin else None
        casillero.codigo_cliente, casillero.fecha_inicio, casillero.fecha_fin = codigo, inicio, fin
        con_casillero[codigo] = numero


def _leer_invitados(datos: DatosAntiguos, hoy: date) -> None:
    t = TABLA_INVITADOS
    tabla = _abrir(datos, t)
    if tabla is None:
        return
    vistos: set[str] = set()
    for fila, r in enumerate(tabla.registros, start=1):
        documento = re.sub(r"[^0-9A-Za-z]", "", r["IDHUES"]).upper()
        if not re.fullmatch(r"[A-Z0-9]{3,20}", documento):
            datos.problema(t, fila, r["IDHUES"], "Invitado sin documento válido.", "No se importa.")
            continue
        if documento in vistos:
            datos.problema(t, fila, documento, "Invitado repetido.", "Se usa el primero.")
            continue
        vistos.add(documento)
        nombres, apellidos, _ = separar_nombre(r["HUESPED"])
        nombre = f"{nombres} {apellidos}".replace("Sin Nombre", "").replace("Sin Apellido", "")
        nombre = " ".join(nombre.split()) or "Sin Nombre"

        def valida(d: date | None) -> date | None:
            return d if d and 1990 <= d.year and d <= hoy else None

        primera, ultima = valida(fecha_dbf(r["FCHA1AVIS"])), valida(fecha_dbf(r["FCHAULVIS"]))
        if (r["FCHA1AVIS"] and primera is None) or (r["FCHAULVIS"] and ultima is None):
            datos.problema(t, fila, documento, "Fecha de visita inválida.",
                           "Esa visita queda contada sin fecha.")
        if primera and ultima and primera > ultima:
            primera, ultima = ultima, primera
        visitas = max(entero(r["VISITAS"]) or 0, sum(1 for d in {primera, ultima} if d))
        datos.invitados.append(InvitadoAntiguo(fila, documento, nombre, visitas, primera, ultima))
