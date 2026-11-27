"""Casilleros (sección 3.6): catálogo, asignar, renovar, liberar, cambiar, historial y listas.

Reglas:
- Un cliente tiene como máximo un casillero activo y un casillero pertenece como
  máximo a un cliente (RN-06). La base lo garantiza con índices únicos parciales;
  aquí se valida antes para dar mensajes claros.
- El casillero tiene **vencimiento propio** ("pagado hasta", inclusive), independiente
  de la membresía: se puede asignar o pagar en otra fecha. Su vigencia se calcula.
- Zonas por sexo: «hombres» solo para clientes de sexo masculino, «mujeres» solo
  femenino; «mixto» para cualquiera. Se bloquea, no solo se avisa.
- Nada se borra: liberar cierra la asignación con fecha, usuario y motivo; el
  historial queda. Los casilleros del catálogo tampoco se borran (mantenimiento).
- El sistema **sugiere** liberar (cliente inactivo o casillero vencido hace más de
  N días, configurable), pero nunca libera sin confirmación.
- Catálogo (crear, editar, mantenimiento) solo admin. Recepción asigna, renueva,
  cambia y libera. Cada acción queda en la auditoría.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.modelos import (
    Casillero, CasilleroAsignacion, Cliente, Contacto, Membresia, Usuario, ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.auditoria import inicio_dia_utc
from gimnasio.servicios.autorizaciones import (
    PARA_INSCRIPCION, PARA_PAGO, Autorizacion, registrar_uso,
)
from gimnasio.servicios.clientes import NOMBRES_VIGENCIA, SEXOS, Vigencia, calcular_vigencia
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.pagos import (
    DatosPago, MembresiaRegistrada, PagoRegistrado, ServicioPagos,
)
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente
from gimnasio.servicios.zonas_casilleros import (
    TOTAL_CASILLEROS_GIMNASIO, zona_del_gimnasio,
)

ZONAS = {"hombres": "Hombres", "mujeres": "Mujeres", "mixto": "Mixto"}
ESTADOS = {"disponible": "Disponible", "ocupado": "Ocupado", "mantenimiento": "En mantenimiento"}
SEXO_DE_ZONA = {"hombres": "M", "mujeres": "F"}
MOTIVOS_LIBERACION = (
    "Casillero vencido",
    "El cliente ya no lo quiere usar",
    "Cliente inactivo",
    "Otro",
)
DIAS_MAXIMOS = 366
# Cuánto se puede correr la fecha de inicio respecto a hoy al asignar o renovar.
DIAS_MARGEN_INICIO = 60
MAXIMO_LOTE = 500
_PATRON_NUMERO = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,9}$")


class VigenciaCasillero(str, Enum):
    AL_DIA = "al_dia"
    POR_VENCER = "por_vencer"
    VENCIDO = "vencido"
    SIN_FECHA = "sin_fecha"  # asignaciones anteriores a la Fase 5


NOMBRES_VIGENCIA_CASILLERO = {
    VigenciaCasillero.AL_DIA: "Al día",
    VigenciaCasillero.POR_VENCER: "Por vencer",
    VigenciaCasillero.VENCIDO: "Vencido",
    VigenciaCasillero.SIN_FECHA: "Sin fecha",
}

SITUACIONES = {
    "vencidos": "Casillero vencido",
    "por_vencer": "Casillero por vencer",
    "membresia_vencida": "Membresía del cliente vencida",
    "sugerido_liberar": "Sugerido liberar",
    "fuera_de_zona": "Ocupado fuera de su zona",
}


def calcular_vigencia_casillero(
    vence: date | None, hoy: date, dias_por_vencer: int
) -> tuple[VigenciaCasillero, int | None]:
    """Igual que la membresía: el último día pagado se puede usar (quedan 0 días)."""
    if vence is None:
        return VigenciaCasillero.SIN_FECHA, None
    dias = (vence - hoy).days
    if dias < 0:
        return VigenciaCasillero.VENCIDO, dias
    if dias <= dias_por_vencer:
        return VigenciaCasillero.POR_VENCER, dias
    return VigenciaCasillero.AL_DIA, dias


def zona_permitida(zona: str, sexo: str) -> bool:
    """«mixto» admite a todos; «hombres» solo M y «mujeres» solo F."""
    return zona == "mixto" or SEXO_DE_ZONA.get(zona) == sexo


def normalizar_numero(numero: str) -> str:
    texto = (numero or "").strip().upper()
    if not texto:
        raise ErrorValidacion("Escriba el número del casillero.")
    if not _PATRON_NUMERO.match(texto):
        raise ErrorValidacion(
            "El número del casillero admite hasta 10 letras, números o guiones (ej.: 015, A-12)."
        )
    return texto


def _clave_orden(numero: str) -> tuple:
    """Ordena 2 antes que 10 y deja los números con letras al final."""
    sin_ceros = numero.lstrip("0") or "0"
    return (0, int(sin_ceros), numero) if sin_ceros.isdigit() else (1, 0, numero)


def _motivo(texto: str) -> str:
    motivo = " ".join((texto or "").split())
    if len(motivo) < 3:
        raise ErrorValidacion("Escriba el motivo.")
    if len(motivo) > 200:
        raise ErrorValidacion("El motivo admite máximo 200 caracteres.")
    return motivo


def _texto_dias(dias: int) -> str:
    return f"{dias} {'día' if dias == 1 else 'días'}"


def aviso_casillero(numero: str, vigencia: VigenciaCasillero, dias: int | None,
                    vence: date | None, sugerir: bool) -> str:
    """Texto corto para Recepción y la ficha."""
    if vigencia == VigenciaCasillero.VENCIDO:
        texto = f"Casillero {numero} vencido hace {_texto_dias(-dias)} ({formato_fecha(vence)})"
    elif vigencia == VigenciaCasillero.POR_VENCER:
        texto = (f"Casillero {numero} vence hoy" if dias == 0
                 else f"Casillero {numero} vence en {_texto_dias(dias)} ({formato_fecha(vence)})")
    elif vigencia == VigenciaCasillero.SIN_FECHA:
        texto = f"Casillero {numero} sin fecha de vencimiento: renuévelo"
    else:
        texto = f"Casillero {numero} pagado hasta el {formato_fecha(vence)}"
    if sugerir:
        texto += " · sugerido liberar"
    return texto


# --- datos de entrada y salida ---------------------------------------------------------

@dataclass(frozen=True)
class FiltrosCasilleros:
    estado: str | None = None  # disponible / ocupado / mantenimiento
    zona: str | None = None
    sexo_cliente: str | None = None  # M / F / O (solo ocupados)
    situacion: str | None = None  # clave de SITUACIONES
    texto: str = ""  # número del casillero, código o nombre del cliente


@dataclass(frozen=True)
class FilaCasillero:
    casillero_id: int
    numero: str
    zona: str
    estado: str
    notas: str
    asignacion_id: int | None = None
    cliente_id: int | None = None
    codigo: str = ""
    cliente: str = ""
    sexo: str = ""
    cliente_activo: bool = True
    telefono: str = ""
    asignado_en: datetime | None = None  # UTC
    vence: date | None = None
    vigencia: VigenciaCasillero | None = None
    dias: int | None = None  # días restantes (negativo si vencido)
    vigencia_membresia: Vigencia | None = None
    dias_membresia: int | None = None
    sugerir_liberar: bool = False
    motivo_sugerencia: str = ""

    @property
    def ocupado(self) -> bool:
        return self.asignacion_id is not None

    @property
    def dias_vencido(self) -> int:
        return -self.dias if self.dias is not None and self.dias < 0 else 0

    @property
    def fuera_de_zona(self) -> bool:
        """Ocupado por alguien cuyo sexo no corresponde a la zona (p. ej. un hombre en un
        casillero de mujeres que ya lo tenía antes de definir las zonas). No se libera
        solo: se avisa para que lo cambien."""
        return self.ocupado and not zona_permitida(self.zona, self.sexo)


@dataclass(frozen=True)
class ResumenCasilleros:
    total: int
    disponibles: int
    ocupados: int
    mantenimiento: int
    vencidos: int
    sugeridos: int
    por_zona: dict[str, tuple[int, int]] = field(default_factory=dict)  # zona -> (total, ocupados)


@dataclass(frozen=True)
class CasilleroCliente:
    """El casillero que tiene un cliente ahora (ficha, Recepción)."""

    asignacion_id: int
    casillero_id: int
    numero: str
    zona: str
    asignado_en: datetime
    vence: date | None
    vigencia: VigenciaCasillero
    dias: int | None
    sugerir_liberar: bool

    @property
    def aviso(self) -> str:
        return aviso_casillero(self.numero, self.vigencia, self.dias, self.vence,
                               self.sugerir_liberar)


@dataclass(frozen=True)
class Propuesta:
    """Lo que la pantalla de asignar o renovar muestra precargado."""

    inicio: date
    dias: int
    vence: date
    precio: int
    vence_actual: date | None = None


@dataclass(frozen=True)
class AsignacionRegistrada:
    asignacion_id: int
    numero: str
    vence: date
    pago: PagoRegistrado | None


@dataclass(frozen=True)
class RenovacionRegistrada:
    asignacion_id: int
    numero: str
    vence_anterior: date | None
    vence: date
    pago: PagoRegistrado | None


@dataclass(frozen=True)
class CasilleroEnRecibo:
    """Casillero que se cobra junto con la mensualidad, en el mismo recibo.

    Se indica `casillero_id` para asignar uno libre (lo elige el usuario a mano) o
    `asignacion_id` para renovar el que el cliente ya tiene."""

    monto: int
    casillero_id: int | None = None
    asignacion_id: int | None = None
    fecha_inicio: date | None = None
    dias: int | None = None


@dataclass(frozen=True)
class MensualidadConCasillero:
    membresia: MembresiaRegistrada
    casillero: AsignacionRegistrada | RenovacionRegistrada
    recibo: str
    pago_id: int  # cualquiera de los dos pagos abre el mismo recibo


@dataclass(frozen=True)
class FilaHistorial:
    asignacion_id: int
    numero: str
    zona: str
    cliente_id: int
    codigo: str
    cliente: str
    asignado_en: datetime
    asignado_por: str
    vence: date | None
    liberado_en: datetime | None
    liberado_por: str
    motivo: str


@dataclass(frozen=True)
class Movimiento:
    """Asignación o liberación ocurrida en un día (lista «por día»)."""

    fecha_hora: datetime  # UTC
    tipo: str  # "Asignado" / "Liberado"
    numero: str
    zona: str
    codigo: str
    cliente: str
    sexo: str
    usuario: str
    vence: date | None
    motivo: str


@dataclass(frozen=True)
class Listado:
    """Lista lista para mostrar o exportar."""

    titulo: str
    subtitulo: str
    encabezados: tuple[str, ...]
    filas: list[tuple]


# --- servicio --------------------------------------------------------------------------

class ServicioCasilleros:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        pagos: ServicioPagos,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._pagos = pagos
        self._carpeta = carpeta_datos
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    # --- catálogo (solo admin) ----------------------------------------------------
    def crear(self, actual: UsuarioActual, numero: str, zona: str, notas: str = "") -> int:
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        numero = normalizar_numero(numero)
        zona = self._zona(zona)
        notas = self._notas(notas)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            self._exigir_numero_libre(sesion, numero)
            casillero = Casillero(numero=numero, zona=zona, estado="disponible",
                                  notas=notas or None)
            sesion.add(casillero)
            sesion.flush()
            auditoria.registrar(
                sesion, "casillero_creado", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, detalle={"casillero": numero, "zona": zona},
                momento=self._reloj(),
            )
            sesion.commit()
            return casillero.id

    def crear_rango(
        self, actual: UsuarioActual, desde: int, hasta: int, zona: str, digitos: int = 3,
        prefijo: str = "",
    ) -> list[str]:
        """Crea varios casilleros de una vez (p. ej. del 1 al 50). Omite los que ya existen.

        Devuelve los números creados."""
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        zona = self._zona(zona)
        if desde < 1 or hasta < desde:
            raise ErrorValidacion("Indique un rango válido (por ejemplo, del 1 al 50).")
        if hasta - desde + 1 > MAXIMO_LOTE:
            raise ErrorValidacion(f"Se pueden crear máximo {MAXIMO_LOTE} casilleros a la vez.")
        if not 1 <= digitos <= 6:
            raise ErrorValidacion("Los dígitos deben estar entre 1 y 6.")
        prefijo = (prefijo or "").strip().upper()
        numeros = [normalizar_numero(f"{prefijo}{n:0{digitos}d}") for n in range(desde, hasta + 1)]
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            existentes = set(sesion.scalars(
                select(Casillero.numero).where(Casillero.numero.in_(numeros))
            ))
            nuevos = [n for n in numeros if n not in existentes]
            sesion.add_all(Casillero(numero=n, zona=zona, estado="disponible") for n in nuevos)
            if nuevos:
                auditoria.registrar(
                    sesion, "casilleros_creados", "casilleros", usuario_id=actual.id,
                    detalle={"desde": nuevos[0], "hasta": nuevos[-1], "cantidad": len(nuevos),
                             "zona": zona, "omitidos": len(existentes)},
                    momento=self._reloj(),
                )
            sesion.commit()
            return nuevos

    def crear_catalogo_gimnasio(self) -> int:
        """Al arrancar: si no hay ningún casillero, crea los del gimnasio (001 al 411) con
        su zona. Devuelve cuántos creó (0 si ya había casilleros)."""
        with self._fabrica() as sesion:
            if sesion.scalar(select(func.count(Casillero.id))):
                return 0
            sesion.add_all(
                Casillero(numero=f"{n:03d}", zona=zona_del_gimnasio(n), estado="disponible")
                for n in range(1, TOTAL_CASILLEROS_GIMNASIO + 1)
            )
            auditoria.registrar(
                sesion, "casilleros_creados", "casilleros", momento=self._reloj(),
                detalle={"desde": "001", "hasta": f"{TOTAL_CASILLEROS_GIMNASIO:03d}",
                         "cantidad": TOTAL_CASILLEROS_GIMNASIO, "zona": "del gimnasio"},
            )
            sesion.commit()
            return TOTAL_CASILLEROS_GIMNASIO

    def modificar(
        self, actual: UsuarioActual, casillero_id: int, numero: str, zona: str, notas: str = ""
    ) -> list[str]:
        """Cambia número, zona o notas. Devuelve los campos cambiados."""
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        numero = normalizar_numero(numero)
        zona = self._zona(zona)
        notas = self._notas(notas)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            casillero = self._casillero(sesion, casillero_id)
            cambios: dict[str, dict] = {}
            for campo, nuevo in (("numero", numero), ("zona", zona), ("notas", notas)):
                anterior = getattr(casillero, campo) or ""
                if anterior != nuevo:
                    cambios[campo] = {"antes": anterior, "despues": nuevo}
            if not cambios:
                return []
            if "numero" in cambios:
                self._exigir_numero_libre(sesion, numero, excepto_id=casillero.id)
            if "zona" in cambios:
                ocupante = self._ocupante(sesion, casillero.id)
                if ocupante and not zona_permitida(zona, ocupante.sexo):
                    raise ErrorValidacion(
                        f"El casillero lo ocupa {ocupante.nombres} {ocupante.apellidos} "
                        f"({SEXOS.get(ocupante.sexo, ocupante.sexo).lower()}): no puede pasar a "
                        f"la zona {ZONAS[zona].lower()}. Cámbielo de casillero primero."
                    )
            casillero.numero, casillero.zona, casillero.notas = numero, zona, notas or None
            auditoria.registrar(
                sesion, "casillero_editado", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, detalle={"casillero": numero, **cambios},
                momento=self._reloj(),
            )
            sesion.commit()
            return list(cambios)

    def poner_en_mantenimiento(self, actual: UsuarioActual, casillero_id: int, nota: str) -> None:
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        nota = _motivo(nota)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            casillero = self._casillero(sesion, casillero_id)
            if self._ocupante(sesion, casillero.id) is not None:
                raise ErrorValidacion(
                    "El casillero está ocupado. Libérelo o cambie al cliente de casillero antes "
                    "de ponerlo en mantenimiento."
                )
            if casillero.estado == "mantenimiento":
                raise ErrorValidacion("El casillero ya está en mantenimiento.")
            casillero.estado = "mantenimiento"
            casillero.notas = nota
            auditoria.registrar(
                sesion, "casillero_mantenimiento", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, detalle={"casillero": casillero.numero, "motivo": nota},
                momento=self._reloj(),
            )
            sesion.commit()

    def habilitar(self, actual: UsuarioActual, casillero_id: int) -> None:
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            casillero = self._casillero(sesion, casillero_id)
            if casillero.estado != "mantenimiento":
                raise ErrorValidacion("El casillero no está en mantenimiento.")
            casillero.estado = "disponible"
            auditoria.registrar(
                sesion, "casillero_habilitado", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, detalle={"casillero": casillero.numero},
                momento=self._reloj(),
            )
            sesion.commit()

    # --- asignar, renovar, cambiar y liberar ----------------------------------------
    def proponer(
        self, actual: UsuarioActual, asignacion_id: int | None = None
    ) -> Propuesta:
        """Propuesta para asignar (sin `asignacion_id`) o renovar.

        Al renovar: si sigue al día, el nuevo periodo empieza el día siguiente al
        vencimiento; si ya venció, empieza hoy (como RN-04 en membresías)."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        hoy = self.hoy()
        with self._fabrica() as sesion:
            dias = self._configuracion.obtener("casillero_dias", sesion)
            precio = self._configuracion.obtener("casillero_precio", sesion)
            vence_actual = None
            inicio = hoy
            if asignacion_id is not None:
                asignacion = self._asignacion_activa_por_id(sesion, asignacion_id)
                vence_actual = asignacion.fecha_vencimiento
                if vence_actual is not None and vence_actual >= hoy:
                    inicio = vence_actual + timedelta(days=1)
        return Propuesta(inicio, dias, inicio + timedelta(days=dias - 1), precio, vence_actual)

    def asignar(
        self, actual: UsuarioActual, casillero_id: int, cliente_id: int, *,
        fecha_inicio: date | None = None, dias: int | None = None, pago: DatosPago | None = None,
        autorizacion: Autorizacion | None = None,
    ) -> AsignacionRegistrada:
        """Asigna el casillero. Con pago, Recepción necesita la clave de un administrador."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        admin = None
        if pago is not None:
            exigir(actual, Permiso.REGISTRAR_PAGOS)
            admin = self._pagos.autorizaciones.verificar(actual, autorizacion, PARA_PAGO)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registrada = self._asignar_en_sesion(
                sesion, actual, casillero_id, cliente_id, fecha_inicio, dias, pago, ahora)
            if registrada.pago:
                registrar_uso(sesion, actual, admin, "pago de casillero", ahora,
                              recibo=registrada.pago.recibo)
            sesion.commit()
        if pago is not None:
            self._pagos.autorizaciones.gastar(autorizacion)
        return registrada

    def _asignar_en_sesion(
        self, sesion: Session, actual: UsuarioActual, casillero_id: int, cliente_id: int,
        fecha_inicio: date | None, dias: int | None, pago: DatosPago | None, ahora: datetime,
        consecutivo: int | None = None,
    ) -> AsignacionRegistrada:
        inicio, dias = self._periodo(sesion, fecha_inicio, dias)
        casillero = self._casillero(sesion, casillero_id)
        cliente = self._cliente(sesion, cliente_id)
        self._validar_asignacion(sesion, casillero, cliente)
        vence = inicio + timedelta(days=dias - 1)
        asignacion = CasilleroAsignacion(
            casillero_id=casillero.id, cliente_id=cliente.id, fecha_asignacion=ahora,
            fecha_vencimiento=vence, asignado_por=actual.id,
        )
        sesion.add(asignacion)
        casillero.estado = "ocupado"
        try:
            sesion.flush()
        except IntegrityError:
            # Otro usuario lo asignó en el mismo instante: la base lo impide.
            sesion.rollback()
            raise ErrorValidacion(
                "El casillero o el cliente ya tienen una asignación activa. "
                "Actualice la lista e intente de nuevo."
            ) from None
        registrado = None
        if pago is not None:
            registrado = self._pagos.pago_casillero_en_sesion(
                sesion, actual, cliente, pago, asignacion.id, ahora, consecutivo)
        auditoria.registrar(
            sesion, "casillero_asignado", "casilleros", usuario_id=actual.id,
            entidad_id=casillero.id, momento=ahora,
            detalle={"casillero": casillero.numero, "cliente": cliente.codigo,
                     "desde": formato_fecha(inicio), "vence": formato_fecha(vence),
                     **({"recibo": registrado.recibo} if registrado else {})},
        )
        return AsignacionRegistrada(asignacion.id, casillero.numero, vence, registrado)

    def renovar(
        self, actual: UsuarioActual, asignacion_id: int, *,
        fecha_inicio: date | None = None, dias: int | None = None, pago: DatosPago | None = None,
        autorizacion: Autorizacion | None = None,
    ) -> RenovacionRegistrada:
        """Extiende el vencimiento del casillero (opcionalmente con su pago; con pago,
        Recepción necesita la clave de un administrador)."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        admin = None
        if pago is not None:
            exigir(actual, Permiso.REGISTRAR_PAGOS)
            admin = self._pagos.autorizaciones.verificar(actual, autorizacion, PARA_PAGO)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registrada = self._renovar_en_sesion(
                sesion, actual, asignacion_id, fecha_inicio, dias, pago, ahora)
            if registrada.pago:
                registrar_uso(sesion, actual, admin, "pago de casillero", ahora,
                              recibo=registrada.pago.recibo)
            sesion.commit()
        if pago is not None:
            self._pagos.autorizaciones.gastar(autorizacion)
        return registrada

    def _renovar_en_sesion(
        self, sesion: Session, actual: UsuarioActual, asignacion_id: int,
        fecha_inicio: date | None, dias: int | None, pago: DatosPago | None, ahora: datetime,
        consecutivo: int | None = None,
    ) -> RenovacionRegistrada:
        asignacion = self._asignacion_activa_por_id(sesion, asignacion_id)
        casillero = self._casillero(sesion, asignacion.casillero_id)
        cliente = self._cliente(sesion, asignacion.cliente_id)
        if fecha_inicio is None:
            anterior = asignacion.fecha_vencimiento
            hoy = self.hoy()
            fecha_inicio = (anterior + timedelta(days=1)
                            if anterior is not None and anterior >= hoy else hoy)
        inicio, dias = self._periodo(sesion, fecha_inicio, dias, renovacion=True)
        vence = inicio + timedelta(days=dias - 1)
        anterior = asignacion.fecha_vencimiento
        if anterior is not None and vence <= anterior:
            raise ErrorValidacion(
                f"El casillero ya está pagado hasta el {formato_fecha(anterior)}: el nuevo "
                "vencimiento debe ser posterior."
            )
        asignacion.fecha_vencimiento = vence
        registrado = None
        if pago is not None:
            registrado = self._pagos.pago_casillero_en_sesion(
                sesion, actual, cliente, pago, asignacion.id, ahora, consecutivo)
        auditoria.registrar(
            sesion, "casillero_renovado", "casilleros", usuario_id=actual.id,
            entidad_id=casillero.id, momento=ahora,
            detalle={"casillero": casillero.numero, "cliente": cliente.codigo,
                     "vence_antes": formato_fecha(anterior) if anterior else "",
                     "vence": formato_fecha(vence),
                     **({"recibo": registrado.recibo} if registrado else {})},
        )
        return RenovacionRegistrada(asignacion.id, casillero.numero, anterior, vence,
                                    registrado)

    def mensualidad_con_casillero(
        self, actual: UsuarioActual, cliente_id: int, plan_id: int, *,
        pago: DatosPago, casillero: CasilleroEnRecibo, fecha_inicio: date | None = None,
        precio_pactado: int | None = None, motivo_descuento: str = "",
        autorizacion: Autorizacion | None = None,
    ) -> MensualidadConCasillero:
        """Mensualidad y casillero pagados juntos: un solo recibo con un solo número.

        El casillero se asigna (uno libre elegido a mano) o se renueva el que ya tiene.
        Los dos pagos usan el mismo método y referencia. O se guarda todo o nada."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        admin = self._pagos.autorizaciones.verificar(
            actual, autorizacion, PARA_PAGO, PARA_INSCRIPCION)
        if pago is None:
            raise ErrorValidacion(
                "Para cobrar el casillero en el mismo recibo registre también el pago de "
                "la mensualidad."
            )
        if (casillero.casillero_id is None) == (casillero.asignacion_id is None):
            raise ErrorValidacion("Elija el casillero.")
        pago_casillero = DatosPago(casillero.monto, pago.metodo, pago.referencia)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            membresia = self._pagos.membresia_en_sesion(
                sesion, actual, cliente_id, plan_id, fecha_inicio=fecha_inicio,
                precio_pactado=precio_pactado, motivo_descuento=motivo_descuento, pago=pago,
                ahora=ahora,
            )
            numero = membresia.pago.consecutivo
            if casillero.asignacion_id is not None:
                asignacion = self._asignacion_activa_por_id(sesion, casillero.asignacion_id)
                if asignacion.cliente_id != cliente_id:
                    raise ErrorValidacion("Ese casillero no es de este cliente.")
                resultado = self._renovar_en_sesion(
                    sesion, actual, asignacion.id, casillero.fecha_inicio, casillero.dias,
                    pago_casillero, ahora, numero)
            else:
                resultado = self._asignar_en_sesion(
                    sesion, actual, casillero.casillero_id, cliente_id, casillero.fecha_inicio,
                    casillero.dias, pago_casillero, ahora, numero)
            registrar_uso(sesion, actual, admin, "mensualidad y casillero", ahora,
                          recibo=membresia.pago.recibo)
            sesion.commit()
        self._pagos.autorizaciones.gastar(autorizacion)
        return MensualidadConCasillero(membresia, resultado, membresia.pago.recibo,
                                       membresia.pago.id)

    def corregir_vencimiento(
        self, actual: UsuarioActual, asignacion_id: int, vence: date, motivo: str
    ) -> None:
        """Solo admin (p. ej. tras anular un pago de casillero o un error de digitación)."""
        exigir(actual, Permiso.ADMINISTRAR_CATALOGOS)
        motivo = _motivo(motivo)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            asignacion = self._asignacion_activa_por_id(sesion, asignacion_id)
            casillero = self._casillero(sesion, asignacion.casillero_id)
            asignado = asignacion.fecha_asignacion.astimezone(cfg.ZONA_HORARIA).date()
            if vence < asignado - timedelta(days=DIAS_MARGEN_INICIO):
                raise ErrorValidacion("La fecha de vencimiento es demasiado antigua.")
            anterior = asignacion.fecha_vencimiento
            if anterior == vence:
                raise ErrorValidacion("La fecha es igual a la actual.")
            asignacion.fecha_vencimiento = vence
            cliente = sesion.get(Cliente, asignacion.cliente_id)
            auditoria.registrar(
                sesion, "casillero_vencimiento_corregido", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, momento=self._reloj(),
                detalle={"casillero": casillero.numero, "cliente": cliente.codigo,
                         "antes": formato_fecha(anterior) if anterior else "",
                         "despues": formato_fecha(vence), "motivo": motivo},
            )
            sesion.commit()

    def cambiar(
        self, actual: UsuarioActual, asignacion_id: int, nuevo_casillero_id: int
    ) -> AsignacionRegistrada:
        """Pasa al cliente a otro casillero conservando lo que tiene pagado."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        exigir(actual, Permiso.LIBERAR_CASILLERO)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            anterior = self._asignacion_activa_por_id(sesion, asignacion_id)
            viejo = self._casillero(sesion, anterior.casillero_id)
            nuevo = self._casillero(sesion, nuevo_casillero_id)
            if nuevo.id == viejo.id:
                raise ErrorValidacion("Elija un casillero distinto al actual.")
            cliente = self._cliente(sesion, anterior.cliente_id)
            self._validar_asignacion(sesion, nuevo, cliente, cambiando=True)
            anterior.fecha_liberacion = ahora
            anterior.liberado_por = actual.id
            anterior.motivo_liberacion = f"Cambio al casillero {nuevo.numero}"
            viejo.estado = "disponible"
            sesion.flush()  # libera el índice del cliente antes de la nueva asignación
            asignacion = CasilleroAsignacion(
                casillero_id=nuevo.id, cliente_id=cliente.id, fecha_asignacion=ahora,
                fecha_vencimiento=anterior.fecha_vencimiento, asignado_por=actual.id,
            )
            sesion.add(asignacion)
            nuevo.estado = "ocupado"
            try:
                sesion.flush()
            except IntegrityError:
                sesion.rollback()
                raise ErrorValidacion(
                    "El casillero nuevo ya fue asignado. Actualice la lista e intente de nuevo."
                ) from None
            auditoria.registrar(
                sesion, "casillero_trasladado", "casilleros", usuario_id=actual.id,
                entidad_id=nuevo.id, momento=ahora,
                detalle={"cliente": cliente.codigo, "de": viejo.numero, "a": nuevo.numero},
            )
            sesion.commit()
            return AsignacionRegistrada(asignacion.id, nuevo.numero,
                                        asignacion.fecha_vencimiento, None)

    def liberar(self, actual: UsuarioActual, asignacion_id: int, motivo: str) -> None:
        """Cierra la asignación (queda en el historial) y deja el casillero disponible."""
        exigir(actual, Permiso.LIBERAR_CASILLERO)
        motivo = _motivo(motivo)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            asignacion = self._asignacion_activa_por_id(sesion, asignacion_id)
            casillero = self._casillero(sesion, asignacion.casillero_id)
            cliente = sesion.get(Cliente, asignacion.cliente_id)
            asignacion.fecha_liberacion = max(ahora, asignacion.fecha_asignacion)
            asignacion.liberado_por = actual.id
            asignacion.motivo_liberacion = motivo
            if casillero.estado == "ocupado":
                casillero.estado = "disponible"
            auditoria.registrar(
                sesion, "casillero_liberado", "casilleros", usuario_id=actual.id,
                entidad_id=casillero.id, momento=ahora,
                detalle={"casillero": casillero.numero, "cliente": cliente.codigo,
                         "motivo": motivo},
            )
            sesion.commit()

    # --- consultas ------------------------------------------------------------------
    def de_cliente(self, actual: UsuarioActual, cliente_id: int) -> CasilleroCliente | None:
        """Qué casillero tiene un cliente (RF-L3)."""
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            return casillero_de_cliente(sesion, self._configuracion, cliente_id, self.hoy())

    def libres(self, actual: UsuarioActual, sexo: str | None = None) -> list[tuple[int, str, str]]:
        """Casilleros disponibles (id, número, zona); con `sexo`, solo los de su zona."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        with self._fabrica() as sesion:
            ocupados = select(CasilleroAsignacion.casillero_id).where(
                CasilleroAsignacion.fecha_liberacion.is_(None))
            filas = sesion.execute(
                select(Casillero.id, Casillero.numero, Casillero.zona).where(
                    Casillero.estado != "mantenimiento", Casillero.id.not_in(ocupados))
            ).all()
        if sexo is not None:
            filas = [f for f in filas if zona_permitida(f.zona, sexo)]
        return sorted(((f.id, f.numero, f.zona) for f in filas), key=lambda f: _clave_orden(f[1]))

    def listar(
        self, actual: UsuarioActual, filtros: FiltrosCasilleros | None = None
    ) -> list[FilaCasillero]:
        """Todos los casilleros con su ocupante, vencimiento y sugerencias (RF-L5)."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        filtros = filtros or FiltrosCasilleros()
        hoy = self.hoy()
        with self._fabrica() as sesion:
            dias_por_vencer = self._configuracion.obtener("dias_por_vencer", sesion)
            limite = self._configuracion.obtener("casillero_dias_liberar", sesion)
            fin_membresia = (
                select(func.max(Membresia.fecha_fin))
                .where(Membresia.cliente_id == Cliente.id, Membresia.estado == "activa")
                .correlate(Cliente).scalar_subquery()
            )
            telefono = (
                select(Contacto.valor)
                .where(Contacto.cliente_id == Cliente.id, Contacto.tipo == "telefono")
                .order_by(Contacto.principal.desc(), Contacto.id).limit(1)
                .correlate(Cliente).scalar_subquery()
            )
            consulta = (
                select(Casillero, CasilleroAsignacion, Cliente,
                       fin_membresia.label("fin"), telefono.label("telefono"))
                .outerjoin(CasilleroAsignacion, and_(
                    CasilleroAsignacion.casillero_id == Casillero.id,
                    CasilleroAsignacion.fecha_liberacion.is_(None)))
                .outerjoin(Cliente, Cliente.id == CasilleroAsignacion.cliente_id)
            )
            if filtros.zona:
                consulta = consulta.where(Casillero.zona == filtros.zona)
            filas_bd = sesion.execute(consulta).all()

        texto = " ".join(filtros.texto.split()).upper()
        resultado: list[FilaCasillero] = []
        for casillero, asignacion, cliente, fin, tel in filas_bd:
            fila = self._fila(casillero, asignacion, cliente, fin, tel, hoy, dias_por_vencer,
                              limite)
            if not self._cumple(fila, filtros, texto):
                continue
            resultado.append(fila)
        resultado.sort(key=lambda f: _clave_orden(f.numero))
        if filtros.situacion in ("vencidos", "sugerido_liberar"):
            resultado.sort(key=lambda f: -f.dias_vencido)  # los más atrasados primero
        elif filtros.situacion == "membresia_vencida":
            # Sin membresía primero; luego los que vencieron hace más tiempo.
            resultado.sort(key=lambda f: f.dias_membresia if f.dias_membresia is not None
                           else -10**6)
        return resultado

    def resumen(self, actual: UsuarioActual) -> ResumenCasilleros:
        filas = self.listar(actual)
        por_zona: dict[str, tuple[int, int]] = {}
        for f in filas:
            total, ocupados = por_zona.get(f.zona, (0, 0))
            por_zona[f.zona] = (total + 1, ocupados + (1 if f.ocupado else 0))
        return ResumenCasilleros(
            total=len(filas),
            disponibles=sum(1 for f in filas if f.estado == "disponible"),
            ocupados=sum(1 for f in filas if f.ocupado),
            mantenimiento=sum(1 for f in filas if f.estado == "mantenimiento"),
            vencidos=sum(1 for f in filas if f.vigencia == VigenciaCasillero.VENCIDO),
            sugeridos=sum(1 for f in filas if f.sugerir_liberar),
            por_zona=por_zona,
        )

    def historial(self, actual: UsuarioActual, casillero_id: int) -> list[FilaHistorial]:
        """De quién ha sido un casillero, lo más reciente primero."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        with self._fabrica() as sesion:
            self._casillero(sesion, casillero_id)
            return self._historial(sesion, CasilleroAsignacion.casillero_id == casillero_id)

    def movimientos(self, actual: UsuarioActual, dia: date) -> list[Movimiento]:
        """Casilleros asignados o liberados en un día (hora de Bogotá)."""
        exigir(actual, Permiso.ASIGNAR_CASILLERO)
        desde, hasta = inicio_dia_utc(dia), inicio_dia_utc(dia + timedelta(days=1))
        with self._fabrica() as sesion:
            usuarios = dict(sesion.execute(select(Usuario.id, Usuario.usuario)).all())
            filas = sesion.execute(
                select(CasilleroAsignacion, Casillero, Cliente)
                .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
                .join(Cliente, Cliente.id == CasilleroAsignacion.cliente_id)
                .where(or_(
                    and_(CasilleroAsignacion.fecha_asignacion >= desde,
                         CasilleroAsignacion.fecha_asignacion < hasta),
                    and_(CasilleroAsignacion.fecha_liberacion >= desde,
                         CasilleroAsignacion.fecha_liberacion < hasta),
                ))
            ).all()
        movimientos: list[Movimiento] = []
        for a, c, cli in filas:
            nombre = f"{cli.nombres} {cli.apellidos}"
            if desde <= a.fecha_asignacion < hasta:
                movimientos.append(Movimiento(
                    a.fecha_asignacion, "Asignado", c.numero, c.zona, cli.codigo, nombre,
                    cli.sexo, usuarios.get(a.asignado_por, "—"), a.fecha_vencimiento, ""))
            if a.fecha_liberacion is not None and desde <= a.fecha_liberacion < hasta:
                movimientos.append(Movimiento(
                    a.fecha_liberacion, "Liberado", c.numero, c.zona, cli.codigo, nombre,
                    cli.sexo, usuarios.get(a.liberado_por, "—"), a.fecha_vencimiento,
                    a.motivo_liberacion or ""))
        movimientos.sort(key=lambda m: m.fecha_hora)
        return movimientos

    # --- listas para exportar ---------------------------------------------------------
    def listado(
        self, actual: UsuarioActual, tipo: str, filtros: FiltrosCasilleros | None = None,
        dia: date | None = None,
    ) -> Listado:
        """`tipo`: "estado" (lista con filtros) o "dia" (movimientos de una fecha)."""
        exigir(actual, Permiso.REPORTES_BASICOS)
        generado = f"Generado el {self._reloj().astimezone(cfg.ZONA_HORARIA):%d/%m/%Y %H:%M}"
        nombre = self._configuracion.obtener("gimnasio_nombre") or "Enforma"
        if tipo == "dia":
            dia = dia or self.hoy()
            movs = self.movimientos(actual, dia)
            filas = [
                (m.fecha_hora.astimezone(cfg.ZONA_HORARIA).strftime("%H:%M"), m.tipo, m.numero,
                 ZONAS.get(m.zona, m.zona), m.codigo, m.cliente, SEXOS.get(m.sexo, m.sexo),
                 m.vence, m.motivo, m.usuario)
                for m in movs
            ]
            asignados = sum(1 for m in movs if m.tipo == "Asignado")
            return Listado(
                f"Casilleros del día {formato_fecha(dia)}",
                f"{nombre} · {asignados} asignados · {len(movs) - asignados} liberados · {generado}",
                ("Hora", "Movimiento", "Casillero", "Zona", "Código", "Cliente", "Sexo",
                 "Pagado hasta", "Motivo", "Usuario"),
                filas,
            )
        if tipo != "estado":
            raise ErrorValidacion("Tipo de lista no válido.")
        filtros = filtros or FiltrosCasilleros()
        lista = self.listar(actual, filtros)
        filas = [
            (f.numero, ZONAS.get(f.zona, f.zona), ESTADOS.get(f.estado, f.estado), f.codigo,
             f.cliente, SEXOS.get(f.sexo, "") if f.sexo else "", f.telefono,
             f.vence, NOMBRES_VIGENCIA_CASILLERO[f.vigencia] if f.vigencia else "",
             f.dias_vencido or "",
             NOMBRES_VIGENCIA[f.vigencia_membresia] if f.vigencia_membresia else "",
             f.motivo_sugerencia, f.notas)
            for f in lista
        ]
        partes = [f"{len(lista)} casilleros"]
        if filtros.estado:
            partes.append(ESTADOS[filtros.estado].lower())
        if filtros.zona:
            partes.append(f"zona {ZONAS[filtros.zona].lower()}")
        if filtros.sexo_cliente:
            partes.append(f"ocupados por sexo {SEXOS[filtros.sexo_cliente].lower()}")
        if filtros.situacion:
            partes.append(SITUACIONES[filtros.situacion].lower())
        titulo = ("Casilleros vencidos" if filtros.situacion == "vencidos"
                  else "Casilleros sugeridos para liberar" if filtros.situacion == "sugerido_liberar"
                  else "Casilleros")
        return Listado(
            titulo, f"{nombre} · {' · '.join(partes)} · {generado}",
            ("Casillero", "Zona", "Estado", "Código", "Cliente", "Sexo", "Teléfono",
             "Pagado hasta", "Casillero", "Días vencido", "Membresía", "Sugerencia", "Notas"),
            filas,
        )

    def exportar(
        self, actual: UsuarioActual, tipo: str, ruta: Path | str, formato: str,
        filtros: FiltrosCasilleros | None = None, dia: date | None = None,
    ) -> Path:
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        lista = self.listado(actual, tipo, filtros, dia)
        if formato == "xlsx":
            ruta = exp.exportar_excel(ruta, lista.titulo, lista.encabezados, lista.filas)
        else:
            ruta = exp.exportar_pdf(ruta, lista.titulo, lista.subtitulo, lista.encabezados,
                                    lista.filas)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "casilleros_exportados", "casilleros", usuario_id=actual.id,
                momento=self._reloj(),
                detalle={"lista": tipo, "formato": formato, "filas": len(lista.filas)},
            )
            sesion.commit()
        return Path(ruta)

    def carpeta_reportes(self) -> Path:
        carpeta = (self._carpeta or cfg.carpeta_datos()) / "reportes"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    # --- apoyo ----------------------------------------------------------------------
    @staticmethod
    def _fila(casillero, asignacion, cliente, fin, telefono, hoy, dias_por_vencer,
              limite) -> FilaCasillero:
        base = dict(casillero_id=casillero.id, numero=casillero.numero, zona=casillero.zona,
                    estado=casillero.estado, notas=casillero.notas or "")
        if asignacion is None:
            return FilaCasillero(**base)
        vigencia, dias = calcular_vigencia_casillero(
            asignacion.fecha_vencimiento, hoy, dias_por_vencer)
        vig_m, dias_m = calcular_vigencia(fin, hoy, dias_por_vencer)
        sugerir, motivo = sugerencia(cliente.estado, vigencia, dias, limite)
        return FilaCasillero(
            **base, asignacion_id=asignacion.id, cliente_id=cliente.id, codigo=cliente.codigo,
            cliente=f"{cliente.nombres} {cliente.apellidos}", sexo=cliente.sexo,
            cliente_activo=cliente.estado == "activo", telefono=telefono or "",
            asignado_en=asignacion.fecha_asignacion, vence=asignacion.fecha_vencimiento,
            vigencia=vigencia, dias=dias, vigencia_membresia=vig_m, dias_membresia=dias_m,
            sugerir_liberar=sugerir, motivo_sugerencia=motivo,
        )

    @staticmethod
    def _cumple(f: FilaCasillero, filtros: FiltrosCasilleros, texto: str) -> bool:
        if filtros.estado == "ocupado" and not f.ocupado:
            return False
        if filtros.estado in ("disponible", "mantenimiento") and (
                f.ocupado or f.estado != filtros.estado):
            return False
        if filtros.sexo_cliente and f.sexo != filtros.sexo_cliente:
            return False
        s = filtros.situacion
        if s == "vencidos" and f.vigencia != VigenciaCasillero.VENCIDO:
            return False
        if s == "por_vencer" and f.vigencia != VigenciaCasillero.POR_VENCER:
            return False
        if s == "membresia_vencida" and f.vigencia_membresia not in (
                Vigencia.VENCIDA, Vigencia.SIN_MEMBRESIA):
            return False
        if s == "membresia_vencida" and not f.ocupado:
            return False
        if s == "sugerido_liberar" and not f.sugerir_liberar:
            return False
        if s == "fuera_de_zona" and not f.fuera_de_zona:
            return False
        if texto:
            numero = f.numero.lstrip("0") or "0"
            buscado = texto.lstrip("0") or "0"
            if not (numero == buscado or f.numero == texto or texto == f.codigo
                    or (f.cliente and texto in f.cliente.upper())):
                return False
        return True

    def _historial(self, sesion: Session, condicion) -> list[FilaHistorial]:
        usuarios = dict(sesion.execute(select(Usuario.id, Usuario.usuario)).all())
        filas = sesion.execute(
            select(CasilleroAsignacion, Casillero, Cliente)
            .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
            .join(Cliente, Cliente.id == CasilleroAsignacion.cliente_id)
            .where(condicion)
            .order_by(CasilleroAsignacion.fecha_asignacion.desc(), CasilleroAsignacion.id.desc())
        ).all()
        return [
            FilaHistorial(
                a.id, c.numero, c.zona, cli.id, cli.codigo, f"{cli.nombres} {cli.apellidos}",
                a.fecha_asignacion, usuarios.get(a.asignado_por, "—"), a.fecha_vencimiento,
                a.fecha_liberacion, usuarios.get(a.liberado_por, "") if a.liberado_por else "",
                a.motivo_liberacion or "",
            )
            for a, c, cli in filas
        ]

    def _periodo(
        self, sesion: Session, inicio: date | None, dias: int | None, renovacion: bool = False
    ) -> tuple[date, int]:
        hoy = self.hoy()
        inicio = inicio or hoy
        if dias is None:
            dias = self._configuracion.obtener("casillero_dias", sesion)
        try:
            dias = int(dias)
        except (TypeError, ValueError):
            raise ErrorValidacion("Los días deben ser un número entero.") from None
        if not 1 <= dias <= DIAS_MAXIMOS:
            raise ErrorValidacion(f"Los días deben estar entre 1 y {DIAS_MAXIMOS}.")
        # Al renovar por adelantado el inicio puede quedar más lejos (después del vencimiento).
        margen_futuro = DIAS_MARGEN_INICIO + (DIAS_MAXIMOS if renovacion else 0)
        if not hoy - timedelta(days=DIAS_MARGEN_INICIO) <= inicio <= hoy + timedelta(
                days=margen_futuro):
            raise ErrorValidacion(
                f"La fecha de inicio debe estar a menos de {DIAS_MARGEN_INICIO} días de hoy.")
        return inicio, dias

    def _validar_asignacion(
        self, sesion: Session, casillero: Casillero, cliente: Cliente, cambiando: bool = False
    ) -> None:
        if cliente.estado != "activo":
            raise ErrorValidacion("El cliente está inactivo: no se le puede asignar casillero.")
        if casillero.estado == "mantenimiento":
            raise ErrorValidacion(f"El casillero {casillero.numero} está en mantenimiento.")
        ocupante = self._ocupante(sesion, casillero.id)
        if ocupante is not None:
            raise ErrorValidacion(
                f"El casillero {casillero.numero} ya está asignado a {ocupante.nombres} "
                f"{ocupante.apellidos} (código {ocupante.codigo})."
            )
        if not cambiando:
            actual = casillero_activo_numero(sesion, cliente.id)
            if actual is not None:
                raise ErrorValidacion(
                    f"El cliente ya tiene el casillero {actual}. Use «Cambiar de casillero» "
                    "o libérelo primero."
                )
        if not zona_permitida(casillero.zona, cliente.sexo):
            raise ErrorValidacion(
                f"El casillero {casillero.numero} es de la zona "
                f"{ZONAS[casillero.zona].lower()} y el cliente es de sexo "
                f"{SEXOS.get(cliente.sexo, cliente.sexo).lower()}. Elija un casillero de su "
                "zona o uno mixto."
            )

    @staticmethod
    def _ocupante(sesion: Session, casillero_id: int) -> Cliente | None:
        return sesion.scalar(
            select(Cliente)
            .join(CasilleroAsignacion, CasilleroAsignacion.cliente_id == Cliente.id)
            .where(CasilleroAsignacion.casillero_id == casillero_id,
                   CasilleroAsignacion.fecha_liberacion.is_(None))
        )

    @staticmethod
    def _asignacion_activa_por_id(sesion: Session, asignacion_id: int) -> CasilleroAsignacion:
        asignacion = sesion.get(CasilleroAsignacion, asignacion_id)
        if asignacion is None:
            raise ErrorValidacion("La asignación de casillero no existe.")
        if asignacion.fecha_liberacion is not None:
            raise ErrorValidacion("Ese casillero ya fue liberado. Actualice la lista.")
        return asignacion

    @staticmethod
    def _casillero(sesion: Session, casillero_id: int) -> Casillero:
        casillero = sesion.get(Casillero, casillero_id)
        if casillero is None:
            raise ErrorValidacion("El casillero no existe.")
        return casillero

    @staticmethod
    def _cliente(sesion: Session, cliente_id: int) -> Cliente:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise ErrorValidacion("El cliente no existe.")
        return cliente

    @staticmethod
    def _zona(zona: str) -> str:
        if zona not in ZONAS:
            raise ErrorValidacion("Elija la zona: hombres, mujeres o mixto.")
        return zona

    @staticmethod
    def _notas(notas: str) -> str:
        notas = " ".join((notas or "").split())
        if len(notas) > 200:
            raise ErrorValidacion("Las notas admiten máximo 200 caracteres.")
        return notas

    @staticmethod
    def _exigir_numero_libre(sesion: Session, numero: str, excepto_id: int | None = None) -> None:
        consulta = select(Casillero.id).where(Casillero.numero == numero)
        if excepto_id is not None:
            consulta = consulta.where(Casillero.id != excepto_id)
        if sesion.scalar(consulta) is not None:
            raise ErrorValidacion(f"Ya existe el casillero {numero}.")


# --- funciones compartidas con Clientes y Recepción ----------------------------------------

def sugerencia(estado_cliente: str, vigencia: VigenciaCasillero, dias: int | None,
               limite: int) -> tuple[bool, str]:
    """¿Conviene liberar? Cliente inactivo, o casillero vencido hace más de `limite` días."""
    if estado_cliente != "activo":
        return True, "Cliente inactivo"
    if vigencia == VigenciaCasillero.VENCIDO and dias is not None and -dias > limite:
        return True, f"Vencido hace {_texto_dias(-dias)}"
    return False, ""


def casillero_activo_numero(sesion: Session, cliente_id: int) -> str | None:
    return sesion.scalar(
        select(Casillero.numero)
        .join(CasilleroAsignacion, CasilleroAsignacion.casillero_id == Casillero.id)
        .where(CasilleroAsignacion.cliente_id == cliente_id,
               CasilleroAsignacion.fecha_liberacion.is_(None))
    )


def casillero_de_cliente(
    sesion: Session, configuracion: ServicioConfiguracion, cliente_id: int, hoy: date
) -> CasilleroCliente | None:
    fila = sesion.execute(
        select(CasilleroAsignacion, Casillero, Cliente.estado)
        .join(Casillero, Casillero.id == CasilleroAsignacion.casillero_id)
        .join(Cliente, Cliente.id == CasilleroAsignacion.cliente_id)
        .where(CasilleroAsignacion.cliente_id == cliente_id,
               CasilleroAsignacion.fecha_liberacion.is_(None))
    ).first()
    if fila is None:
        return None
    asignacion, casillero, estado = fila
    vigencia, dias = calcular_vigencia_casillero(
        asignacion.fecha_vencimiento, hoy, configuracion.obtener("dias_por_vencer", sesion))
    sugerir, _ = sugerencia(estado, vigencia, dias,
                            configuracion.obtener("casillero_dias_liberar", sesion))
    return CasilleroCliente(
        asignacion.id, casillero.id, casillero.numero, casillero.zona,
        asignacion.fecha_asignacion, asignacion.fecha_vencimiento, vigencia, dias, sugerir,
    )
