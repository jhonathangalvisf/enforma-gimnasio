"""Depuración de pagos antiguos: borra los pagos hasta una fecha que elige el dueño.

Es la única excepción a RN-07 ("nada financiero se borra") y la pidió el dueño del
gimnasio para aligerar el historial. Por eso lleva varias protecciones:

- Solo el administrador, y además una **clave de seguridad propia** (distinta de su
  contraseña) guardada con argon2. Solo quien conoce esa clave entra al apartado.
- La fecha de corte debe ser anterior a hoy: nunca se borra la caja del día.
- Antes de borrar se hace **siempre** una copia de seguridad cifrada y un Excel con
  todo lo que se va a quitar. Si cualquiera de los dos falla, no se borra nada.
- No se rompe el historial del cliente: se conserva la última membresía de cada
  cliente con sus pagos, y las membresías que terminan después del corte con los
  suyos (borrarlos cambiaría su saldo). Junto con los pagos se borran las membresías
  ya terminadas a las que pertenecían.
- La secuencia de recibos no se reutiliza nunca: el siguiente número sigue después
  del mayor que haya existido.
- Queda en la auditoría: fecha de corte, cantidades, valor total y archivos creados.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.formato import fecha_hora_local, pesos
from gimnasio.modelos import Cliente, Config, Membresia, Pago, Plan, Usuario, ahora_utc
from gimnasio.servicios import auditoria, claves
from gimnasio.servicios.auditoria import inicio_dia_utc
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.pagos import CONCEPTOS, METODOS, numero_recibo
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente

CLAVE_CONFIG = "depuracion_clave_hash"
INTENTOS_MAXIMOS = 5
MINUTOS_BLOQUEO = 15


@dataclass(frozen=True)
class VistaPrevia:
    corte: date
    pagos: int
    monto_validos: int
    anulados: int
    membresias: int
    pagos_conservados: int  # pagos del periodo que se conservan (membresías vigentes o últimas)
    primer_pago: datetime | None
    ultimo_pago: datetime | None


@dataclass(frozen=True)
class ResultadoDepuracion:
    vista: VistaPrevia
    excel: Path
    copia_seguridad: str  # dónde quedó la copia (para mostrarlo)


class ServicioDepuracion:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        respaldar: Callable[[UsuarioActual], object],
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        """`respaldar(actual)` hace la copia de seguridad y devuelve un resultado con
        `exitoso`, `error` y `escrituras` (el de ServicioBackups.hacer_backup)."""
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._respaldar = respaldar
        self._carpeta = carpeta_datos
        self._reloj = reloj
        self._fallidos: list[datetime] = []

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    # --- clave de seguridad -----------------------------------------------------------
    def tiene_clave(self, actual: UsuarioActual) -> bool:
        exigir(actual, Permiso.DEPURAR_PAGOS)
        with self._fabrica() as sesion:
            fila = sesion.get(Config, CLAVE_CONFIG)
            return bool(fila and fila.valor)

    def configurar_clave(
        self, actual: UsuarioActual, clave_autorizacion: str, nueva: str, confirmar: str
    ) -> None:
        """La primera vez se autoriza con la contraseña del administrador; para cambiarla
        hace falta la clave de seguridad actual."""
        exigir(actual, Permiso.DEPURAR_PAGOS)
        if nueva != confirmar:
            raise ErrorValidacion("Las claves no coinciden.")
        claves.validar_clave(nueva)
        with self._fabrica() as sesion:
            usuario = usuario_vigente(sesion, actual)
            fila = sesion.get(Config, CLAVE_CONFIG)
            if fila and fila.valor:
                self._verificar(sesion, actual, fila.valor, clave_autorizacion,
                                "La clave de seguridad actual no es correcta.")
            elif not claves.verificar(usuario.hash_clave, clave_autorizacion):
                raise ErrorPermiso("La contraseña del administrador no es correcta.")
            if claves.verificar(usuario.hash_clave, nueva):
                raise ErrorValidacion(
                    "Use una clave de seguridad distinta de su contraseña de inicio de sesión.")
            sesion.merge(Config(clave=CLAVE_CONFIG, valor=claves.generar_hash(nueva)))
            auditoria.registrar(sesion, "clave_depuracion_configurada", "config",
                                usuario_id=actual.id, momento=self._reloj())
            sesion.commit()

    def comprobar_clave(self, actual: UsuarioActual, clave: str) -> None:
        """Para abrir el apartado. Lanza ErrorPermiso si la clave no es correcta."""
        exigir(actual, Permiso.DEPURAR_PAGOS)
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            fila = sesion.get(Config, CLAVE_CONFIG)
            if not (fila and fila.valor):
                raise ErrorValidacion("Primero configure la clave de seguridad.")
            self._verificar(sesion, actual, fila.valor, clave,
                            "La clave de seguridad no es correcta.")

    # --- depuración -------------------------------------------------------------------
    def vista_previa(self, actual: UsuarioActual, clave: str, corte: date) -> VistaPrevia:
        self.comprobar_clave(actual, clave)
        self._validar_corte(corte)
        with self._fabrica() as sesion:
            return self._vista(sesion, corte)[0]

    def depurar(self, actual: UsuarioActual, clave: str, corte: date,
                motivo: str) -> ResultadoDepuracion:
        self.comprobar_clave(actual, clave)
        self._validar_corte(corte)
        motivo = " ".join((motivo or "").split())
        if len(motivo) < 3:
            raise ErrorValidacion("Escriba el motivo de la depuración.")
        with self._fabrica() as sesion:
            vista, pagos_ids, membresias_ids = self._vista(sesion, corte)
        if not pagos_ids and not membresias_ids:
            raise ErrorValidacion(f"No hay pagos para borrar hasta el {formato_fecha(corte)}.")

        # 1. Excel con todo lo que se va a quitar (si falla, no se borra nada).
        excel = self._exportar(corte, pagos_ids, membresias_ids)
        # 2. Copia de seguridad cifrada completa (si falla, no se borra nada).
        copia = self._respaldar(actual)
        if not getattr(copia, "exitoso", False):
            raise ErrorValidacion(
                "No se pudo hacer la copia de seguridad, así que no se borró nada. "
                f"{getattr(copia, 'error', '')}".strip())
        rutas = [str(getattr(e, "ruta", "")) for e in getattr(copia, "escrituras", [])
                 if getattr(e, "exitoso", False)]

        # 3. Borrado en una sola transacción.
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            maximo = sesion.scalar(select(func.max(Pago.consecutivo))) or 0
            siguiente = max(int(self._configuracion.obtener("recibo_siguiente", sesion)),
                            maximo + 1)
            sesion.merge(Config(clave="recibo_siguiente", valor=str(siguiente)))
            for bloque in _bloques(pagos_ids):
                sesion.execute(delete(Pago).where(Pago.id.in_(bloque)))
            for bloque in _bloques(membresias_ids):
                sesion.execute(delete(Membresia).where(Membresia.id.in_(bloque)))
            auditoria.registrar(
                sesion, "pagos_depurados", "pagos", usuario_id=actual.id, momento=ahora,
                detalle={
                    "corte": formato_fecha(corte), "motivo": motivo,
                    "pagos_borrados": vista.pagos, "valor_validos": vista.monto_validos,
                    "anulados_borrados": vista.anulados,
                    "membresias_borradas": vista.membresias,
                    "pagos_conservados": vista.pagos_conservados,
                    "excel": excel.name, "copia_seguridad": rutas[0] if rutas else "",
                    "siguiente_recibo": siguiente,
                },
            )
            sesion.commit()
        return ResultadoDepuracion(vista=vista, excel=excel,
                                   copia_seguridad=rutas[0] if rutas else "")

    # --- apoyo ------------------------------------------------------------------------
    def _verificar(self, sesion: Session, actual: UsuarioActual, hash_guardado: str,
                   clave: str, mensaje: str) -> None:
        ahora = self._reloj()
        self._fallidos = [f for f in self._fallidos if ahora - f < timedelta(minutes=MINUTOS_BLOQUEO)]
        if len(self._fallidos) >= INTENTOS_MAXIMOS:
            raise ErrorPermiso(
                f"Demasiados intentos con la clave de seguridad. Espere {MINUTOS_BLOQUEO} minutos.")
        if claves.verificar(hash_guardado, clave or ""):
            self._fallidos.clear()
            return
        self._fallidos.append(ahora)
        auditoria.registrar(sesion, "depuracion_clave_incorrecta", "config",
                            usuario_id=actual.id, momento=ahora)
        sesion.commit()
        raise ErrorPermiso(mensaje)

    def _validar_corte(self, corte: date) -> None:
        if corte is None:
            raise ErrorValidacion("Elija la fecha hasta la que se borran los pagos.")
        if corte >= self.hoy():
            raise ErrorValidacion(
                "La fecha de corte debe ser anterior a hoy: los pagos de hoy no se borran.")

    def _vista(self, sesion: Session, corte: date) -> tuple[VistaPrevia, list[int], list[int]]:
        """Qué se borraría con ese corte (incluido el día de corte)."""
        limite = inicio_dia_utc(corte + timedelta(days=1))
        # Última membresía activa de cada cliente: nunca se borra.
        ultimas = self._ultimas_membresias(sesion)
        # Membresías que se borran con sus pagos: terminaron hasta el corte, no son la
        # última del cliente, tienen pagos y todos son de hasta el corte. Las que no
        # tienen pagos se conservan (no son pagos).
        con_pagos_recientes = select(Pago.membresia_id).where(
            Pago.membresia_id.is_not(None), Pago.fecha_hora >= limite)
        con_pagos = select(Pago.membresia_id).where(Pago.membresia_id.is_not(None))
        candidatas = set(sesion.scalars(
            select(Membresia.id).where(Membresia.fecha_fin <= corte,
                                       Membresia.id.in_(con_pagos),
                                       Membresia.id.not_in(con_pagos_recientes))
        )) - ultimas
        filas = sesion.execute(
            select(Pago.id, Pago.membresia_id, Pago.monto, Pago.anulado, Pago.fecha_hora)
            .where(Pago.fecha_hora < limite)
        ).all()
        borrar, conservados = [], 0
        monto = anulados = 0
        primero = ultimo = None
        for f in filas:
            if f.membresia_id is not None and f.membresia_id not in candidatas:
                conservados += 1
                continue
            borrar.append(f.id)
            if f.anulado:
                anulados += 1
            else:
                monto += f.monto
            primero = f.fecha_hora if primero is None or f.fecha_hora < primero else primero
            ultimo = f.fecha_hora if ultimo is None or f.fecha_hora > ultimo else ultimo
        vista = VistaPrevia(
            corte=corte, pagos=len(borrar), monto_validos=monto, anulados=anulados,
            membresias=len(candidatas), pagos_conservados=conservados,
            primer_pago=primero, ultimo_pago=ultimo,
        )
        return vista, borrar, sorted(candidatas)

    @staticmethod
    def _ultimas_membresias(sesion: Session) -> set[int]:
        """Id de la última membresía activa (mayor fecha de fin) de cada cliente."""
        ultimas: dict[int, tuple] = {}
        for mid, cliente_id, fin in sesion.execute(
            select(Membresia.id, Membresia.cliente_id, Membresia.fecha_fin)
            .where(Membresia.estado == "activa")
        ):
            actual = ultimas.get(cliente_id)
            if actual is None or (fin, mid) > actual:
                ultimas[cliente_id] = (fin, mid)
        return {mid for _, mid in ultimas.values()}

    def _exportar(self, corte: date, pagos_ids: list[int], membresias_ids: list[int]) -> Path:
        from gimnasio.reportes import exportar as exp

        carpeta = (self._carpeta or cfg.carpeta_datos()) / "depuraciones"
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = self._reloj().astimezone(cfg.ZONA_HORARIA).strftime("%Y%m%d_%H%M%S")
        ruta = carpeta / f"pagos_borrados_hasta_{corte:%Y%m%d}_{marca}.xlsx"
        with self._fabrica() as sesion:
            prefijo = self._configuracion.obtener("recibo_prefijo", sesion)
            filas = []
            for bloque in _bloques(pagos_ids):
                for p, codigo, nombres, apellidos, usuario, plan, inicio, fin in sesion.execute(
                    select(Pago, Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                           Usuario.usuario, Plan.nombre, Membresia.fecha_inicio,
                           Membresia.fecha_fin)
                    .join(Cliente, Cliente.id == Pago.cliente_id)
                    .join(Usuario, Usuario.id == Pago.usuario_id)
                    .outerjoin(Membresia, Membresia.id == Pago.membresia_id)
                    .outerjoin(Plan, Plan.id == Membresia.plan_id)
                    .where(Pago.id.in_(bloque))
                ):
                    filas.append((
                        p.fecha_hora, fecha_hora_local(p.fecha_hora),
                        numero_recibo(prefijo, p.consecutivo), codigo, f"{nombres} {apellidos}",
                        CONCEPTOS[p.concepto],
                        f"{plan}: {formato_fecha(inicio)} al {formato_fecha(fin)}" if plan else "",
                        METODOS[p.metodo], p.referencia or "", usuario,
                        f"Anulado: {p.motivo_anulacion}" if p.anulado else "Válido",
                        0 if p.anulado else p.monto,
                    ))
            filas.sort(key=lambda f: f[0])
            filas = [f[1:] for f in filas]
        total = sum(f[-1] for f in filas)
        subtitulo = (f"Pagos hasta el {formato_fecha(corte)} · {len(filas)} pagos · "
                     f"valor válido {pesos(total)} · {len(membresias_ids)} membresías terminadas "
                     f"borradas con ellos")
        return exp.exportar_excel(
            ruta, "Pagos borrados por depuración",
            ("Fecha y hora", "Recibo", "Código", "Cliente", "Concepto", "Membresía", "Método",
             "Referencia", "Registró", "Estado", "Monto"),
            filas, totales=("Total", *[""] * 9, total), dinero={10}, subtitulo=subtitulo,
        )


def _bloques(ids: list[int], tamano: int = 900):
    """SQLite limita los parámetros por consulta: se procesa por partes."""
    for i in range(0, len(ids), tamano):
        yield ids[i:i + tamano]
