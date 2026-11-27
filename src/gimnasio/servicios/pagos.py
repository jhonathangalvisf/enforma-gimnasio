"""Membresías, pagos, saldos, anulaciones, recibos y cierre de caja (sección 3.3).

Reglas:
- RN-03: fecha_fin = fecha_inicio + duracion_dias - 1 (el último día se puede entrar).
- RN-04: si el cliente sigue vigente, la renovación inicia el día siguiente a su
  fecha de fin (o hoy, según la configuración). Si ya venció, inicia hoy o en la
  fecha que se elija.
- Precio distinto al del plan (descuento) solo lo pone el administrador, con motivo.
- Se aceptan abonos: el saldo de una membresía es su precio pactado menos los pagos
  no anulados. Ningún pago puede superar el saldo.
- Nada financiero se borra (RN-07): pagos y membresías se anulan con motivo (solo
  el administrador). Anular una membresía anula también sus pagos.
- Cada recibo recibe un consecutivo que nunca se repite. Si el cliente paga la
  mensualidad y el casillero juntos, los dos pagos comparten el número: un solo
  recibo con los dos conceptos (migración 0008).
- Cierre de caja: Recepción ve el suyo del día; el administrador, el de cualquier
  usuario y fecha. Los pagos anulados no suman, pero se listan con su motivo.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.formato import pesos as _pesos
from gimnasio.modelos import (
    Casillero, CasilleroAsignacion, Cliente, Config, Membresia, Pago, Plan, Usuario, ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.auditoria import inicio_dia_utc
from gimnasio.servicios.autorizaciones import (
    PARA_INSCRIPCION, PARA_MODULO_PAGOS, PARA_PAGO, Autorizacion, ServicioAutorizaciones,
    registrar_uso,
)
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente

METODOS = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}
CONCEPTOS = {"membresia": "Membresía", "casillero": "Casillero", "otro": "Otro"}
MONTO_MAXIMO = 99_999_999
# Recepción puede registrar una membresía que empezó hace pocos días (p. ej. si
# pagó tarde); más atrás solo el administrador.
DIAS_ATRAS_RECEPCION = 30
DIAS_ADELANTE_MAXIMO = 90


def calcular_fecha_fin(fecha_inicio: date, duracion_dias: int) -> date:
    """RN-03: el último día incluido. Un plan de 30 días que inicia el 01/11 vence el 30/11."""
    if duracion_dias < 1:
        raise ErrorValidacion("La duración del plan debe ser de al menos 1 día.")
    return fecha_inicio + timedelta(days=duracion_dias - 1)


def calcular_inicio_renovacion(
    fin_actual: date | None, hoy: date, politica: str = "dia_siguiente"
) -> date:
    """RN-04: fecha de inicio sugerida para una membresía nueva.

    `fin_actual` es la fecha de fin de la última membresía no anulada (None si no tiene).
    """
    if fin_actual is not None and fin_actual >= hoy and politica == "dia_siguiente":
        return fin_actual + timedelta(days=1)
    return hoy


def numero_recibo(prefijo: str, consecutivo: int) -> str:
    return f"{prefijo}{consecutivo:06d}"


def saldos_por_membresia(sesion: Session, ids: list[int]) -> dict[int, int]:
    """Total pagado (pagos no anulados) de cada membresía."""
    if not ids:
        return {}
    filas = sesion.execute(
        select(Pago.membresia_id, func.sum(Pago.monto))
        .where(Pago.membresia_id.in_(ids), Pago.anulado.is_(False))
        .group_by(Pago.membresia_id)
    ).all()
    return {mid: int(total or 0) for mid, total in filas}


def saldo_pendiente_cliente(sesion: Session, cliente_id: int) -> int:
    """Suma de lo que falta por pagar en las membresías activas del cliente."""
    membresias = sesion.execute(
        select(Membresia.id, Membresia.precio_pactado)
        .where(Membresia.cliente_id == cliente_id, Membresia.estado == "activa")
    ).all()
    pagado = saldos_por_membresia(sesion, [m.id for m in membresias])
    return sum(max(0, m.precio_pactado - pagado.get(m.id, 0)) for m in membresias)


# --- datos de entrada y salida ---------------------------------------------------

@dataclass(frozen=True)
class DatosPago:
    monto: int
    metodo: str = "efectivo"
    referencia: str = ""


@dataclass(frozen=True)
class PagoRegistrado:
    id: int
    consecutivo: int
    recibo: str  # número con prefijo, p. ej. "R-000123"
    monto: int
    saldo_despues: int | None  # saldo de la membresía después de este pago


@dataclass(frozen=True)
class MembresiaRegistrada:
    id: int
    plan: str
    fecha_inicio: date
    fecha_fin: date
    precio_pactado: int
    saldo: int
    pago: PagoRegistrado | None


@dataclass(frozen=True)
class PropuestaMembresia:
    """Lo que la pantalla de renovación muestra precargado."""

    plan_id: int | None
    fecha_inicio: date
    fecha_fin: date | None
    precio: int | None
    fin_actual: date | None  # vence la membresía vigente (None si no tiene)
    saldo_pendiente: int
    cliente_activo: bool


@dataclass(frozen=True)
class FilaCaja:
    pago_id: int
    recibo: str
    fecha_hora: datetime  # UTC
    cliente_codigo: str
    cliente_nombre: str
    concepto: str
    metodo: str
    referencia: str
    monto: int
    usuario_id: int
    usuario: str
    anulado: bool
    motivo_anulacion: str


@dataclass(frozen=True)
class TotalUsuario:
    usuario_id: int
    usuario: str
    por_metodo: dict[str, int]
    total: int
    cantidad: int


@dataclass(frozen=True)
class CierreCaja:
    dia: date
    usuario_id: int | None  # None = todos
    filas: list[FilaCaja]
    por_metodo: dict[str, int]
    por_usuario: list[TotalUsuario]
    total: int
    cantidad: int
    anulados_cantidad: int
    anulados_monto: int


@dataclass(frozen=True)
class LineaRecibo:
    """Un concepto de un recibo con varios (mensualidad + casillero)."""

    concepto: str
    detalle: str
    monto: int
    anulado: bool = False


@dataclass(frozen=True)
class DatosRecibo:
    recibo: str
    fecha_hora: datetime  # UTC
    gimnasio_nombre: str
    gimnasio_nit: str
    gimnasio_direccion: str
    gimnasio_telefono: str
    logo: Path | None
    cliente_codigo: str
    cliente_nombre: str
    cliente_documento: str
    concepto: str
    detalle: str
    metodo: str
    referencia: str
    monto: int
    precio_membresia: int | None
    saldo_despues: int | None
    usuario: str
    anulado: bool
    motivo_anulacion: str
    lineas_extra: list[str] = field(default_factory=list)
    # Pagos de membresía: período que cubre (la nueva vigencia del cliente).
    vigencia_desde: date | None = None
    vigencia_hasta: date | None = None
    # Otros pagos: hasta qué día está al día el cliente (no cambia con este pago).
    vigente_hasta: date | None = None
    # Solo si el recibo tiene más de un concepto; `monto` es entonces el total.
    lineas: list[LineaRecibo] = field(default_factory=list)


def _motivo(texto: str, que: str) -> str:
    texto = " ".join((texto or "").split())
    if len(texto) < 3:
        raise ErrorValidacion(f"Escriba el motivo {que}.")
    if len(texto) > 200:
        raise ErrorValidacion("El motivo admite máximo 200 caracteres.")
    return texto


def _validar_pago(datos: DatosPago) -> DatosPago:
    try:
        monto = int(datos.monto)
    except (TypeError, ValueError):
        raise ErrorValidacion("El monto debe ser un número entero de pesos.") from None
    if monto <= 0:
        raise ErrorValidacion("El monto debe ser mayor que cero.")
    if monto > MONTO_MAXIMO:
        raise ErrorValidacion("El monto no es válido.")
    if datos.metodo not in METODOS:
        raise ErrorValidacion("Elija el método de pago: efectivo, tarjeta o transferencia.")
    referencia = " ".join((datos.referencia or "").split())
    if datos.metodo != "efectivo" and not referencia:
        raise ErrorValidacion(
            f"Escriba la referencia del pago con {METODOS[datos.metodo].lower()} "
            "(número de aprobación o de transacción)."
        )
    if len(referencia) > 60:
        raise ErrorValidacion("La referencia admite máximo 60 caracteres.")
    return DatosPago(monto, datos.metodo, referencia)


# --- consultas de pagos (por cliente y por fecha de pago) ----------------------------

LIMITE_CONSULTA = 5000


@dataclass(frozen=True)
class FiltrosPagos:
    """Fechas en días de Bogotá, incluidas. None = sin límite por ese lado."""

    cliente_id: int | None = None
    desde: date | None = None
    hasta: date | None = None
    metodo: str | None = None
    concepto: str | None = None
    usuario_id: int | None = None
    incluir_anulados: bool = True


@dataclass(frozen=True)
class FilaConsultaPago:
    pago_id: int
    recibo: str
    fecha_hora: datetime  # UTC
    cliente_codigo: str
    cliente_nombre: str
    concepto: str
    detalle: str  # plan y período de la membresía, si aplica
    metodo: str
    referencia: str
    monto: int
    usuario: str
    anulado: bool
    motivo_anulacion: str


@dataclass(frozen=True)
class ConsultaPagos:
    filas: list[FilaConsultaPago]
    total: int  # solo pagos válidos
    cantidad: int
    anulados_cantidad: int
    anulados_monto: int
    truncada: bool  # hay más pagos que el límite mostrado


ENCABEZADOS_CONSULTA = ("Fecha y hora", "Recibo", "Código", "Cliente", "Concepto", "Detalle",
                        "Método", "Referencia", "Registró", "Estado", "Monto")


def filas_exportables(consulta: ConsultaPagos) -> list[tuple]:
    from gimnasio.formato import fecha_hora_local

    return [
        (fecha_hora_local(f.fecha_hora), f.recibo, f.cliente_codigo, f.cliente_nombre,
         CONCEPTOS[f.concepto], f.detalle, METODOS[f.metodo], f.referencia, f.usuario,
         f"Anulado: {f.motivo_anulacion}" if f.anulado else "Válido",
         0 if f.anulado else f.monto)
        for f in consulta.filas
    ]


# --- servicio -------------------------------------------------------------------------

class ServicioPagos:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
        *,
        autorizaciones: ServicioAutorizaciones,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._carpeta = carpeta_datos
        self._reloj = reloj
        self.autorizaciones = autorizaciones

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    # --- membresías -----------------------------------------------------------------
    def proponer_membresia(
        self, actual: UsuarioActual, cliente_id: int, plan_id: int | None = None
    ) -> PropuestaMembresia:
        """Renovación rápida: el último plan del cliente (si sigue activo), la fecha de
        inicio según RN-04, la fecha de fin y el precio del plan."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        with self._fabrica() as sesion:
            cliente = self._cliente(sesion, cliente_id)
            ultima = self._ultima_membresia(sesion, cliente.id)
            fin_actual = ultima.fecha_fin if ultima else None
            if plan_id is None and ultima is not None:
                plan_ultimo = sesion.get(Plan, ultima.plan_id)
                if plan_ultimo and plan_ultimo.activo:
                    plan_id = plan_ultimo.id
            plan = sesion.get(Plan, plan_id) if plan_id else None
            inicio = calcular_inicio_renovacion(
                fin_actual, self.hoy(), self._configuracion.obtener("renovacion_anticipada", sesion)
            )
            return PropuestaMembresia(
                plan_id=plan.id if plan else None,
                fecha_inicio=inicio,
                fecha_fin=calcular_fecha_fin(inicio, plan.duracion_dias) if plan else None,
                precio=plan.precio if plan else None,
                fin_actual=fin_actual if fin_actual and fin_actual >= self.hoy() else None,
                saldo_pendiente=saldo_pendiente_cliente(sesion, cliente.id),
                cliente_activo=cliente.estado == "activo",
            )

    def registrar_membresia(
        self,
        actual: UsuarioActual,
        cliente_id: int,
        plan_id: int,
        *,
        fecha_inicio: date | None = None,
        precio_pactado: int | None = None,
        motivo_descuento: str = "",
        pago: DatosPago | None = None,
        autorizacion: Autorizacion | None = None,
    ) -> MembresiaRegistrada:
        """Registra la membresía y, si se indica, su primer pago (completo o abono).
        Recepción necesita la autorización de un administrador (pago o inscripción)."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        admin = self.autorizaciones.verificar(actual, autorizacion, PARA_PAGO, PARA_INSCRIPCION)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            registrada = self.membresia_en_sesion(
                sesion, actual, cliente_id, plan_id, fecha_inicio=fecha_inicio,
                precio_pactado=precio_pactado, motivo_descuento=motivo_descuento, pago=pago,
                ahora=ahora,
            )
            registrar_uso(sesion, actual, admin, "membresía", ahora, membresia=registrada.id,
                          recibo=registrada.pago.recibo if registrada.pago else None)
            sesion.commit()
        self.autorizaciones.gastar(autorizacion)
        return registrada

    def membresia_en_sesion(
        self, sesion: Session, actual: UsuarioActual, cliente_id: int, plan_id: int, *,
        fecha_inicio: date | None, precio_pactado: int | None, motivo_descuento: str,
        pago: DatosPago | None, ahora: datetime,
    ) -> MembresiaRegistrada:
        """Membresía (y su pago) dentro de una transacción abierta, sin confirmarla.
        La usa también el cobro de mensualidad + casillero en un solo recibo."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        if pago is not None:
            pago = _validar_pago(pago)
        hoy = self.hoy()
        cliente = self._cliente(sesion, cliente_id)
        if cliente.estado != "activo":
            raise ErrorValidacion(
                "El cliente está inactivo. El administrador debe activarlo antes de "
                "registrarle una membresía."
            )
        plan = sesion.get(Plan, plan_id)
        if plan is None:
            raise ErrorValidacion("Elija un plan.")
        if not plan.activo:
            raise ErrorValidacion(f"El plan «{plan.nombre}» está desactivado.")

        # Precio: el del plan, salvo descuento del administrador con motivo.
        if precio_pactado is None:
            precio_pactado = plan.precio
        try:
            precio_pactado = int(precio_pactado)
        except (TypeError, ValueError):
            raise ErrorValidacion("El precio debe ser un número entero de pesos.") from None
        if not 0 <= precio_pactado <= MONTO_MAXIMO:
            raise ErrorValidacion("El precio no es válido.")
        motivo = None
        if precio_pactado != plan.precio:
            if not actual.puede(Permiso.APLICAR_DESCUENTOS):
                raise ErrorPermiso(
                    "Solo el administrador puede cambiar el precio del plan (descuento)."
                )
            motivo = _motivo(motivo_descuento, "del descuento o del cambio de precio")

        # Fechas (RN-03 y RN-04).
        ultima = self._ultima_membresia(sesion, cliente.id)
        politica = self._configuracion.obtener("renovacion_anticipada", sesion)
        sugerida = calcular_inicio_renovacion(ultima.fecha_fin if ultima else None, hoy, politica)
        if fecha_inicio is None:
            fecha_inicio = sugerida
        if fecha_inicio > hoy + timedelta(days=DIAS_ADELANTE_MAXIMO):
            raise ErrorValidacion(
                f"La fecha de inicio no puede ser más de {DIAS_ADELANTE_MAXIMO} días después de hoy."
            )
        if (fecha_inicio < hoy - timedelta(days=DIAS_ATRAS_RECEPCION)
                and not actual.puede(Permiso.APLICAR_DESCUENTOS)):
            raise ErrorPermiso(
                f"Solo el administrador puede registrar una membresía que inició hace más "
                f"de {DIAS_ATRAS_RECEPCION} días."
            )
        fecha_fin = calcular_fecha_fin(fecha_inicio, plan.duracion_dias)
        if politica == "dia_siguiente":
            cruce = sesion.scalars(
                select(Membresia).where(
                    Membresia.cliente_id == cliente.id, Membresia.estado == "activa",
                    Membresia.fecha_inicio <= fecha_fin, Membresia.fecha_fin >= fecha_inicio,
                ).order_by(Membresia.fecha_fin.desc())
            ).first()
            if cruce is not None:
                raise ErrorValidacion(
                    f"Las fechas se cruzan con la membresía del {formato_fecha(cruce.fecha_inicio)} "
                    f"al {formato_fecha(cruce.fecha_fin)}. La nueva puede iniciar el "
                    f"{formato_fecha(cruce.fecha_fin + timedelta(days=1))}."
                )

        if pago is not None and pago.monto > precio_pactado:
            raise ErrorValidacion(
                "El pago no puede ser mayor que el precio de la membresía."
            )

        membresia = Membresia(
            cliente_id=cliente.id, plan_id=plan.id, fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin, precio_pactado=precio_pactado, estado="activa",
            motivo_descuento=motivo, creado_por=actual.id, creado_en=ahora,
        )
        sesion.add(membresia)
        sesion.flush()
        detalle = {
            "cliente": cliente.codigo, "plan": plan.nombre,
            "inicio": formato_fecha(fecha_inicio), "fin": formato_fecha(fecha_fin),
            "precio_pactado": precio_pactado,
        }
        if motivo:
            detalle.update(precio_plan=plan.precio, motivo_descuento=motivo)
        auditoria.registrar(
            sesion, "membresia_registrada", "membresias", usuario_id=actual.id,
            entidad_id=membresia.id, detalle=detalle, momento=ahora,
        )
        registrado = None
        if pago is not None:
            registrado = self._crear_pago(
                sesion, actual, cliente, pago, "membresia", membresia, 0, ahora
            )
        return MembresiaRegistrada(
            id=membresia.id, plan=plan.nombre, fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin, precio_pactado=precio_pactado,
            saldo=precio_pactado - (pago.monto if pago else 0), pago=registrado,
        )

    def anular_membresia(self, actual: UsuarioActual, membresia_id: int, motivo: str) -> int:
        """Solo admin. Anula también los pagos válidos de la membresía (mismo motivo).
        Devuelve cuántos pagos se anularon."""
        exigir(actual, Permiso.ANULAR_PAGOS)
        motivo = _motivo(motivo, "de la anulación")
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            membresia = sesion.get(Membresia, membresia_id)
            if membresia is None:
                raise ErrorValidacion("La membresía no existe.")
            if membresia.estado == "anulada":
                raise ErrorValidacion("La membresía ya está anulada.")
            membresia.estado = "anulada"
            membresia.motivo_anulacion = motivo
            membresia.anulada_por = actual.id
            membresia.anulada_en = ahora
            pagos = list(sesion.scalars(
                select(Pago).where(Pago.membresia_id == membresia.id, Pago.anulado.is_(False))
            ))
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
            for p in pagos:
                self._marcar_anulado(p, actual, f"Membresía anulada: {motivo}"[:200], ahora)
                auditoria.registrar(
                    sesion, "pago_anulado", "pagos", usuario_id=actual.id, entidad_id=p.id,
                    momento=ahora,
                    detalle={"recibo": numero_recibo(prefijo, p.consecutivo), "monto": p.monto,
                             "motivo": p.motivo_anulacion},
                )
            cliente = sesion.get(Cliente, membresia.cliente_id)
            auditoria.registrar(
                sesion, "membresia_anulada", "membresias", usuario_id=actual.id,
                entidad_id=membresia.id, momento=ahora,
                detalle={"cliente": cliente.codigo, "inicio": formato_fecha(membresia.fecha_inicio),
                         "fin": formato_fecha(membresia.fecha_fin), "motivo": motivo,
                         "pagos_anulados": len(pagos)},
            )
            sesion.commit()
            return len(pagos)

    # --- pagos ------------------------------------------------------------------------
    def registrar_pago(
        self,
        actual: UsuarioActual,
        cliente_id: int,
        datos: DatosPago,
        *,
        concepto: str = "membresia",
        membresia_id: int | None = None,
        autorizacion: Autorizacion | None = None,
    ) -> PagoRegistrado:
        """Pago suelto: abono a una membresía, casillero u otro concepto.
        Recepción necesita la autorización de un administrador."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        admin = self.autorizaciones.verificar(actual, autorizacion, PARA_PAGO)
        datos = _validar_pago(datos)
        if concepto not in CONCEPTOS:
            raise ErrorValidacion("Concepto de pago no válido.")
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            cliente = self._cliente(sesion, cliente_id)
            membresia = None
            pagado = 0
            if concepto == "membresia":
                if membresia_id is None:
                    raise ErrorValidacion("Elija la membresía a la que se abona.")
                membresia = sesion.get(Membresia, membresia_id)
                if membresia is None or membresia.cliente_id != cliente.id:
                    raise ErrorValidacion("La membresía no pertenece a este cliente.")
                if membresia.estado != "activa":
                    raise ErrorValidacion("La membresía está anulada: no recibe pagos.")
                pagado = saldos_por_membresia(sesion, [membresia.id]).get(membresia.id, 0)
                saldo = membresia.precio_pactado - pagado
                if saldo <= 0:
                    raise ErrorValidacion("La membresía ya está paga por completo.")
                if datos.monto > saldo:
                    raise ErrorValidacion(
                        f"El pago supera el saldo pendiente de la membresía "
                        f"({_pesos(saldo)})."
                    )
            elif membresia_id is not None:
                raise ErrorValidacion("Solo los pagos de membresía se asocian a una membresía.")
            registrado = self._crear_pago(
                sesion, actual, cliente, datos, concepto, membresia, pagado, ahora
            )
            registrar_uso(sesion, actual, admin, "pago", ahora, recibo=registrado.recibo)
            sesion.commit()
        self.autorizaciones.gastar(autorizacion)
        return registrado

    def anular_pago(self, actual: UsuarioActual, pago_id: int, motivo: str) -> None:
        """Solo admin. El pago sigue visible con su motivo y deja de sumar en la caja."""
        exigir(actual, Permiso.ANULAR_PAGOS)
        motivo = _motivo(motivo, "de la anulación")
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            pago = sesion.get(Pago, pago_id)
            if pago is None:
                raise ErrorValidacion("El pago no existe.")
            if pago.anulado:
                raise ErrorValidacion("El pago ya está anulado.")
            self._marcar_anulado(pago, actual, motivo, ahora)
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
            cliente = sesion.get(Cliente, pago.cliente_id)
            auditoria.registrar(
                sesion, "pago_anulado", "pagos", usuario_id=actual.id, entidad_id=pago.id,
                momento=ahora,
                detalle={"recibo": numero_recibo(prefijo, pago.consecutivo),
                         "cliente": cliente.codigo, "monto": pago.monto, "motivo": motivo},
            )
            sesion.commit()

    def saldo_cliente(self, actual: UsuarioActual, cliente_id: int) -> int:
        """Lo que el cliente debe en sus membresías activas (para el aviso de Recepción)."""
        exigir(actual, Permiso.VER_CLIENTES)
        with self._fabrica() as sesion:
            return saldo_pendiente_cliente(sesion, cliente_id)

    # --- cierre de caja --------------------------------------------------------------
    def cierre_caja(
        self, actual: UsuarioActual, dia: date | None = None, usuario_id: int | None = None,
        autorizacion: Autorizacion | None = None,
    ) -> CierreCaja:
        """Pagos del día (de Bogotá). Recepción solo ve los suyos de hoy, con la
        autorización de un administrador para el módulo de Pagos."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        self.autorizaciones.verificar(actual, autorizacion, PARA_MODULO_PAGOS)
        hoy = self.hoy()
        dia = dia or hoy
        if not actual.puede(Permiso.CIERRE_CAJA_GENERAL):
            if dia != hoy:
                raise ErrorPermiso("Recepción solo puede ver el cierre de caja del día de hoy.")
            if usuario_id not in (None, actual.id):
                raise ErrorPermiso("Recepción solo puede ver su propio cierre de caja.")
            usuario_id = actual.id
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
            consulta = (
                select(Pago, Cliente.codigo, Cliente.nombres, Cliente.apellidos, Usuario.usuario)
                .join(Cliente, Cliente.id == Pago.cliente_id)
                .join(Usuario, Usuario.id == Pago.usuario_id)
                .where(Pago.fecha_hora >= inicio_dia_utc(dia),
                       Pago.fecha_hora < inicio_dia_utc(dia + timedelta(days=1)))
                .order_by(Pago.fecha_hora, Pago.id)
            )
            if usuario_id is not None:
                consulta = consulta.where(Pago.usuario_id == usuario_id)
            filas = [
                FilaCaja(
                    pago_id=p.id, recibo=numero_recibo(prefijo, p.consecutivo),
                    fecha_hora=p.fecha_hora, cliente_codigo=codigo,
                    cliente_nombre=f"{nombres} {apellidos}", concepto=p.concepto,
                    metodo=p.metodo, referencia=p.referencia or "", monto=p.monto,
                    usuario_id=p.usuario_id, usuario=usuario, anulado=p.anulado,
                    motivo_anulacion=p.motivo_anulacion or "",
                )
                for p, codigo, nombres, apellidos, usuario in sesion.execute(consulta)
            ]
        validas = [f for f in filas if not f.anulado]
        por_metodo = {m: 0 for m in METODOS}
        por_usuario: dict[int, dict] = {}
        for f in validas:
            por_metodo[f.metodo] += f.monto
            u = por_usuario.setdefault(
                f.usuario_id, {"usuario": f.usuario, "metodos": defaultdict(int), "cantidad": 0}
            )
            u["metodos"][f.metodo] += f.monto
            u["cantidad"] += 1
        totales = [
            TotalUsuario(
                usuario_id=uid, usuario=u["usuario"],
                por_metodo={m: u["metodos"].get(m, 0) for m in METODOS},
                total=sum(u["metodos"].values()), cantidad=u["cantidad"],
            )
            for uid, u in sorted(por_usuario.items(), key=lambda x: x[1]["usuario"])
        ]
        anulados = [f for f in filas if f.anulado]
        return CierreCaja(
            dia=dia, usuario_id=usuario_id, filas=filas, por_metodo=por_metodo,
            por_usuario=totales, total=sum(por_metodo.values()), cantidad=len(validas),
            anulados_cantidad=len(anulados), anulados_monto=sum(f.monto for f in anulados),
        )

    # --- recibos ----------------------------------------------------------------------
    def datos_recibo(self, actual: UsuarioActual, pago_id: int) -> DatosRecibo:
        """Datos del recibo al que pertenece el pago, con todos sus conceptos."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        with self._fabrica() as sesion:
            pago = sesion.get(Pago, pago_id)
            if pago is None:
                raise ErrorValidacion("El pago no existe.")
            # Mensualidad primero, luego casillero y otros.
            orden = {"membresia": 0, "casillero": 1, "otro": 2}
            pagos = sorted(
                sesion.scalars(select(Pago).where(Pago.consecutivo == pago.consecutivo)),
                key=lambda p: (orden[p.concepto], p.id),
            )
            principal = pagos[0]
            cliente = sesion.get(Cliente, principal.cliente_id)
            usuario = sesion.get(Usuario, principal.usuario_id)
            obtener = lambda clave: self._configuracion.obtener(clave, sesion)  # noqa: E731
            precio = saldo = vigencia_desde = vigencia_hasta = None
            if principal.membresia_id is not None:
                membresia = sesion.get(Membresia, principal.membresia_id)
                precio = membresia.precio_pactado
                vigencia_desde, vigencia_hasta = membresia.fecha_inicio, membresia.fecha_fin
                # Saldo justo después de este pago: lo pagado hasta este recibo inclusive.
                pagado = sesion.scalar(
                    select(func.coalesce(func.sum(Pago.monto), 0)).where(
                        Pago.membresia_id == membresia.id, Pago.anulado.is_(False),
                        Pago.consecutivo <= principal.consecutivo,
                    )
                )
                saldo = max(0, precio - int(pagado))
            vigente_hasta = None
            if vigencia_hasta is None:
                vigente_hasta = sesion.scalar(
                    select(func.max(Membresia.fecha_fin)).where(
                        Membresia.cliente_id == cliente.id, Membresia.estado == "activa")
                )
            lineas = [
                LineaRecibo(CONCEPTOS[p.concepto], self._detalle_pago(sesion, p), p.monto, p.anulado)
                for p in pagos
            ]
            todos_anulados = all(p.anulado for p in pagos)
            if len(pagos) == 1:
                monto, extra = principal.monto, []
            else:
                monto = sum(p.monto for p in pagos if todos_anulados or not p.anulado)
                extra = lineas
            motivos = "; ".join(dict.fromkeys(p.motivo_anulacion for p in pagos if p.anulado))
            return DatosRecibo(
                recibo=numero_recibo(obtener("recibo_prefijo"), principal.consecutivo),
                fecha_hora=principal.fecha_hora,
                gimnasio_nombre=obtener("gimnasio_nombre") or "Enforma",
                gimnasio_nit=obtener("gimnasio_nit"),
                gimnasio_direccion=obtener("gimnasio_direccion"),
                gimnasio_telefono=obtener("gimnasio_telefono"),
                logo=self._configuracion.ruta_logo(),
                cliente_codigo=cliente.codigo,
                cliente_nombre=f"{cliente.nombres} {cliente.apellidos}",
                cliente_documento=f"{cliente.tipo_documento} {cliente.documento}",
                concepto=CONCEPTOS[principal.concepto], detalle=lineas[0].detalle,
                metodo=METODOS[principal.metodo], referencia=principal.referencia or "",
                monto=monto, precio_membresia=precio, saldo_despues=saldo,
                usuario=usuario.nombre_completo if usuario else "—",
                anulado=todos_anulados, motivo_anulacion=motivos if todos_anulados else "",
                vigencia_desde=vigencia_desde, vigencia_hasta=vigencia_hasta,
                vigente_hasta=vigente_hasta, lineas=extra,
            )

    @staticmethod
    def _detalle_pago(sesion: Session, pago: Pago) -> str:
        if pago.casillero_asignacion_id is not None:
            asignacion = sesion.get(CasilleroAsignacion, pago.casillero_asignacion_id)
            casillero = sesion.get(Casillero, asignacion.casillero_id)
            return f"Casillero {casillero.numero}"
        if pago.membresia_id is not None:
            membresia = sesion.get(Membresia, pago.membresia_id)
            plan = sesion.get(Plan, membresia.plan_id)
            return (f"Membresía {plan.nombre} del {formato_fecha(membresia.fecha_inicio)} "
                    f"al {formato_fecha(membresia.fecha_fin)}")
        return CONCEPTOS[pago.concepto]

    def generar_recibo(
        self, actual: UsuarioActual, pago_id: int, destino: Path | str | None = None
    ) -> Path:
        """Crea el PDF del recibo (por defecto en la carpeta de datos, subcarpeta recibos)."""
        from gimnasio.reportes.recibo import crear_recibo_pdf

        datos = self.datos_recibo(actual, pago_id)
        if destino is None:
            carpeta = (self._carpeta or cfg.carpeta_datos()) / "recibos"
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = carpeta / f"{datos.recibo}.pdf"
        destino = Path(destino)
        crear_recibo_pdf(datos, destino)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "recibo_generado", "pagos", usuario_id=actual.id, entidad_id=pago_id,
                detalle={"recibo": datos.recibo},
            )
            sesion.commit()
        return destino

    # --- consultas -------------------------------------------------------------------

    def consultar_pagos(self, actual: UsuarioActual, filtros: FiltrosPagos,
                        limite: int = LIMITE_CONSULTA,
                        autorizacion: Autorizacion | None = None) -> ConsultaPagos:
        """Pagos por cliente y/o por fecha de pago, del más reciente al más antiguo.

        El administrador consulta todo; Recepción solo los pagos de un cliente puntual.
        """
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        self.autorizaciones.verificar(actual, autorizacion, PARA_MODULO_PAGOS)
        if filtros.cliente_id is None and not actual.puede(Permiso.REPORTES_TODOS):
            raise ErrorPermiso("Recepción solo puede consultar los pagos de un cliente. Elija el cliente.")
        if filtros.desde and filtros.hasta and filtros.desde > filtros.hasta:
            raise ErrorValidacion("La fecha inicial no puede ser posterior a la final.")
        if filtros.metodo and filtros.metodo not in METODOS:
            raise ErrorValidacion("Método de pago no válido.")
        if filtros.concepto and filtros.concepto not in CONCEPTOS:
            raise ErrorValidacion("Concepto no válido.")
        condiciones = []
        if filtros.cliente_id is not None:
            condiciones.append(Pago.cliente_id == filtros.cliente_id)
        if filtros.desde:
            condiciones.append(Pago.fecha_hora >= inicio_dia_utc(filtros.desde))
        if filtros.hasta:
            condiciones.append(Pago.fecha_hora < inicio_dia_utc(filtros.hasta + timedelta(days=1)))
        if filtros.metodo:
            condiciones.append(Pago.metodo == filtros.metodo)
        if filtros.concepto:
            condiciones.append(Pago.concepto == filtros.concepto)
        if filtros.usuario_id:
            condiciones.append(Pago.usuario_id == filtros.usuario_id)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
            totales = {
                bool(anulado): (cantidad, suma)
                for anulado, cantidad, suma in sesion.execute(
                    select(Pago.anulado, func.count(Pago.id), func.coalesce(func.sum(Pago.monto), 0))
                    .where(*condiciones).group_by(Pago.anulado))
            }
            if not filtros.incluir_anulados:
                condiciones.append(Pago.anulado.is_(False))
            consulta = (
                select(Pago, Cliente.codigo, Cliente.nombres, Cliente.apellidos, Usuario.usuario,
                       Plan.nombre, Membresia.fecha_inicio, Membresia.fecha_fin)
                .join(Cliente, Cliente.id == Pago.cliente_id)
                .join(Usuario, Usuario.id == Pago.usuario_id)
                .outerjoin(Membresia, Membresia.id == Pago.membresia_id)
                .outerjoin(Plan, Plan.id == Membresia.plan_id)
                .where(*condiciones)
                .order_by(Pago.fecha_hora.desc(), Pago.id.desc())
                .limit(limite + 1)
            )
            filas = []
            for p, codigo, nombres, apellidos, usuario, plan, inicio, fin in sesion.execute(consulta):
                detalle = (f"{plan}: {formato_fecha(inicio)} al {formato_fecha(fin)}"
                           if plan else "")
                filas.append(FilaConsultaPago(
                    pago_id=p.id, recibo=numero_recibo(prefijo, p.consecutivo),
                    fecha_hora=p.fecha_hora, cliente_codigo=codigo,
                    cliente_nombre=f"{nombres} {apellidos}", concepto=p.concepto, detalle=detalle,
                    metodo=p.metodo, referencia=p.referencia or "", monto=p.monto,
                    usuario=usuario, anulado=p.anulado, motivo_anulacion=p.motivo_anulacion or "",
                ))
        validos = totales.get(False, (0, 0))
        anulados = totales.get(True, (0, 0))
        return ConsultaPagos(
            filas=filas[:limite], total=int(validos[1]), cantidad=int(validos[0]),
            anulados_cantidad=int(anulados[0]), anulados_monto=int(anulados[1]),
            truncada=len(filas) > limite,
        )

    def exportar_consulta(self, actual: UsuarioActual, filtros: FiltrosPagos,
                           ruta: Path | str, formato: str,
                           autorizacion: Autorizacion | None = None) -> Path:
        """Exporta la consulta a Excel ("xlsx") o PDF ("pdf"). Queda en la auditoría."""
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        consulta = self.consultar_pagos(actual, filtros, limite=10**9,
                                        autorizacion=autorizacion)
        partes = []
        if filtros.desde or filtros.hasta:
            partes.append("Pagos del " + (formato_fecha(filtros.desde) if filtros.desde else "inicio")
                          + " al " + (formato_fecha(filtros.hasta) if filtros.hasta else "hoy"))
        if filtros.cliente_id and consulta.filas:
            partes.append(f"Cliente {consulta.filas[0].cliente_codigo} · {consulta.filas[0].cliente_nombre}")
        partes.append(f"{consulta.cantidad} pagos válidos · total {_pesos(consulta.total)}")
        if consulta.anulados_cantidad:
            partes.append(f"{consulta.anulados_cantidad} anulados por "
                          f"{_pesos(consulta.anulados_monto)} (no suman)")
        subtitulo = " · ".join(partes)
        filas = filas_exportables(consulta)
        totales = ("Total", *[""] * 9, consulta.total)
        if formato == "xlsx":
            destino = exp.exportar_excel(ruta, "Consulta de pagos", ENCABEZADOS_CONSULTA, filas,
                                         totales=totales, dinero={10}, subtitulo=subtitulo)
        else:
            destino = exp.exportar_pdf(ruta, "Consulta de pagos", subtitulo, ENCABEZADOS_CONSULTA,
                                       filas, totales=totales, dinero={10})
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "pagos_exportados", "pagos", usuario_id=actual.id, momento=self._reloj(),
                detalle={"formato": formato, "filas": len(filas),
                         "cliente_id": filtros.cliente_id,
                         "desde": formato_fecha(filtros.desde) if filtros.desde else None,
                         "hasta": formato_fecha(filtros.hasta) if filtros.hasta else None},
            )
            sesion.commit()
        return Path(destino)


    # --- apoyo ------------------------------------------------------------------------
    @staticmethod
    def _cliente(sesion: Session, cliente_id: int) -> Cliente:
        cliente = sesion.get(Cliente, cliente_id)
        if cliente is None:
            raise ErrorValidacion("El cliente no existe.")
        return cliente

    @staticmethod
    def _ultima_membresia(sesion: Session, cliente_id: int) -> Membresia | None:
        return sesion.scalars(
            select(Membresia)
            .where(Membresia.cliente_id == cliente_id, Membresia.estado == "activa")
            .order_by(Membresia.fecha_fin.desc(), Membresia.id.desc())
        ).first()

    def _siguiente_consecutivo(self, sesion: Session) -> int:
        """El mayor entre el configurado y el último usado + 1; deja guardado el siguiente."""
        configurado = self._configuracion.obtener("recibo_siguiente", sesion)
        maximo = sesion.scalar(select(func.max(Pago.consecutivo))) or 0
        numero = max(int(configurado), maximo + 1)
        fila = sesion.get(Config, "recibo_siguiente")
        if fila is None:
            sesion.add(Config(clave="recibo_siguiente", valor=str(numero + 1)))
        else:
            fila.valor = str(numero + 1)
        return numero

    def pago_casillero_en_sesion(
        self, sesion: Session, actual: UsuarioActual, cliente: Cliente, datos: DatosPago,
        asignacion_id: int, ahora: datetime, consecutivo: int | None = None,
    ) -> PagoRegistrado:
        """Pago de casillero dentro de la transacción del servicio de casilleros
        (asignar o renovar y cobrar quedan juntos: o se guarda todo o nada).
        Con `consecutivo` va en el mismo recibo que el pago de la mensualidad."""
        exigir(actual, Permiso.REGISTRAR_PAGOS)
        datos = _validar_pago(datos)
        return self._crear_pago(sesion, actual, cliente, datos, "casillero", None, 0, ahora,
                                casillero_asignacion_id=asignacion_id, consecutivo=consecutivo)

    def _crear_pago(
        self, sesion: Session, actual: UsuarioActual, cliente: Cliente, datos: DatosPago,
        concepto: str, membresia: Membresia | None, pagado_antes: int, ahora: datetime,
        casillero_asignacion_id: int | None = None, consecutivo: int | None = None,
    ) -> PagoRegistrado:
        if consecutivo is None:
            consecutivo = self._siguiente_consecutivo(sesion)
        pago = Pago(
            consecutivo=consecutivo, cliente_id=cliente.id,
            membresia_id=membresia.id if membresia else None, concepto=concepto,
            casillero_asignacion_id=casillero_asignacion_id,
            monto=datos.monto, metodo=datos.metodo, referencia=datos.referencia or None,
            fecha_hora=ahora, usuario_id=actual.id,
        )
        sesion.add(pago)
        sesion.flush()
        recibo = numero_recibo(self._configuracion.obtener("recibo_prefijo", sesion), consecutivo)
        saldo = (membresia.precio_pactado - pagado_antes - datos.monto) if membresia else None
        detalle = {"recibo": recibo, "cliente": cliente.codigo, "concepto": concepto,
                   "monto": datos.monto, "metodo": datos.metodo}
        if saldo is not None:
            detalle["saldo"] = saldo
        if casillero_asignacion_id is not None:
            detalle["casillero_asignacion"] = casillero_asignacion_id
        auditoria.registrar(
            sesion, "pago_registrado", "pagos", usuario_id=actual.id, entidad_id=pago.id,
            detalle=detalle, momento=ahora,
        )
        return PagoRegistrado(pago.id, consecutivo, recibo, datos.monto, saldo)

    @staticmethod
    def _marcar_anulado(pago: Pago, actual: UsuarioActual, motivo: str, ahora: datetime) -> None:
        pago.anulado = True
        pago.motivo_anulacion = motivo
        pago.anulado_por = actual.id
        pago.anulado_en = ahora


