"""Clientes (sección 3.2): registro, consulta, modificación, activación y búsquedas.

Reglas:
- El código es el identificador único del cliente: 6 dígitos, consecutivo, inmutable.
- Los clientes no se borran nunca: solo se inactivan (solo el administrador).
- La vigencia (vigente / por vencer / vencida / sin membresía) se calcula siempre a
  partir de la última membresía no anulada; no se guarda en ninguna tabla.
- Recepción solo modifica datos de contacto; el administrador modifica todo.
- Cada cambio queda en la auditoría con el campo, el valor anterior y el nuevo.
"""

from __future__ import annotations

import re
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, union
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.modelos import (
    Alerta, Asistencia, Casillero, CasilleroAsignacion, Cliente, Contacto, Membresia, Pago,
    Plan, Usuario, ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.auditoria import inicio_dia_utc
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import saldos_por_membresia
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente
from gimnasio.texto import normalizar

TIPOS_DOCUMENTO = {
    "CC": "Cédula de ciudadanía",
    "TI": "Tarjeta de identidad",
    "CE": "Cédula de extranjería",
    "PAS": "Pasaporte",
    "PPT": "Permiso por protección temporal",
}
SEXOS = {"M": "Masculino", "F": "Femenino", "O": "Otro"}
ESTADOS = {"activo": "Activo", "inactivo": "Inactivo"}

# Campos que Recepción puede cambiar (sección 2: "datos de contacto").
CAMPOS_CONTACTO = frozenset({"direccion", "telefonos", "correos", "emergencias"})
EXTENSIONES_FOTO = {".png", ".jpg", ".jpeg"}
TAMANO_MAXIMO_FOTO = 5 * 1024 * 1024
CODIGO_MAXIMO = 999_999
# Con menos dígitos solo se busca el código exacto (evita listar miles de teléfonos).
MINIMO_DIGITOS_PREFIJO = 3

_PATRON_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PATRON_NUMERICO = re.compile(r"^\+?[\d\s.\-]+$")


class Vigencia(str, Enum):
    VIGENTE = "vigente"
    POR_VENCER = "por_vencer"
    VENCIDA = "vencida"
    SIN_MEMBRESIA = "sin_membresia"


NOMBRES_VIGENCIA = {
    Vigencia.VIGENTE: "Vigente",
    Vigencia.POR_VENCER: "Por vencer",
    Vigencia.VENCIDA: "Vencida",
    Vigencia.SIN_MEMBRESIA: "Sin membresía",
}


def calcular_vigencia(
    fecha_fin: date | None, hoy: date, dias_por_vencer: int
) -> tuple[Vigencia, int | None]:
    """Vigencia y días restantes según la fecha de fin de la última membresía no anulada.

    El cliente puede ingresar hasta el día de `fecha_fin` incluido (RN-03): ese día
    quedan 0 días y sigue "por vencer".
    """
    if fecha_fin is None:
        return Vigencia.SIN_MEMBRESIA, None
    dias = (fecha_fin - hoy).days
    if dias < 0:
        return Vigencia.VENCIDA, dias
    if dias <= dias_por_vencer:
        return Vigencia.POR_VENCER, dias
    return Vigencia.VIGENTE, dias


class ErrorCasilleroAsignado(ErrorValidacion):
    """Se intentó inactivar a un cliente con casillero sin decidir si se libera."""

    def __init__(self, numero: str):
        self.numero = numero
        super().__init__(
            f"El cliente tiene asignado el casillero {numero}. Indique si se libera "
            "al inactivarlo."
        )


# --- datos de entrada y salida ---------------------------------------------------

@dataclass
class ContactoEmergencia:
    nombre: str
    telefono: str


@dataclass
class DatosCliente:
    """Lo que se escribe en el formulario de registro o edición.

    En las listas de teléfonos y correos el primero es el principal.
    """

    tipo_documento: str
    documento: str
    nombres: str
    apellidos: str
    sexo: str
    fecha_nacimiento: date | None = None
    direccion: str = ""
    notas: str = ""
    autoriza_datos: bool = False
    telefonos: list[str] = field(default_factory=list)
    correos: list[str] = field(default_factory=list)
    emergencias: list[ContactoEmergencia] = field(default_factory=list)


@dataclass(frozen=True)
class FiltrosClientes:
    texto: str = ""
    estado: str | None = None  # "activo" / "inactivo"
    vigencia: Vigencia | None = None
    sexo: str | None = None
    plan_id: int | None = None
    registro_desde: date | None = None  # días de Bogotá, incluidos
    registro_hasta: date | None = None
    cumple_mes: int | None = None  # 1..12
    sin_asistir_dias: int | None = None


@dataclass(frozen=True)
class FilaCliente:
    id: int
    codigo: str
    nombres: str
    apellidos: str
    tipo_documento: str
    documento: str
    sexo: str
    telefono: str
    correo: str
    plan: str
    fecha_fin: date | None
    vigencia: Vigencia
    dias_restantes: int | None
    estado: str
    creado_en: datetime

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}"


@dataclass(frozen=True)
class PaginaClientes:
    filas: list[FilaCliente]
    total: int


@dataclass(frozen=True)
class FilaMembresia:
    id: int
    plan: str
    fecha_inicio: date
    fecha_fin: date
    precio_pactado: int
    estado: str
    motivo_descuento: str | None
    pagado: int = 0
    motivo_anulacion: str | None = None

    @property
    def saldo(self) -> int:
        """Lo que falta por pagar (0 si está anulada)."""
        return 0 if self.estado == "anulada" else max(0, self.precio_pactado - self.pagado)


@dataclass(frozen=True)
class FilaPago:
    id: int
    consecutivo: int
    fecha_hora: datetime
    concepto: str
    monto: int
    metodo: str
    referencia: str | None
    usuario: str
    anulado: bool
    motivo_anulacion: str | None
    membresia_id: int | None = None


@dataclass(frozen=True)
class FilaAsistencia:
    id: int
    fecha_hora: datetime
    resultado: str
    casillero_numero: str | None
    usuario: str


@dataclass(frozen=True)
class FilaAlerta:
    id: int
    mensaje: str
    nivel: str
    activa: bool
    fecha_inicio: date
    fecha_fin: date | None


@dataclass(frozen=True)
class FilaCasillero:
    numero: str
    zona: str
    fecha_asignacion: datetime
    fecha_liberacion: datetime | None
    motivo_liberacion: str | None


@dataclass(frozen=True)
class FichaCliente:
    id: int
    codigo: str
    qr_token: str
    tipo_documento: str
    documento: str
    nombres: str
    apellidos: str
    sexo: str
    fecha_nacimiento: date | None
    direccion: str
    notas: str
    estado: str
    foto: Path | None
    autoriza_datos_en: datetime | None
    creado_en: datetime
    creado_por: str
    actualizado_en: datetime
    telefonos: list[str]
    correos: list[str]
    emergencias: list[ContactoEmergencia]
    vigencia: Vigencia
    dias_restantes: int | None
    fecha_fin: date | None
    plan_actual: str
    casillero: str | None
    cumple_hoy: bool
    membresias: list[FilaMembresia]
    pagos: list[FilaPago]
    asistencias: list[FilaAsistencia]
    alertas: list[FilaAlerta]
    historial_casilleros: list[FilaCasillero]

    @property
    def saldo_pendiente(self) -> int:
        return sum(m.saldo for m in self.membresias)

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombres} {self.apellidos}"

    @property
    def activo(self) -> bool:
        return self.estado == "activo"

    def a_datos(self) -> DatosCliente:
        """Datos para llenar el formulario de edición."""
        return DatosCliente(
            tipo_documento=self.tipo_documento, documento=self.documento,
            nombres=self.nombres, apellidos=self.apellidos, sexo=self.sexo,
            fecha_nacimiento=self.fecha_nacimiento, direccion=self.direccion,
            notas=self.notas, autoriza_datos=self.autoriza_datos_en is not None,
            telefonos=list(self.telefonos), correos=list(self.correos),
            emergencias=[ContactoEmergencia(e.nombre, e.telefono) for e in self.emergencias],
        )


# --- validación -------------------------------------------------------------------

def _texto(valor: str | None) -> str:
    return " ".join((valor or "").split())


def normalizar_telefono(valor: str) -> str:
    """Deja solo dígitos (y el + inicial). Lanza ErrorValidacion si no es un teléfono."""
    limpio = (valor or "").strip()
    if not limpio:
        return ""
    if not _PATRON_NUMERICO.match(limpio):
        raise ErrorValidacion(f"El teléfono «{limpio}» solo puede tener números.")
    mas = "+" if limpio.startswith("+") else ""
    digitos = re.sub(r"\D", "", limpio)
    if not 7 <= len(digitos) <= 15:
        raise ErrorValidacion(f"El teléfono «{limpio}» debe tener entre 7 y 15 dígitos.")
    return mas + digitos


def _validar(datos: DatosCliente, hoy: date) -> DatosCliente:
    tipo = (datos.tipo_documento or "").strip().upper()
    if tipo not in TIPOS_DOCUMENTO:
        raise ErrorValidacion("Seleccione el tipo de documento.")
    documento = re.sub(r"[\s.\-]", "", datos.documento or "").upper()
    if tipo in ("CC", "TI"):
        if not documento.isdigit() or not 5 <= len(documento) <= 11:
            raise ErrorValidacion(
                "El número de documento debe tener solo números (entre 5 y 11 dígitos)."
            )
    elif not re.fullmatch(r"[A-Z0-9]{3,20}", documento):
        raise ErrorValidacion(
            "El número de documento debe tener entre 3 y 20 letras o números."
        )
    nombres, apellidos = _texto(datos.nombres), _texto(datos.apellidos)
    if len(nombres) < 2:
        raise ErrorValidacion("Escriba los nombres del cliente.")
    if len(apellidos) < 2:
        raise ErrorValidacion("Escriba los apellidos del cliente.")
    if len(nombres) > 80 or len(apellidos) > 80:
        raise ErrorValidacion("Los nombres y los apellidos admiten máximo 80 caracteres.")
    if datos.sexo not in SEXOS:
        raise ErrorValidacion("Seleccione el sexo del cliente.")
    nacimiento = datos.fecha_nacimiento
    if nacimiento is not None:
        if nacimiento > hoy:
            raise ErrorValidacion("La fecha de nacimiento no puede ser futura.")
        if nacimiento.year < hoy.year - 110:
            raise ErrorValidacion("Revise la fecha de nacimiento.")
    direccion = _texto(datos.direccion)
    if len(direccion) > 200:
        raise ErrorValidacion("La dirección admite máximo 200 caracteres.")
    notas = (datos.notas or "").strip()
    if len(notas) > 1000:
        raise ErrorValidacion("Las notas admiten máximo 1000 caracteres.")

    telefonos = []
    for t in datos.telefonos:
        t = normalizar_telefono(t)
        if t and t not in telefonos:
            telefonos.append(t)
    correos = []
    for c in datos.correos:
        c = (c or "").strip().lower()
        if not c:
            continue
        if not _PATRON_CORREO.match(c) or len(c) > 120:
            raise ErrorValidacion(f"El correo «{c}» no es válido.")
        if c not in correos:
            correos.append(c)
    emergencias = []
    for e in datos.emergencias:
        nombre, telefono = _texto(e.nombre), normalizar_telefono(e.telefono)
        if not nombre and not telefono:
            continue
        if not telefono:
            raise ErrorValidacion("Escriba el teléfono del contacto de emergencia.")
        if not nombre:
            raise ErrorValidacion("Escriba el nombre del contacto de emergencia.")
        if len(nombre) > 120:
            raise ErrorValidacion("El nombre del contacto de emergencia es muy largo.")
        emergencias.append(ContactoEmergencia(nombre, telefono))
    return DatosCliente(
        tipo_documento=tipo, documento=documento, nombres=nombres, apellidos=apellidos,
        sexo=datos.sexo, fecha_nacimiento=nacimiento, direccion=direccion, notas=notas,
        autoriza_datos=bool(datos.autoriza_datos), telefonos=telefonos, correos=correos,
        emergencias=emergencias,
    )


def _prefijo(columna, prefijo: str) -> ColumnElement[bool]:
    """`columna` empieza por `prefijo`, escrito como rango para que use el índice."""
    siguiente = prefijo[:-1] + chr(ord(prefijo[-1]) + 1)
    return and_(columna >= prefijo, columna < siguiente)


def _valor_auditoria(valor) -> str:
    if isinstance(valor, date):
        return formato_fecha(valor)
    if isinstance(valor, list):
        return ", ".join(
            f"{v.nombre} ({v.telefono})" if isinstance(v, ContactoEmergencia) else str(v)
            for v in valor
        )
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    return "" if valor is None else str(valor)


# --- servicio -------------------------------------------------------------------------

class ServicioClientes:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._carpeta = carpeta_datos
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    # --- registro y modificación ---------------------------------------------------
    def registrar(self, actual: UsuarioActual, datos: DatosCliente) -> FichaCliente:
        exigir(actual, Permiso.REGISTRAR_CLIENTES)
        datos = _validar(datos, self.hoy())
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            self._exigir_documento_libre(sesion, datos.documento)
            cliente = Cliente(
                codigo=self._siguiente_codigo(sesion),
                qr_token=secrets.token_urlsafe(16),
                tipo_documento=datos.tipo_documento, documento=datos.documento,
                nombres=datos.nombres, apellidos=datos.apellidos, sexo=datos.sexo,
                fecha_nacimiento=datos.fecha_nacimiento,
                direccion=datos.direccion or None, notas=datos.notas or None,
                estado="activo",
                autoriza_datos_en=ahora if datos.autoriza_datos else None,
                creado_en=ahora, actualizado_en=ahora, creado_por=actual.id,
            )
            sesion.add(cliente)
            sesion.flush()
            self._guardar_contactos(sesion, cliente.id, datos)
            # Solo el código y quién lo registró: sin copiar datos personales.
            auditoria.registrar(
                sesion, "cliente_registrado", "clientes", usuario_id=actual.id,
                entidad_id=cliente.id, detalle={"codigo": cliente.codigo}, momento=ahora,
            )
            sesion.commit()
            cliente_id = cliente.id
        return self.obtener_ficha(actual, cliente_id)

    def modificar(
        self, actual: UsuarioActual, cliente_id: int, datos: DatosCliente
    ) -> list[str]:
        """Guarda los cambios. Devuelve los campos que cambiaron (vacío si no hubo)."""
        exigir(actual, Permiso.MODIFICAR_CONTACTO_CLIENTE)
        datos = _validar(datos, self.hoy())
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._obtener(sesion, cliente_id)
            anteriores = self._datos_actuales(sesion, cliente)
            cambios: dict[str, dict] = {}
            for campo in (
                "tipo_documento", "documento", "nombres", "apellidos", "sexo",
                "fecha_nacimiento", "direccion", "notas", "autoriza_datos",
                "telefonos", "correos", "emergencias",
            ):
                antes, despues = getattr(anteriores, campo), getattr(datos, campo)
                if antes != despues:
                    cambios[campo] = {
                        "antes": _valor_auditoria(antes), "despues": _valor_auditoria(despues)
                    }
            if not cambios:
                return []
            completos = set(cambios) - CAMPOS_CONTACTO
            if completos and not actual.puede(Permiso.MODIFICAR_CLIENTE_COMPLETO):
                raise ErrorPermiso(
                    "Recepción solo puede modificar teléfonos, correos, contacto de "
                    "emergencia y dirección. Pida al administrador los demás cambios."
                )
            if "documento" in cambios:
                self._exigir_documento_libre(sesion, datos.documento, excepto_id=cliente.id)

            cliente.tipo_documento = datos.tipo_documento
            cliente.documento = datos.documento
            cliente.nombres, cliente.apellidos = datos.nombres, datos.apellidos
            cliente.sexo = datos.sexo
            cliente.fecha_nacimiento = datos.fecha_nacimiento
            cliente.direccion = datos.direccion or None
            cliente.notas = datos.notas or None
            if "autoriza_datos" in cambios:
                cliente.autoriza_datos_en = ahora if datos.autoriza_datos else None
            if cambios.keys() & {"telefonos", "correos", "emergencias"}:
                for contacto in list(cliente.contactos):
                    sesion.delete(contacto)
                sesion.flush()
                self._guardar_contactos(sesion, cliente.id, datos)
            cliente.actualizado_en = ahora
            auditoria.registrar(
                sesion, "cliente_modificado", "clientes", usuario_id=actual.id,
                entidad_id=cliente.id, detalle={"codigo": cliente.codigo, **cambios},
                momento=ahora,
            )
            sesion.commit()
            return list(cambios)

    def cambiar_foto(
        self, actual: UsuarioActual, cliente_id: int, ruta_origen: Path | str | None
    ) -> Path | None:
        """Copia la foto a la carpeta de datos (o la quita si `ruta_origen` es None)."""
        exigir(actual, Permiso.MODIFICAR_CONTACTO_CLIENTE)
        destino = None
        if ruta_origen is not None:
            ruta_origen = Path(ruta_origen)
            extension = ruta_origen.suffix.lower()
            if extension not in EXTENSIONES_FOTO:
                raise ErrorValidacion("La foto debe ser una imagen PNG o JPG.")
            if not ruta_origen.is_file():
                raise ErrorValidacion("No se encontró el archivo de la foto.")
            if ruta_origen.stat().st_size > TAMANO_MAXIMO_FOTO:
                raise ErrorValidacion("La foto no debe pesar más de 5 MB.")
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._obtener(sesion, cliente_id)
            carpeta = self._carpeta_fotos()
            anterior = carpeta / cliente.foto_ruta if cliente.foto_ruta else None
            nombre = None
            if ruta_origen is not None:
                nombre = f"{cliente.codigo}{extension}"
                destino = carpeta / nombre
                shutil.copyfile(ruta_origen, destino)
            if anterior and anterior != destino and anterior.exists():
                anterior.unlink()
            cliente.foto_ruta = nombre
            cliente.actualizado_en = self._reloj()
            auditoria.registrar(
                sesion, "cliente_foto_cambiada", "clientes", usuario_id=actual.id,
                entidad_id=cliente.id,
                detalle={"codigo": cliente.codigo, "foto": "actualizada" if nombre else "quitada"},
            )
            sesion.commit()
        return destino

    # --- estado administrativo ------------------------------------------------------
    def casillero_activo(self, actual: UsuarioActual, cliente_id: int) -> str | None:
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            asignacion = self._asignacion_activa(sesion, cliente_id)
            return asignacion[1].numero if asignacion else None

    def inactivar(
        self, actual: UsuarioActual, cliente_id: int, motivo: str,
        liberar_casillero: bool | None = None,
    ) -> None:
        """Solo admin. Si tiene casillero, `liberar_casillero` debe indicar qué hacer
        (None lanza ErrorCasilleroAsignado para que la pantalla pregunte)."""
        exigir(actual, Permiso.ACTIVAR_CLIENTES)
        motivo = _texto(motivo)
        if len(motivo) < 3:
            raise ErrorValidacion("Escriba el motivo de la inactivación.")
        if len(motivo) > 200:
            raise ErrorValidacion("El motivo admite máximo 200 caracteres.")
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._obtener(sesion, cliente_id)
            if cliente.estado == "inactivo":
                raise ErrorValidacion("El cliente ya está inactivo.")
            asignacion = self._asignacion_activa(sesion, cliente.id)
            if asignacion and liberar_casillero is None:
                raise ErrorCasilleroAsignado(asignacion[1].numero)
            cliente.estado = "inactivo"
            cliente.actualizado_en = ahora
            detalle = {"codigo": cliente.codigo, "motivo": motivo}
            if asignacion and liberar_casillero:
                registro, casillero = asignacion
                registro.fecha_liberacion = ahora
                registro.liberado_por = actual.id
                registro.motivo_liberacion = f"Cliente inactivado: {motivo}"[:200]
                if casillero.estado == "ocupado":
                    casillero.estado = "disponible"
                detalle["casillero_liberado"] = casillero.numero
                auditoria.registrar(
                    sesion, "casillero_liberado", "casilleros", usuario_id=actual.id,
                    entidad_id=casillero.id, momento=ahora,
                    detalle={"casillero": casillero.numero, "cliente": cliente.codigo,
                             "motivo": registro.motivo_liberacion},
                )
            elif asignacion:
                detalle["casillero_conservado"] = asignacion[1].numero
            auditoria.registrar(
                sesion, "cliente_inactivado", "clientes", usuario_id=actual.id,
                entidad_id=cliente.id, detalle=detalle, momento=ahora,
            )
            sesion.commit()

    def activar(self, actual: UsuarioActual, cliente_id: int) -> None:
        exigir(actual, Permiso.ACTIVAR_CLIENTES)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._obtener(sesion, cliente_id)
            if cliente.estado == "activo":
                raise ErrorValidacion("El cliente ya está activo.")
            cliente.estado = "activo"
            cliente.actualizado_en = self._reloj()
            auditoria.registrar(
                sesion, "cliente_activado", "clientes", usuario_id=actual.id,
                entidad_id=cliente.id, detalle={"codigo": cliente.codigo},
            )
            sesion.commit()

    # --- consulta ---------------------------------------------------------------------
    def obtener_ficha(
        self, actual: UsuarioActual, cliente_id: int, max_asistencias: int = 200
    ) -> FichaCliente:
        exigir(actual, Permiso.VER_CLIENTES)
        hoy = self.hoy()
        dias_por_vencer = self._configuracion.obtener("dias_por_vencer")
        with self._fabrica() as sesion:
            cliente = self._obtener(sesion, cliente_id)
            datos = self._datos_actuales(sesion, cliente)
            nombres_usuarios = dict(sesion.execute(select(Usuario.id, Usuario.usuario)).all())

            filas_membresias = sesion.execute(
                select(Membresia, Plan.nombre).join(Plan, Plan.id == Membresia.plan_id)
                .where(Membresia.cliente_id == cliente.id)
                .order_by(Membresia.fecha_fin.desc(), Membresia.id.desc())
            ).all()
            pagado = saldos_por_membresia(sesion, [m.id for m, _ in filas_membresias])
            membresias = [
                FilaMembresia(m.id, nombre_plan, m.fecha_inicio, m.fecha_fin, m.precio_pactado,
                              m.estado, m.motivo_descuento, pagado.get(m.id, 0),
                              m.motivo_anulacion)
                for m, nombre_plan in filas_membresias
            ]
            vigentes = [m for m in membresias if m.estado == "activa"]
            fecha_fin = vigentes[0].fecha_fin if vigentes else None
            vigencia, dias = calcular_vigencia(fecha_fin, hoy, dias_por_vencer)

            pagos = [
                FilaPago(p.id, p.consecutivo, p.fecha_hora, p.concepto, p.monto, p.metodo,
                         p.referencia, nombres_usuarios.get(p.usuario_id, "—"), p.anulado,
                         p.motivo_anulacion, p.membresia_id)
                for p in sesion.scalars(
                    select(Pago).where(Pago.cliente_id == cliente.id)
                    .order_by(Pago.fecha_hora.desc(), Pago.id.desc())
                )
            ]
            asistencias = [
                FilaAsistencia(a.id, a.fecha_hora, a.resultado, a.casillero_numero,
                               nombres_usuarios.get(a.usuario_id, "—"))
                for a in sesion.scalars(
                    select(Asistencia)
                    .where(Asistencia.cliente_id == cliente.id, Asistencia.eliminada.is_(False))
                    .order_by(Asistencia.fecha_hora.desc()).limit(max_asistencias)
                )
            ]
            alertas = [
                FilaAlerta(a.id, a.mensaje, a.nivel, a.activa, a.fecha_inicio, a.fecha_fin)
                for a in sesion.scalars(
                    select(Alerta).where(Alerta.cliente_id == cliente.id)
                    .order_by(Alerta.activa.desc(), Alerta.creada_en.desc())
                )
            ]
            historial = [
                FilaCasillero(c.numero, c.zona, a.fecha_asignacion, a.fecha_liberacion,
                              a.motivo_liberacion)
                for a, c in sesion.execute(
                    select(CasilleroAsignacion, Casillero)
                    .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
                    .where(CasilleroAsignacion.cliente_id == cliente.id)
                    .order_by(CasilleroAsignacion.fecha_asignacion.desc())
                )
            ]
            actual_casillero = next(
                (h.numero for h in historial if h.fecha_liberacion is None), None
            )
            foto = None
            if cliente.foto_ruta:
                ruta = self._carpeta_fotos() / cliente.foto_ruta
                foto = ruta if ruta.exists() else None
            nacimiento = cliente.fecha_nacimiento
            return FichaCliente(
                id=cliente.id, codigo=cliente.codigo, qr_token=cliente.qr_token,
                tipo_documento=cliente.tipo_documento, documento=cliente.documento,
                nombres=cliente.nombres, apellidos=cliente.apellidos, sexo=cliente.sexo,
                fecha_nacimiento=nacimiento, direccion=cliente.direccion or "",
                notas=cliente.notas or "", estado=cliente.estado, foto=foto,
                autoriza_datos_en=cliente.autoriza_datos_en, creado_en=cliente.creado_en,
                creado_por=nombres_usuarios.get(cliente.creado_por, "—"),
                actualizado_en=cliente.actualizado_en,
                telefonos=datos.telefonos, correos=datos.correos, emergencias=datos.emergencias,
                vigencia=vigencia, dias_restantes=dias, fecha_fin=fecha_fin,
                plan_actual=vigentes[0].plan if vigentes else "",
                casillero=actual_casillero,
                cumple_hoy=bool(nacimiento and (nacimiento.month, nacimiento.day)
                                == (hoy.month, hoy.day)),
                membresias=membresias, pagos=pagos, asistencias=asistencias,
                alertas=alertas, historial_casilleros=historial,
            )

    def buscar(
        self,
        actual: UsuarioActual,
        filtros: FiltrosClientes = FiltrosClientes(),
        *,
        orden: str = "apellidos",
        descendente: bool = False,
        desde: int = 0,
        limite: int | None = 200,
    ) -> PaginaClientes:
        """Lista de clientes filtrada y ordenada, por páginas (`desde`, `limite`)."""
        exigir(actual, Permiso.VER_CLIENTES)
        hoy = self.hoy()
        dias_por_vencer = self._configuracion.obtener("dias_por_vencer")
        expr = _Expresiones()
        condiciones = self._condiciones(filtros, expr, hoy, dias_por_vencer)
        if orden not in expr.orden:
            raise ErrorValidacion(f"No se puede ordenar por «{orden}».")
        columna_orden = expr.orden[orden]
        criterio = columna_orden.desc() if descendente else columna_orden.asc()
        consulta = (
            select(
                Cliente.id, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                Cliente.tipo_documento, Cliente.documento, Cliente.sexo, Cliente.estado,
                Cliente.creado_en, expr.telefono.label("telefono"),
                expr.correo.label("correo"), expr.plan.label("plan"),
                expr.fin.label("fin"),
            )
            .where(*condiciones)
            .order_by(criterio, Cliente.id.desc() if descendente else Cliente.id.asc())
            .offset(desde)
        )
        if limite is not None:
            consulta = consulta.limit(limite)
        with self._fabrica() as sesion:
            total = sesion.scalar(select(func.count(Cliente.id)).where(*condiciones))
            filas = []
            for r in sesion.execute(consulta):
                fin = date.fromisoformat(r.fin) if isinstance(r.fin, str) else r.fin
                vigencia, dias = calcular_vigencia(fin, hoy, dias_por_vencer)
                filas.append(FilaCliente(
                    id=r.id, codigo=r.codigo, nombres=r.nombres, apellidos=r.apellidos,
                    tipo_documento=r.tipo_documento, documento=r.documento, sexo=r.sexo,
                    telefono=r.telefono or "", correo=r.correo or "", plan=r.plan or "",
                    fecha_fin=fin, vigencia=vigencia, dias_restantes=dias, estado=r.estado,
                    creado_en=r.creado_en,
                ))
        return PaginaClientes(filas, total)

    def buscar_rapido(self, actual: UsuarioActual, texto: str, limite: int = 10) -> list[FilaCliente]:
        """Búsqueda global (Ctrl+K): código o QR exactos primero; si no, la búsqueda normal."""
        texto = (texto or "").strip()
        if not texto:
            return []
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            condicion = Cliente.qr_token == texto
            if texto.isdigit() and len(texto) <= 6:
                condicion = or_(condicion, Cliente.codigo == texto.zfill(6))
            exacto = sesion.scalar(select(Cliente.id).where(condicion))
        if exacto:
            return self._filas_por_ids([exacto])
        return self.buscar(actual, FiltrosClientes(texto=texto), limite=limite).filas

    def _filas_por_ids(self, ids: list[int]) -> list[FilaCliente]:
        hoy = self.hoy()
        dias_por_vencer = self._configuracion.obtener("dias_por_vencer")
        expr = _Expresiones()
        with self._fabrica() as sesion:
            filas = []
            for r in sesion.execute(
                select(Cliente, expr.telefono, expr.correo, expr.plan, expr.fin)
                .where(Cliente.id.in_(ids))
            ):
                c, telefono, correo, plan, fin = r
                fin = date.fromisoformat(fin) if isinstance(fin, str) else fin
                vigencia, dias = calcular_vigencia(fin, hoy, dias_por_vencer)
                filas.append(FilaCliente(
                    c.id, c.codigo, c.nombres, c.apellidos, c.tipo_documento, c.documento,
                    c.sexo, telefono or "", correo or "", plan or "", fin, vigencia, dias,
                    c.estado, c.creado_en,
                ))
            return filas

    def planes(self, actual: UsuarioActual) -> list[tuple[int, str]]:
        """Planes para el filtro de la lista (incluye los inactivos)."""
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            return [tuple(f) for f in sesion.execute(
                select(Plan.id, Plan.nombre).order_by(Plan.activo.desc(), Plan.nombre)
            )]

    # --- exportación ----------------------------------------------------------------
    COLUMNAS_EXPORTACION = (
        "Código", "Nombres", "Apellidos", "Documento", "Sexo", "Teléfono", "Correo",
        "Plan", "Vence", "Vigencia", "Estado", "Registro",
    )

    def exportar(
        self, actual: UsuarioActual, filtros: FiltrosClientes, ruta: Path | str,
        formato: str, *, orden: str = "apellidos", descendente: bool = False,
    ) -> int:
        """Exporta a Excel ("xlsx") o PDF ("pdf") la lista filtrada. Solo admin.

        Devuelve cuántos clientes se exportaron y lo deja en la auditoría.
        """
        exigir(actual, Permiso.REPORTES_TODOS)
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        pagina = self.buscar(actual, filtros, orden=orden, descendente=descendente, limite=None)
        filas = [
            (
                f.codigo, f.nombres, f.apellidos, f"{f.tipo_documento} {f.documento}",
                SEXOS.get(f.sexo, f.sexo), f.telefono, f.correo, f.plan,
                f.fecha_fin, NOMBRES_VIGENCIA[f.vigencia], ESTADOS.get(f.estado, f.estado),
                f.creado_en.astimezone(cfg.ZONA_HORARIA).date(),
            )
            for f in pagina.filas
        ]
        titulo = "Clientes"
        nombre_gimnasio = self._configuracion.obtener("gimnasio_nombre")
        subtitulo = f"{nombre_gimnasio} · {len(filas)} clientes · generado el {formato_fecha(self.hoy())}"
        if formato == "xlsx":
            exp.exportar_excel(ruta, titulo, self.COLUMNAS_EXPORTACION, filas)
        else:
            exp.exportar_pdf(ruta, titulo, subtitulo, self.COLUMNAS_EXPORTACION, filas)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "clientes_exportados", "clientes", usuario_id=actual.id,
                detalle={"formato": formato, "cantidad": len(filas)},
            )
            sesion.commit()
        return len(filas)

    # --- auxiliares ------------------------------------------------------------------
    def _condiciones(
        self, filtros: FiltrosClientes, expr: _Expresiones, hoy: date, dias_por_vencer: int
    ) -> list[ColumnElement[bool]]:
        condiciones: list[ColumnElement[bool]] = []
        texto = (filtros.texto or "").strip()
        if texto:
            condiciones.append(_condicion_texto(texto))
        if filtros.estado:
            condiciones.append(Cliente.estado == filtros.estado)
        if filtros.sexo:
            condiciones.append(Cliente.sexo == filtros.sexo)
        if filtros.vigencia:
            limite = hoy + timedelta(days=dias_por_vencer)
            condiciones.append({
                Vigencia.SIN_MEMBRESIA: expr.fin.is_(None),
                Vigencia.VENCIDA: expr.fin < hoy,
                Vigencia.POR_VENCER: and_(expr.fin >= hoy, expr.fin <= limite),
                Vigencia.VIGENTE: expr.fin > limite,
            }[Vigencia(filtros.vigencia)])
        if filtros.plan_id:
            condiciones.append(expr.plan_id == filtros.plan_id)
        if filtros.registro_desde:
            condiciones.append(Cliente.creado_en >= inicio_dia_utc(filtros.registro_desde))
        if filtros.registro_hasta:
            condiciones.append(
                Cliente.creado_en < inicio_dia_utc(filtros.registro_hasta + timedelta(days=1))
            )
        if filtros.cumple_mes:
            condiciones.append(
                func.strftime("%m", Cliente.fecha_nacimiento) == f"{filtros.cumple_mes:02d}"
            )
        if filtros.sin_asistir_dias:
            desde = hoy - timedelta(days=filtros.sin_asistir_dias)
            condiciones.append(~exists().where(
                Asistencia.cliente_id == Cliente.id,
                Asistencia.eliminada.is_(False),
                # Los intentos rechazados (vencido, inactivo) no cuentan como asistencia.
                Asistencia.resultado.in_(("permitido", "por_vencer", "autorizado")),
                Asistencia.fecha > desde,
            ))
        return condiciones

    @staticmethod
    def _siguiente_codigo(sesion: Session) -> str:
        ultimo = sesion.scalar(select(func.max(Cliente.codigo)))
        siguiente = int(ultimo) + 1 if ultimo else 1
        if siguiente > CODIGO_MAXIMO:
            raise ErrorValidacion("Se agotaron los códigos de cliente de 6 dígitos.")
        return f"{siguiente:06d}"

    @staticmethod
    def _exigir_documento_libre(
        sesion: Session, documento: str, excepto_id: int | None = None
    ) -> None:
        consulta = select(Cliente.codigo, Cliente.nombres, Cliente.apellidos).where(
            Cliente.documento == documento
        )
        if excepto_id is not None:
            consulta = consulta.where(Cliente.id != excepto_id)
        existente = sesion.execute(consulta).first()
        if existente:
            raise ErrorValidacion(
                f"Ya existe un cliente con el documento {documento}: código "
                f"{existente.codigo} ({existente.nombres} {existente.apellidos})."
            )

    @staticmethod
    def _obtener(sesion: Session, cliente_id: int) -> Cliente:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise ErrorValidacion("El cliente no existe.")
        return cliente

    @staticmethod
    def _asignacion_activa(
        sesion: Session, cliente_id: int
    ) -> tuple[CasilleroAsignacion, Casillero] | None:
        fila = sesion.execute(
            select(CasilleroAsignacion, Casillero)
            .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
            .where(
                CasilleroAsignacion.cliente_id == cliente_id,
                CasilleroAsignacion.fecha_liberacion.is_(None),
            )
        ).first()
        return (fila[0], fila[1]) if fila else None

    @staticmethod
    def _datos_actuales(sesion: Session, cliente: Cliente) -> DatosCliente:
        contactos = sesion.scalars(
            select(Contacto).where(Contacto.cliente_id == cliente.id)
            .order_by(Contacto.principal.desc(), Contacto.id)
        ).all()
        return DatosCliente(
            tipo_documento=cliente.tipo_documento, documento=cliente.documento,
            nombres=cliente.nombres, apellidos=cliente.apellidos, sexo=cliente.sexo,
            fecha_nacimiento=cliente.fecha_nacimiento, direccion=cliente.direccion or "",
            notas=cliente.notas or "", autoriza_datos=cliente.autoriza_datos_en is not None,
            telefonos=[c.valor for c in contactos if c.tipo == "telefono"],
            correos=[c.valor for c in contactos if c.tipo == "email"],
            emergencias=[
                ContactoEmergencia(c.nombre_contacto or "", c.valor)
                for c in contactos if c.tipo == "emergencia"
            ],
        )

    @staticmethod
    def _guardar_contactos(sesion: Session, cliente_id: int, datos: DatosCliente) -> None:
        for i, telefono in enumerate(datos.telefonos):
            sesion.add(Contacto(cliente_id=cliente_id, tipo="telefono", valor=telefono,
                                principal=i == 0))
        for i, correo in enumerate(datos.correos):
            sesion.add(Contacto(cliente_id=cliente_id, tipo="email", valor=correo,
                                principal=i == 0))
        for i, e in enumerate(datos.emergencias):
            sesion.add(Contacto(cliente_id=cliente_id, tipo="emergencia", valor=e.telefono,
                                nombre_contacto=e.nombre, principal=i == 0))

    def _carpeta_fotos(self) -> Path:
        carpeta = (self._carpeta or cfg.carpeta_datos()) / "fotos"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta


class _Expresiones:
    """Subconsultas correlacionadas por cliente. Usan los índices de membresías y
    contactos, así solo se calculan para las filas que se consultan."""

    def __init__(self):
        self.fin = (
            select(func.max(Membresia.fecha_fin))
            .where(Membresia.cliente_id == Cliente.id, Membresia.estado == "activa")
            .scalar_subquery()
        )
        ultima = (
            select(Membresia.plan_id)
            .where(Membresia.cliente_id == Cliente.id, Membresia.estado == "activa")
            .order_by(Membresia.fecha_fin.desc(), Membresia.id.desc())
            .limit(1)
            .correlate(Cliente)
        )
        self.plan_id = ultima.scalar_subquery()
        self.plan = (
            select(Plan.nombre).where(Plan.id == ultima.scalar_subquery()).scalar_subquery()
        )
        self.telefono = self._contacto("telefono")
        self.correo = self._contacto("email")
        self.orden = {
            "codigo": Cliente.codigo,
            "nombres": Cliente.nombres,
            "apellidos": Cliente.apellidos,
            "documento": Cliente.documento,
            "sexo": Cliente.sexo,
            "telefono": self.telefono,
            "correo": self.correo,
            "plan": self.plan,
            "vence": self.fin,
            "vigencia": self.fin,
            "estado": Cliente.estado,
            "registro": Cliente.creado_en,
        }

    @staticmethod
    def _contacto(tipo: str):
        return (
            select(Contacto.valor)
            .where(Contacto.cliente_id == Cliente.id, Contacto.tipo == tipo)
            .order_by(Contacto.principal.desc(), Contacto.id)
            .limit(1)
            .correlate(Cliente)
            .scalar_subquery()
        )


def _condicion_texto(texto: str) -> ColumnElement[bool]:
    """Código, documento, teléfono, correo o nombre (sin importar tildes ni mayúsculas)."""
    if _PATRON_NUMERICO.match(texto) and any(c.isdigit() for c in texto):
        # Cada parte usa su propio índice; unidas con UNION evitan recorrer la tabla.
        digitos = re.sub(r"\D", "", texto)
        partes = []
        if len(digitos) >= MINIMO_DIGITOS_PREFIJO:
            telefono = ("+" if texto.strip().startswith("+") else "") + digitos
            partes += [
                select(Cliente.id).where(_prefijo(Cliente.documento, digitos)),
                select(Contacto.cliente_id).where(
                    Contacto.tipo.in_(("telefono", "emergencia")),
                    _prefijo(Contacto.valor, telefono),
                ),
            ]
        if len(digitos) <= 6:
            partes.insert(0, select(Cliente.id).where(Cliente.codigo == digitos.zfill(6)))
        if len(partes) == 1:
            return Cliente.id.in_(partes[0])
        return Cliente.id.in_(union(*partes))
    if "@" in texto:
        return exists().where(
            Contacto.cliente_id == Cliente.id,
            Contacto.tipo == "email",
            Contacto.valor.like(f"%{_escapar_like(texto.lower())}%", escape="\\"),
        )
    palabras = [_escapar_like(p) for p in re.split(r"\s+", texto) if p]
    nombre = Cliente.busqueda
    por_nombre = and_(*[
        nombre.like(f"%{normalizar(p)}%", escape="\\") for p in palabras
    ])
    documento = re.sub(r"[\s.\-]", "", texto).upper()
    return or_(por_nombre, Cliente.documento == documento, Cliente.qr_token == texto)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
