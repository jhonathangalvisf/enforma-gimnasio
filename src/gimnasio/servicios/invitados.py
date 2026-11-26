"""Invitados (sección 3.7).

Reglas:
- El documento identifica a la persona (RN-10): si el invitado ya existe se reutiliza
  el mismo registro, nunca se duplica.
- El número de visitas **no se guarda**: se cuenta desde `invitado_asistencias`
  (sin las eliminadas). La ficha muestra el total, las visitas del mes y el detalle
  de cada fecha.
- Los invitados no pagan y no hay límite de invitados por cliente (decisión del dueño,
  Fase 6). Sí existe un límite opcional de visitas de la misma persona al mes
  (parámetro `invitado_visitas_mes`, 0 = sin límite): al llegar al máximo se avisa y la
  visita necesita la contraseña de un administrador, que queda en la auditoría.
- Si el invitado ya vino hoy se sigue el mismo parámetro de Recepción
  (`asistencia_duplicada`): avisar y confirmar, bloquear o registrar sin avisar.
- Las visitas se eliminan de forma lógica con motivo (RN-08). Recepción solo las del
  día; el administrador, cualquiera.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha as formato_fecha
from gimnasio.modelos import Cliente, Invitado, InvitadoAsistencia, Usuario, ahora_utc
from gimnasio.servicios import auditoria
from gimnasio.servicios.asistencia import Reporte
from gimnasio.servicios.clientes import normalizar_telefono
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorPermiso, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, ServicioSesion, usuario_vigente
from gimnasio.texto import normalizar

# Estados al registrar una visita.
REGISTRADA = "registrada"
DUPLICADO_CONFIRMAR = "duplicado_confirmar"
DUPLICADO_BLOQUEADO = "duplicado_bloqueado"
LIMITE_AUTORIZAR = "limite_autorizar"

LIMITE_LISTA = 500

TIPOS_REPORTE = {
    "visitas": "Visitas de invitados",
    "invitados": "Visitas por invitado",
    "anfitriones": "Invitados por cliente anfitrión",
}


# --- datos -----------------------------------------------------------------------

@dataclass(frozen=True)
class DatosInvitado:
    nombre: str
    documento: str
    telefono: str = ""


@dataclass(frozen=True)
class FilaInvitado:
    id: int
    nombre: str
    documento: str
    telefono: str
    visitas: int
    visitas_mes: int
    ultima_visita: date | None


@dataclass(frozen=True)
class VisitaInvitado:
    id: int
    fecha_hora: datetime  # UTC
    fecha: date
    anfitrion_id: int | None
    anfitrion: str  # "000123 Nombre Apellido" o ""
    usuario: str
    autorizada_por: str | None = None
    eliminada: bool = False
    motivo_eliminacion: str | None = None


@dataclass(frozen=True)
class FichaInvitado:
    id: int
    nombre: str
    documento: str
    telefono: str
    creado_en: datetime
    creado_por: str
    total_visitas: int  # sin las eliminadas, más las visitas_anteriores
    visitas_mes: int  # del mes en curso (Bogotá)
    primera_visita: date | None
    ultima_visita: date | None
    visitas: list[VisitaInvitado]  # más reciente primero
    limite_mes: int = 0  # 0 = sin límite
    cliente_codigo: str | None = None  # el mismo documento ya es de un cliente
    visitas_anteriores: int = 0  # del programa anterior, sin fecha (incluidas en el total)

    @property
    def limite_alcanzado(self) -> bool:
        return bool(self.limite_mes) and self.visitas_mes >= self.limite_mes

    @property
    def texto_contador(self) -> str:
        n = self.total_visitas
        if n == 0:
            return "Aún no tiene visitas registradas"
        texto = f"Lleva {n} {'visita' if n == 1 else 'visitas'} como invitado"
        if self.visitas_anteriores:
            texto += f" ({self.visitas_anteriores} del programa anterior sin fecha)"
        return texto


@dataclass(frozen=True)
class ResultadoVisita:
    estado: str  # REGISTRADA, DUPLICADO_CONFIRMAR, DUPLICADO_BLOQUEADO o LIMITE_AUTORIZAR
    ficha: FichaInvitado
    visita_id: int | None = None
    visita_previa_hoy: datetime | None = None  # UTC

    @property
    def registrada(self) -> bool:
        return self.estado == REGISTRADA


@dataclass(frozen=True)
class ParametrosReporteInvitados:
    tipo: str = "visitas"
    desde: date | None = None
    hasta: date | None = None
    anfitrion_id: int | None = None  # "visitas": solo los invitados de ese cliente


# --- validación ------------------------------------------------------------------

def normalizar_documento(valor: str) -> str:
    """Quita espacios, puntos y guiones y pasa a mayúsculas ("1.020.304" = "1020304")."""
    return re.sub(r"[\s.\-]", "", valor or "").upper()


def _validar(datos: DatosInvitado) -> DatosInvitado:
    nombre = " ".join((datos.nombre or "").split())
    if len(nombre) < 3:
        raise ErrorValidacion("Escriba el nombre completo del invitado.")
    if len(nombre) > 160:
        raise ErrorValidacion("El nombre admite máximo 160 caracteres.")
    documento = normalizar_documento(datos.documento)
    if not documento:
        raise ErrorValidacion("Escriba el número de documento del invitado.")
    if not re.fullmatch(r"[A-Z0-9]{3,20}", documento):
        raise ErrorValidacion("El documento debe tener entre 3 y 20 letras o números.")
    telefono = normalizar_telefono(datos.telefono)
    return DatosInvitado(nombre=nombre, documento=documento, telefono=telefono)


def _motivo(texto: str) -> str:
    texto = " ".join((texto or "").split())
    if len(texto) < 3:
        raise ErrorValidacion("Escriba el motivo de la eliminación.")
    if len(texto) > 200:
        raise ErrorValidacion("El motivo admite máximo 200 caracteres.")
    return texto


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _como_fecha(valor) -> date | None:
    if valor is None or isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor))


def _hora_local(valor: datetime) -> str:
    return valor.astimezone(cfg.ZONA_HORARIA).strftime("%H:%M")


_VIGENTE = InvitadoAsistencia.eliminada.is_(False)


# --- servicio ----------------------------------------------------------------------

class ServicioInvitados:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        sesiones: ServicioSesion,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._sesiones = sesiones
        self._carpeta = carpeta_datos
        self._reloj = reloj

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    def inicio_mes(self) -> date:
        return self.hoy().replace(day=1)

    # --- registro ---------------------------------------------------------------
    def registrar(self, actual: UsuarioActual, datos: DatosInvitado) -> tuple[FichaInvitado, bool]:
        """Registra al invitado o, si el documento ya existe, reutiliza el registro.

        Devuelve la ficha y si fue nuevo. Al reutilizar, si se escribió un teléfono y el
        guardado estaba vacío, se completa; el nombre guardado no se cambia aquí.
        """
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        datos = _validar(datos)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            existente = sesion.scalar(
                select(Invitado).where(Invitado.documento == datos.documento)
            )
            if existente is not None:
                if datos.telefono and not existente.telefono:
                    existente.telefono = datos.telefono
                    auditoria.registrar(
                        sesion, "invitado_modificado", "invitados", usuario_id=actual.id,
                        entidad_id=existente.id, momento=ahora,
                        detalle={"documento": existente.documento,
                                 "cambios": {"telefono": ["", datos.telefono]}},
                    )
                    sesion.commit()
                return self._ficha(sesion, actual, existente), False
            invitado = Invitado(
                nombre=datos.nombre, documento=datos.documento, telefono=datos.telefono or None,
                creado_en=ahora, creado_por=actual.id,
            )
            sesion.add(invitado)
            sesion.flush()
            auditoria.registrar(
                sesion, "invitado_registrado", "invitados", usuario_id=actual.id,
                entidad_id=invitado.id, momento=ahora,
                detalle={"documento": invitado.documento, "nombre": invitado.nombre},
            )
            sesion.commit()
            return self._ficha(sesion, actual, invitado), True

    def modificar(self, actual: UsuarioActual, invitado_id: int, datos: DatosInvitado) -> FichaInvitado:
        """Corrige nombre y teléfono. Cambiar el documento es solo del administrador."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        datos = _validar(datos)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            invitado = self._obtener(sesion, invitado_id)
            cambios = {}
            if datos.documento != invitado.documento:
                if not actual.puede(Permiso.MODIFICAR_CLIENTE_COMPLETO):
                    raise ErrorPermiso("Solo el administrador puede cambiar el documento.")
                otro = sesion.scalar(select(Invitado.id).where(
                    Invitado.documento == datos.documento, Invitado.id != invitado.id))
                if otro is not None:
                    raise ErrorValidacion("Ya existe otro invitado con ese documento.")
                cambios["documento"] = [invitado.documento, datos.documento]
                invitado.documento = datos.documento
            if datos.nombre != invitado.nombre:
                cambios["nombre"] = [invitado.nombre, datos.nombre]
                invitado.nombre = datos.nombre
            if (datos.telefono or None) != invitado.telefono:
                cambios["telefono"] = [invitado.telefono or "", datos.telefono]
                invitado.telefono = datos.telefono or None
            if cambios:
                auditoria.registrar(
                    sesion, "invitado_modificado", "invitados", usuario_id=actual.id,
                    entidad_id=invitado.id, momento=ahora,
                    detalle={"documento": invitado.documento, "cambios": cambios},
                )
                sesion.commit()
            return self._ficha(sesion, actual, invitado)

    # --- visitas ----------------------------------------------------------------
    def registrar_visita(
        self,
        actual: UsuarioActual,
        invitado_id: int,
        anfitrion_id: int | None = None,
        *,
        confirmar_duplicado: bool = False,
        admin_usuario: str | None = None,
        admin_clave: str | None = None,
        motivo_autorizacion: str = "",
    ) -> ResultadoVisita:
        """Registra la visita de hoy. Si ya vino hoy o llegó al límite del mes, devuelve
        el estado correspondiente sin guardar nada para que la pantalla pregunte."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        hoy, ahora = self.hoy(), self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            invitado = self._obtener(sesion, invitado_id)
            if anfitrion_id is not None:
                anfitrion = sesion.get(Cliente, anfitrion_id)
                if anfitrion is None:
                    raise ErrorValidacion("El cliente anfitrión no existe.")
                if anfitrion.documento == invitado.documento:
                    raise ErrorValidacion("El invitado no puede ser su propio anfitrión.")
            previa = sesion.scalar(select(func.max(InvitadoAsistencia.fecha_hora)).where(
                InvitadoAsistencia.invitado_id == invitado.id,
                InvitadoAsistencia.fecha == hoy, _VIGENTE,
            ))
            if previa is not None and previa.tzinfo is None:
                previa = previa.replace(tzinfo=ahora.tzinfo)
            if previa is not None:
                politica = self._configuracion.obtener("asistencia_duplicada", sesion)
                if politica == "bloquear":
                    return ResultadoVisita(DUPLICADO_BLOQUEADO,
                                           self._ficha(sesion, actual, invitado), None, previa)
                if politica == "avisar" and not confirmar_duplicado:
                    return ResultadoVisita(DUPLICADO_CONFIRMAR,
                                           self._ficha(sesion, actual, invitado), None, previa)
            limite = self._configuracion.obtener("invitado_visitas_mes", sesion)
            autorizada_por = None
            if limite:
                del_mes = self._contar(sesion, invitado.id, desde=hoy.replace(day=1))
                if del_mes >= limite:
                    if actual.es_admin:
                        autorizada_por = actual.id
                    elif admin_usuario and admin_clave:
                        admin = self._sesiones.verificar_administrador(
                            admin_usuario, admin_clave,
                            f"autorizar visita del invitado {invitado.documento}",
                        )
                        autorizada_por = admin.id
                    else:
                        return ResultadoVisita(LIMITE_AUTORIZAR,
                                               self._ficha(sesion, actual, invitado), None, previa)
            visita = InvitadoAsistencia(
                invitado_id=invitado.id, fecha_hora=ahora, fecha=hoy,
                cliente_anfitrion_id=anfitrion_id, usuario_id=actual.id,
                autorizada_por=autorizada_por,
            )
            sesion.add(visita)
            sesion.flush()
            if autorizada_por is not None:
                motivo = " ".join((motivo_autorizacion or "").split())[:200]
                auditoria.registrar(
                    sesion, "invitado_visita_autorizada", "invitado_asistencias",
                    usuario_id=autorizada_por, entidad_id=visita.id, momento=ahora,
                    detalle={"invitado": invitado.documento, "limite_mes": limite,
                             "registrado_por": actual.usuario, "motivo": motivo or None},
                )
            sesion.commit()
            return ResultadoVisita(REGISTRADA, self._ficha(sesion, actual, invitado),
                                   visita.id, previa)

    def eliminar_visita(self, actual: UsuarioActual, visita_id: int, motivo: str) -> None:
        exigir(actual, Permiso.ELIMINAR_ASISTENCIA_DEL_DIA)
        motivo = _motivo(motivo)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            visita = sesion.get(InvitadoAsistencia, visita_id)
            if visita is None:
                raise ErrorValidacion("La visita no existe.")
            if visita.eliminada:
                raise ErrorValidacion("Esa visita ya estaba eliminada.")
            if visita.fecha != self.hoy() and not actual.puede(
                Permiso.ELIMINAR_ASISTENCIA_CUALQUIERA
            ):
                raise ErrorPermiso(
                    "Recepción solo puede eliminar visitas del día de hoy. "
                    "Pida al administrador las de otros días."
                )
            visita.eliminada = True
            visita.motivo_eliminacion = motivo
            visita.eliminada_por = actual.id
            visita.eliminada_en = ahora
            documento = sesion.scalar(
                select(Invitado.documento).where(Invitado.id == visita.invitado_id))
            auditoria.registrar(
                sesion, "invitado_visita_eliminada", "invitado_asistencias",
                usuario_id=actual.id, entidad_id=visita.id, momento=ahora,
                detalle={"invitado": documento, "fecha": formato_fecha(visita.fecha),
                         "hora": _hora_local(visita.fecha_hora), "motivo": motivo},
            )
            sesion.commit()

    # --- consultas --------------------------------------------------------------
    def buscar(self, actual: UsuarioActual, texto: str = "", limite: int = LIMITE_LISTA) -> list[FilaInvitado]:
        """Por nombre (sin tildes), documento o teléfono. Vacío = los de visita más reciente.

        Cada fila trae el total de visitas, las del mes y la última visita."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        texto = (texto or "").strip()
        inicio_mes = self.inicio_mes()
        total = func.count(InvitadoAsistencia.id).label("visitas")
        mes = func.sum(
            case((InvitadoAsistencia.fecha >= inicio_mes, 1), else_=0)
        ).label("visitas_mes")
        ultima = func.max(InvitadoAsistencia.fecha).label("ultima")
        consulta = (
            select(Invitado.id, Invitado.nombre, Invitado.documento, Invitado.telefono,
                   total, mes, ultima, Invitado.visitas_anteriores)
            .outerjoin(InvitadoAsistencia, and_(
                InvitadoAsistencia.invitado_id == Invitado.id, _VIGENTE))
            .group_by(Invitado.id)
            .order_by(ultima.desc().nulls_last(), Invitado.nombre)
            .limit(max(1, min(int(limite), 5000)))
        )
        if texto:
            consulta = consulta.where(self._condicion_texto(texto))
        with self._fabrica() as sesion:
            filas = sesion.execute(consulta).all()
        return [
            FilaInvitado(id=r.id, nombre=r.nombre, documento=r.documento,
                         telefono=r.telefono or "",
                         visitas=(r.visitas or 0) + (r.visitas_anteriores or 0),
                         visitas_mes=r.visitas_mes or 0, ultima_visita=_como_fecha(r.ultima))
            for r in filas
        ]

    def por_documento(self, actual: UsuarioActual, documento: str) -> FichaInvitado | None:
        """Ficha del invitado con ese documento, o None si nunca ha venido."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        documento = normalizar_documento(documento)
        if not documento:
            return None
        with self._fabrica() as sesion:
            invitado = sesion.scalar(select(Invitado).where(Invitado.documento == documento))
            return self._ficha(sesion, actual, invitado) if invitado else None

    def cliente_con_documento(self, actual: UsuarioActual, documento: str) -> str | None:
        """Código del cliente con ese documento (para avisar que ya es cliente)."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        documento = normalizar_documento(documento)
        if not documento:
            return None
        with self._fabrica() as sesion:
            return sesion.scalar(select(Cliente.codigo).where(Cliente.documento == documento))

    def ficha(self, actual: UsuarioActual, invitado_id: int) -> FichaInvitado:
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        with self._fabrica() as sesion:
            return self._ficha(sesion, actual, self._obtener(sesion, invitado_id))

    def contar_visitas(self, actual: UsuarioActual, invitado_id: int,
                       desde: date | None = None, hasta: date | None = None) -> int:
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        with self._fabrica() as sesion:
            self._obtener(sesion, invitado_id)
            return self._contar(sesion, invitado_id, desde, hasta)

    def visitas_de_hoy(self, actual: UsuarioActual) -> list[tuple[VisitaInvitado, str, str]]:
        """Visitas de hoy (más reciente primero) con nombre y documento del invitado."""
        exigir(actual, Permiso.REGISTRAR_INVITADOS)
        hoy = self.hoy()
        with self._fabrica() as sesion:
            return self._visitas(sesion, [InvitadoAsistencia.fecha == hoy, _VIGENTE])

    # --- reportes (RF-I5) ---------------------------------------------------------
    def reporte(self, actual: UsuarioActual, p: ParametrosReporteInvitados) -> Reporte:
        if p.tipo not in TIPOS_REPORTE:
            raise ErrorValidacion("Tipo de reporte no válido.")
        hoy = self.hoy()
        desde, hasta = p.desde or hoy, p.hasta or p.desde or hoy
        exigir(actual, Permiso.REPORTES_BASICOS)
        if not actual.puede(Permiso.REPORTES_TODOS) and (
            p.tipo != "visitas" or desde != hoy or hasta != hoy or p.anfitrion_id
        ):
            raise ErrorPermiso(
                "Recepción puede ver las visitas de invitados de hoy. "
                "Los demás reportes los consulta el administrador."
            )
        if desde > hasta:
            raise ErrorValidacion("La fecha inicial no puede ser posterior a la final.")
        nombre_gimnasio = self._configuracion.obtener("gimnasio_nombre")
        periodo = (formato_fecha(desde) if desde == hasta
                   else f"del {formato_fecha(desde)} al {formato_fecha(hasta)}")
        cola = f"generado el {formato_fecha(hoy)}"
        rango = [InvitadoAsistencia.fecha >= desde, InvitadoAsistencia.fecha <= hasta, _VIGENTE]

        with self._fabrica() as sesion:
            if p.tipo == "visitas":
                condiciones = list(rango)
                titulo = TIPOS_REPORTE["visitas"]
                if p.anfitrion_id:
                    anfitrion = sesion.get(Cliente, p.anfitrion_id)
                    if anfitrion is None:
                        raise ErrorValidacion("El cliente anfitrión no existe.")
                    condiciones.append(InvitadoAsistencia.cliente_anfitrion_id == anfitrion.id)
                    titulo += (f" de {anfitrion.codigo} "
                               f"{anfitrion.nombres} {anfitrion.apellidos}")
                visitas = self._visitas(sesion, condiciones)
                filas = [
                    (v.fecha, _hora_local(v.fecha_hora), documento, nombre, v.anfitrion,
                     v.usuario, v.autorizada_por or "")
                    for v, nombre, documento in visitas
                ]
                distintos = len({documento for _, _, documento in visitas})
                resumen = f"{len(filas)} visitas · {distintos} invitados distintos"
                return Reporte(
                    "visitas", titulo, f"{nombre_gimnasio} · {periodo} · {resumen} · {cola}",
                    ("Fecha", "Hora", "Documento", "Invitado", "Anfitrión", "Registró",
                     "Autorizó (límite)"),
                    filas, resumen, [v.id for v, _, _ in visitas],
                )

            if p.tipo == "invitados":
                cantidad = func.count(InvitadoAsistencia.id).label("cantidad")
                datos = sesion.execute(
                    select(Invitado.id, Invitado.documento, Invitado.nombre, Invitado.telefono,
                           cantidad,
                           func.min(InvitadoAsistencia.fecha).label("primera"),
                           func.max(InvitadoAsistencia.fecha).label("ultima"))
                    .join(InvitadoAsistencia, InvitadoAsistencia.invitado_id == Invitado.id)
                    .where(*rango)
                    .group_by(Invitado.id)
                    .order_by(cantidad.desc(), Invitado.nombre)
                ).all()
                # Total histórico de cada uno (no solo del periodo).
                totales = dict(sesion.execute(
                    select(InvitadoAsistencia.invitado_id, func.count(InvitadoAsistencia.id))
                    .where(_VIGENTE).group_by(InvitadoAsistencia.invitado_id)
                ).all())
                filas = [
                    (r.documento, r.nombre, r.telefono or "", r.cantidad,
                     _como_fecha(r.primera), _como_fecha(r.ultima),
                     totales.get(r.id, r.cantidad))
                    for r in datos
                ]
                resumen = (f"{len(filas)} invitados · "
                           f"{sum(f[3] for f in filas)} visitas en el periodo")
                return Reporte(
                    "invitados", TIPOS_REPORTE["invitados"],
                    f"{nombre_gimnasio} · {periodo} · {resumen} · {cola}",
                    ("Documento", "Invitado", "Teléfono", "Visitas en el periodo",
                     "Primera del periodo", "Última del periodo", "Visitas en total"),
                    filas, resumen,
                )

            # anfitriones
            visitas_n = func.count(InvitadoAsistencia.id).label("visitas")
            distintos = func.count(func.distinct(InvitadoAsistencia.invitado_id)).label("invitados")
            datos = sesion.execute(
                select(Cliente.codigo, Cliente.nombres, Cliente.apellidos, visitas_n, distintos,
                       func.max(InvitadoAsistencia.fecha).label("ultima"))
                .join(InvitadoAsistencia, InvitadoAsistencia.cliente_anfitrion_id == Cliente.id)
                .where(*rango)
                .group_by(Cliente.id)
                .order_by(visitas_n.desc(), Cliente.apellidos, Cliente.nombres)
            ).all()
            sin_anfitrion = sesion.scalar(
                select(func.count(InvitadoAsistencia.id))
                .where(*rango, InvitadoAsistencia.cliente_anfitrion_id.is_(None))
            ) or 0
        filas = [
            (r.codigo, f"{r.nombres} {r.apellidos}", r.invitados, r.visitas,
             _como_fecha(r.ultima))
            for r in datos
        ]
        resumen = f"{len(filas)} clientes invitaron · {sin_anfitrion} visitas sin anfitrión"
        return Reporte(
            "anfitriones", TIPOS_REPORTE["anfitriones"],
            f"{nombre_gimnasio} · {periodo} · {resumen} · {cola}",
            ("Código", "Cliente anfitrión", "Invitados distintos", "Visitas de invitados",
             "Última visita"),
            filas, resumen,
        )

    def exportar(self, actual: UsuarioActual, p: ParametrosReporteInvitados,
                 ruta: Path | str, formato: str) -> Path:
        """Exporta el reporte a Excel ("xlsx") o PDF ("pdf"). Queda en la auditoría."""
        from gimnasio.reportes import exportar as exp

        if formato not in ("xlsx", "pdf"):
            raise ErrorValidacion("Formato de exportación no válido.")
        rep = self.reporte(actual, p)
        if formato == "xlsx":
            ruta = exp.exportar_excel(ruta, rep.titulo, rep.encabezados, rep.filas)
        else:
            ruta = exp.exportar_pdf(ruta, rep.titulo, rep.subtitulo, rep.encabezados, rep.filas)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "invitados_exportados", "invitado_asistencias", usuario_id=actual.id,
                momento=self._reloj(),
                detalle={"reporte": rep.tipo, "formato": formato, "filas": len(rep.filas)},
            )
            sesion.commit()
        return Path(ruta)

    def carpeta_reportes(self) -> Path:
        carpeta = (self._carpeta or cfg.carpeta_datos()) / "reportes"
        carpeta.mkdir(parents=True, exist_ok=True)
        return carpeta

    # --- auxiliares ---------------------------------------------------------------
    @staticmethod
    def _obtener(sesion: Session, invitado_id: int) -> Invitado:
        invitado = sesion.get(Invitado, invitado_id)
        if invitado is None:
            raise ErrorValidacion("El invitado no existe.")
        return invitado

    @staticmethod
    def _contar(sesion: Session, invitado_id: int, desde: date | None = None,
                hasta: date | None = None) -> int:
        condiciones = [InvitadoAsistencia.invitado_id == invitado_id, _VIGENTE]
        if desde:
            condiciones.append(InvitadoAsistencia.fecha >= desde)
        if hasta:
            condiciones.append(InvitadoAsistencia.fecha <= hasta)
        return sesion.scalar(select(func.count(InvitadoAsistencia.id)).where(*condiciones)) or 0

    @staticmethod
    def _condicion_texto(texto: str) -> ColumnElement[bool]:
        digitos = re.sub(r"\D", "", texto)
        if digitos and re.fullmatch(r"\+?[\d\s.\-]+", texto):
            patron = _escapar_like(digitos)
            return or_(Invitado.documento.like(f"{patron}%", escape="\\"),
                       Invitado.telefono.like(f"%{patron}%", escape="\\"))
        palabras = [_escapar_like(normalizar(p)) for p in texto.split() if p]
        por_nombre = and_(*[Invitado.busqueda.like(f"%{p}%", escape="\\") for p in palabras])
        return or_(por_nombre, Invitado.documento == normalizar_documento(texto))

    def _visitas(self, sesion: Session, condiciones: list) -> list[tuple[VisitaInvitado, str, str]]:
        registro = aliased(Usuario)
        autorizo = aliased(Usuario)
        filas = sesion.execute(
            select(InvitadoAsistencia, Invitado.nombre, Invitado.documento,
                   Cliente.codigo, Cliente.nombres, Cliente.apellidos,
                   registro.usuario, autorizo.usuario)
            .join(Invitado, Invitado.id == InvitadoAsistencia.invitado_id)
            .outerjoin(Cliente, Cliente.id == InvitadoAsistencia.cliente_anfitrion_id)
            .outerjoin(registro, registro.id == InvitadoAsistencia.usuario_id)
            .outerjoin(autorizo, autorizo.id == InvitadoAsistencia.autorizada_por)
            .where(*condiciones)
            .order_by(InvitadoAsistencia.fecha.desc(), InvitadoAsistencia.fecha_hora.desc(),
                      InvitadoAsistencia.id.desc())
        ).all()
        return [
            (VisitaInvitado(
                id=v.id, fecha_hora=v.fecha_hora, fecha=v.fecha,
                anfitrion_id=v.cliente_anfitrion_id,
                anfitrion=f"{codigo} {nombres} {apellidos}" if codigo else "",
                usuario=usuario or "—", autorizada_por=autorizo_usuario,
                eliminada=v.eliminada, motivo_eliminacion=v.motivo_eliminacion,
            ), nombre, documento)
            for v, nombre, documento, codigo, nombres, apellidos, usuario, autorizo_usuario
            in filas
        ]

    def _ficha(self, sesion: Session, actual: UsuarioActual, invitado: Invitado) -> FichaInvitado:
        condiciones = [InvitadoAsistencia.invitado_id == invitado.id]
        if not actual.puede(Permiso.ELIMINAR_ASISTENCIA_CUALQUIERA):
            condiciones.append(_VIGENTE)  # las eliminadas solo las ve el administrador
        visitas = [v for v, _, _ in self._visitas(sesion, condiciones)]
        vigentes = [v for v in visitas if not v.eliminada]
        inicio_mes = self.inicio_mes()
        creador = sesion.scalar(
            select(Usuario.usuario).where(Usuario.id == invitado.creado_por)
        ) if invitado.creado_por else None
        cliente_codigo = sesion.scalar(
            select(Cliente.codigo).where(Cliente.documento == invitado.documento))
        return FichaInvitado(
            id=invitado.id, nombre=invitado.nombre, documento=invitado.documento,
            telefono=invitado.telefono or "", creado_en=invitado.creado_en,
            creado_por=creador or "—",
            total_visitas=len(vigentes) + (invitado.visitas_anteriores or 0),
            visitas_mes=sum(1 for v in vigentes if v.fecha >= inicio_mes),
            primera_visita=min((v.fecha for v in vigentes), default=None),
            ultima_visita=max((v.fecha for v in vigentes), default=None),
            visitas=visitas,
            limite_mes=self._configuracion.obtener("invitado_visitas_mes", sesion),
            cliente_codigo=cliente_codigo,
            visitas_anteriores=invitado.visitas_anteriores or 0,
        )
