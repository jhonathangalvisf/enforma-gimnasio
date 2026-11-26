"""Importación de los datos del programa anterior (Fase 10, sección 10).

- Solo el administrador (permiso `importar_datos`).
- Nunca toca la carpeta original: primero copia los .DBF a
  `<datos>/importaciones/<fecha_hora>/origen/` y lee esa copia.
- **Modo prueba** (por defecto): hace todo dentro de una transacción y al final la
  deshace, así el informe muestra exactamente lo que pasaría sin guardar nada.
- **Importar de verdad**: solo una vez por base; antes hace una copia de seguridad
  cifrada (si falla, no se importa nada) y todo va en una sola transacción.
- Siempre deja un informe en Excel con el resumen y los problemas fila por fila.
- Los montos del programa anterior no son reales: las membresías se importan con
  precio 0 y sin pagos, así no entra dinero falso a la caja.
"""

from __future__ import annotations

import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.formato import fecha_hora_local
from gimnasio.importacion import programa_anterior as pa
from gimnasio.modelos import (
    Asistencia, Casillero, CasilleroAsignacion, Cliente, Config, Contacto, Invitado,
    InvitadoAsistencia, Membresia, Plan, ahora_utc,
)
from gimnasio.servicios import auditoria
from gimnasio.servicios.clientes import CLAVE_CONSECUTIVO, TIPO_SIN_DOCUMENTO
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.servicios.sesion import Reloj, usuario_vigente

CLAVE_IMPORTADO = "importacion_programa_anterior"  # fecha y hora (UTC) de la importación
NOMBRE_PLAN = "Programa anterior"
ARCHIVOS = (pa.TABLA_CLIENTES, pa.TABLA_PAGOS, pa.TABLA_ASISTENCIAS, pa.TABLA_CASILLEROS,
            pa.TABLA_INVITADOS)
HORA_VISITA_INVITADO = 12


@dataclass
class ResultadoImportacion:
    guardado: bool
    leidos: dict[str, int]
    clientes: int = 0
    clientes_activos: int = 0
    sin_documento: int = 0
    membresias: int = 0
    vigentes: int = 0  # membresía con fin desde hoy
    telefonos: int = 0
    asistencias: int = 0
    casilleros_creados: int = 0
    casilleros_ocupados: int = 0
    invitados: int = 0
    visitas_invitados: int = 0  # incluye las visitas anteriores sin fecha
    problemas: list[pa.Problema] = field(default_factory=list)
    ruta_informe: Path | None = None
    ruta_backup: Path | None = None

    def lineas_resumen(self) -> list[tuple[str, str]]:
        n = lambda v: f"{v:,}".replace(",", ".")  # noqa: E731
        return [
            ("Modo", "Importación guardada" if self.guardado else "Prueba (no se guardó nada)"),
            ("Clientes", f"{n(self.clientes)} ({n(self.clientes_activos)} activos)"),
            ("Clientes «Sin documento»", n(self.sin_documento)),
            ("Membresías (vigencia anterior, sin valor)", n(self.membresias)),
            ("Clientes al día hoy", n(self.vigentes)),
            ("Teléfonos", n(self.telefonos)),
            ("Asistencias", n(self.asistencias)),
            ("Casilleros nuevos", n(self.casilleros_creados)),
            ("Casilleros ocupados", n(self.casilleros_ocupados)),
            ("Invitados", n(self.invitados)),
            ("Visitas de invitados", n(self.visitas_invitados)),
            ("Problemas anotados", n(len(self.problemas))),
        ]

    @property
    def texto(self) -> str:
        return "\n".join(f"{a}: {b}" for a, b in self.lineas_resumen())


def _utc(dia: date, hora: int) -> datetime:
    return datetime.combine(dia, time(hora), tzinfo=cfg.ZONA_HORARIA).astimezone(timezone.utc)


class ServicioImportacion:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
        hacer_backup: Callable[[UsuarioActual], object] | None = None,
    ):
        self._fabrica = fabrica
        self._carpeta = carpeta_datos
        self._reloj = reloj
        self._hacer_backup = hacer_backup

    def hoy(self) -> date:
        return self._reloj().astimezone(cfg.ZONA_HORARIA).date()

    def ya_importado(self, actual: UsuarioActual) -> datetime | None:
        """Cuándo se importó (UTC), o None si nunca."""
        exigir(actual, Permiso.IMPORTAR_DATOS)
        with self._fabrica() as sesion:
            return self._fecha_importado(sesion)

    @staticmethod
    def _fecha_importado(sesion: Session) -> datetime | None:
        guardado = sesion.get(Config, CLAVE_IMPORTADO)
        if not guardado or not guardado.valor:
            return None
        return datetime.fromisoformat(guardado.valor)

    def importar(self, actual: UsuarioActual, carpeta: Path | str,
                 guardar: bool = False) -> ResultadoImportacion:
        """Lee la carpeta DB3 y la importa (o solo la prueba, si `guardar` es False)."""
        exigir(actual, Permiso.IMPORTAR_DATOS)
        ahora = self._reloj()
        with self._fabrica() as sesion:
            usuario_vigente(sesion, actual)
            anterior = self._fecha_importado(sesion)
        if guardar and anterior:
            raise ErrorValidacion(
                f"Los datos del programa anterior ya se importaron el "
                f"{fecha_hora_local(anterior)}. No se pueden importar dos veces."
            )
        trabajo = self._carpeta_trabajo(ahora)
        origen = self._copiar_origen(Path(carpeta), trabajo / "origen")
        try:
            datos = pa.leer_carpeta(origen, self.hoy())
        except pa.ErrorCarpeta as e:
            raise ErrorValidacion(str(e)) from e

        ruta_backup = None
        if guardar:
            ruta_backup = self._copia_previa(actual)

        resultado = ResultadoImportacion(guardado=guardar, leidos=dict(datos.leidos))
        resultado.problemas = list(datos.problemas)
        resultado.ruta_backup = ruta_backup
        with self._fabrica() as sesion:
            self._cargar(sesion, actual, datos, resultado, ahora)
            if guardar:
                sesion.merge(Config(clave=CLAVE_IMPORTADO, valor=ahora.isoformat()))
                auditoria.registrar(
                    sesion, "importacion_programa_anterior", "clientes", usuario_id=actual.id,
                    detalle={
                        "carpeta": str(carpeta), "clientes": resultado.clientes,
                        "membresias": resultado.membresias,
                        "asistencias": resultado.asistencias,
                        "casilleros_ocupados": resultado.casilleros_ocupados,
                        "invitados": resultado.invitados,
                        "problemas": len(resultado.problemas),
                        "copia_seguridad": str(ruta_backup) if ruta_backup else None,
                    },
                    momento=ahora,
                )
                sesion.commit()
            else:
                sesion.rollback()
        resultado.ruta_informe = self._informe(trabajo, resultado, carpeta, ahora)
        return resultado

    # --- preparación ------------------------------------------------------------
    def _carpeta_trabajo(self, ahora: datetime) -> Path:
        marca = ahora.astimezone(cfg.ZONA_HORARIA).strftime("%Y%m%d_%H%M%S")
        base = (self._carpeta or cfg.carpeta_datos()) / "importaciones"
        carpeta, n = base / marca, 1
        while carpeta.exists():
            n += 1
            carpeta = base / f"{marca}_{n}"
        carpeta.mkdir(parents=True)
        return carpeta

    @staticmethod
    def _copiar_origen(carpeta: Path, destino: Path) -> Path:
        """Copia solo los .DBF que se usan: la carpeta original no se toca."""
        if not carpeta.is_dir():
            raise ErrorValidacion("La carpeta elegida no existe.")
        destino.mkdir(parents=True)
        from gimnasio.importacion.dbf import buscar_archivo

        for nombre in ARCHIVOS:
            ruta = buscar_archivo(carpeta, nombre)
            if ruta is not None:
                shutil.copy2(ruta, destino / nombre)
        return destino

    def _copia_previa(self, actual: UsuarioActual) -> Path | None:
        if self._hacer_backup is None:
            return None
        try:
            resultado = self._hacer_backup(actual)
        except Exception as e:  # noqa: BLE001 - cualquier fallo detiene la importación
            raise ErrorValidacion(
                f"No se pudo hacer la copia de seguridad previa ({e}). No se importó nada."
            ) from e
        if not getattr(resultado, "exitoso", False):
            error = getattr(resultado, "error", "") or "error desconocido"
            raise ErrorValidacion(
                f"No se pudo hacer la copia de seguridad previa ({error}). No se importó nada."
            )
        rutas = [e.ruta for e in getattr(resultado, "escrituras", []) if e.exitoso]
        return rutas[0] if rutas else None

    # --- carga ------------------------------------------------------------------
    def _cargar(self, sesion: Session, actual: UsuarioActual, datos: pa.DatosAntiguos,
                r: ResultadoImportacion, ahora: datetime) -> None:
        hoy = self.hoy()
        ids = self._cargar_clientes(sesion, actual, datos, r, ahora, hoy)
        self._cargar_asistencias(sesion, actual, datos, ids, r)
        self._cargar_casilleros(sesion, actual, datos, ids, r, ahora)
        self._cargar_invitados(sesion, actual, datos, r, ahora)

    def _plan(self, sesion: Session) -> Plan:
        plan = sesion.scalar(select(Plan).where(Plan.nombre == NOMBRE_PLAN))
        if plan is None:
            # Inactivo: solo sirve para las vigencias importadas, no se vende.
            plan = Plan(nombre=NOMBRE_PLAN, duracion_dias=pa.DIAS_PERIODO, precio=0, activo=False)
            sesion.add(plan)
            sesion.flush()
        return plan

    def _cargar_clientes(self, sesion: Session, actual: UsuarioActual, datos: pa.DatosAntiguos,
                         r: ResultadoImportacion, ahora: datetime, hoy: date) -> dict[str, int]:
        t = pa.TABLA_CLIENTES
        codigos = dict(sesion.execute(select(Cliente.codigo, Cliente.documento)).all())
        documentos = set(codigos.values())
        nuevos: list[tuple[pa.ClienteAntiguo, Cliente]] = []
        for c in datos.clientes:
            if c.codigo in codigos:
                igual = codigos[c.codigo] == c.documento
                r.problemas.append(pa.Problema(
                    t, c.fila, c.codigo,
                    "Ese código ya existe en el sistema nuevo"
                    + (" (mismo documento)." if igual else " con otra persona."),
                    "No se importa este cliente ni sus asistencias ni su casillero."))
                continue
            tipo, documento = c.tipo_documento, c.documento
            if tipo != TIPO_SIN_DOCUMENTO and documento in documentos:
                r.problemas.append(pa.Problema(
                    t, c.fila, c.codigo, f"El documento {documento} ya es de otro cliente del "
                    "sistema nuevo.", "Queda «Sin documento»; revíselo."))
                tipo, documento = TIPO_SIN_DOCUMENTO, f"SD{c.codigo}"
            documentos.add(documento)
            cliente = Cliente(
                codigo=c.codigo, qr_token=secrets.token_urlsafe(16), tipo_documento=tipo,
                documento=documento, nombres=c.nombres[:80], apellidos=c.apellidos[:80],
                sexo=c.sexo, fecha_nacimiento=c.fecha_nacimiento,
                direccion=c.direccion[:200] or None,
                notas="Importado del programa anterior.",
                estado="activo" if c.activo else "inactivo",
                creado_en=ahora, actualizado_en=ahora, creado_por=actual.id,
            )
            nuevos.append((c, cliente))
        sesion.add_all(cliente for _, cliente in nuevos)
        sesion.flush()

        plan = self._plan(sesion) if any(c.fecha_fin for c, _ in nuevos) else None
        contactos, membresias = [], []
        for c, cliente in nuevos:
            r.clientes += 1
            r.clientes_activos += c.activo
            r.sin_documento += cliente.tipo_documento == TIPO_SIN_DOCUMENTO
            if c.telefono:
                contactos.append(dict(cliente_id=cliente.id, tipo="telefono", valor=c.telefono,
                                      principal=True))
                r.telefonos += 1
            if c.emergencia_nombre and c.emergencia_telefono:
                contactos.append(dict(cliente_id=cliente.id, tipo="emergencia",
                                      valor=c.emergencia_telefono,
                                      nombre_contacto=c.emergencia_nombre[:120], principal=True))
            if c.fecha_fin and plan is not None:
                membresias.append(dict(
                    cliente_id=cliente.id, plan_id=plan.id, fecha_inicio=c.fecha_inicio,
                    fecha_fin=c.fecha_fin, precio_pactado=0, estado="activa",
                    creado_por=actual.id, creado_en=ahora,
                ))
                r.membresias += 1
                r.vigentes += c.fecha_fin >= hoy
        if contactos:
            sesion.execute(insert(Contacto), contactos)
        if membresias:
            sesion.execute(insert(Membresia), membresias)

        # El consecutivo sigue después del código más alto (los nuevos no chocan).
        maximo = sesion.scalar(select(func.max(Cliente.codigo)))
        guardado = sesion.get(Config, CLAVE_CONSECUTIVO)
        actual_consecutivo = int(guardado.valor) if guardado and (guardado.valor or "").isdigit() else 0
        if maximo:
            sesion.merge(Config(clave=CLAVE_CONSECUTIVO,
                                valor=str(max(actual_consecutivo, int(maximo) + 1))))
        return {c.codigo: cliente.id for c, cliente in nuevos}

    @staticmethod
    def _cargar_asistencias(sesion: Session, actual: UsuarioActual, datos: pa.DatosAntiguos,
                            ids: dict[str, int], r: ResultadoImportacion) -> None:
        filas = [
            dict(cliente_id=ids[a.codigo], fecha_hora=_utc(a.fecha, a.hora), fecha=a.fecha,
                 resultado="permitido", usuario_id=actual.id, eliminada=False)
            for a in datos.asistencias if a.codigo in ids
        ]
        if filas:
            sesion.execute(insert(Asistencia), filas)
        r.asistencias = len(filas)

    @staticmethod
    def _cargar_casilleros(sesion: Session, actual: UsuarioActual, datos: pa.DatosAntiguos,
                           ids: dict[str, int], r: ResultadoImportacion, ahora: datetime) -> None:
        t = pa.TABLA_CASILLEROS
        existentes: dict[int | str, Casillero] = {}
        for casillero in sesion.scalars(select(Casillero)):
            sin_ceros = casillero.numero.lstrip("0")
            existentes[int(sin_ceros) if sin_ceros.isdigit() else casillero.numero] = casillero
        ocupados = set(sesion.scalars(select(CasilleroAsignacion.casillero_id).where(
            CasilleroAsignacion.fecha_liberacion.is_(None))))
        con_casillero = set(sesion.scalars(select(CasilleroAsignacion.cliente_id).where(
            CasilleroAsignacion.fecha_liberacion.is_(None))))
        for c in datos.casilleros:
            casillero = existentes.get(int(c.numero))
            if casillero is None:
                casillero = Casillero(numero=c.numero, zona=c.zona, estado="disponible")
                sesion.add(casillero)
                sesion.flush()
                existentes[int(c.numero)] = casillero
                r.casilleros_creados += 1
            if not c.codigo_cliente:
                continue
            cliente_id = ids.get(c.codigo_cliente)
            if cliente_id is None:
                continue  # el cliente no se importó (ya está anotado en sus problemas)
            if casillero.id in ocupados or cliente_id in con_casillero:
                r.problemas.append(pa.Problema(
                    t, c.fila, c.numero, "El casillero o el cliente ya tienen una asignación "
                    "en el sistema nuevo.", "No se asigna."))
                continue
            if casillero.estado == "mantenimiento":
                r.problemas.append(pa.Problema(
                    t, c.fila, c.numero, "El casillero está en mantenimiento en el sistema nuevo.",
                    "No se asigna."))
                continue
            asignado = _utc(c.fecha_inicio, 0) if c.fecha_inicio else ahora
            sesion.add(CasilleroAsignacion(
                casillero_id=casillero.id, cliente_id=cliente_id, fecha_asignacion=asignado,
                fecha_vencimiento=c.fecha_fin, asignado_por=actual.id,
            ))
            casillero.estado = "ocupado"
            ocupados.add(casillero.id)
            con_casillero.add(cliente_id)
            r.casilleros_ocupados += 1
        sesion.flush()

    @staticmethod
    def _cargar_invitados(sesion: Session, actual: UsuarioActual, datos: pa.DatosAntiguos,
                          r: ResultadoImportacion, ahora: datetime) -> None:
        t = pa.TABLA_INVITADOS
        existentes = set(sesion.scalars(select(Invitado.documento)))
        nuevos: list[tuple[pa.InvitadoAntiguo, Invitado, list[date]]] = []
        for i in datos.invitados:
            if i.documento in existentes:
                r.problemas.append(pa.Problema(
                    t, i.fila, i.documento, "El invitado ya existe en el sistema nuevo.",
                    "No se importa."))
                continue
            existentes.add(i.documento)
            fechas = sorted({d for d in (i.primera, i.ultima) if d})
            invitado = Invitado(nombre=i.nombre[:160], documento=i.documento[:20],
                                creado_en=ahora, creado_por=actual.id,
                                visitas_anteriores=max(0, i.visitas - len(fechas)))
            nuevos.append((i, invitado, fechas))
        sesion.add_all(inv for _, inv, _ in nuevos)
        sesion.flush()
        visitas = [
            dict(invitado_id=inv.id, fecha_hora=_utc(d, HORA_VISITA_INVITADO), fecha=d,
                 usuario_id=actual.id, eliminada=False)
            for _, inv, fechas in nuevos for d in fechas
        ]
        if visitas:
            sesion.execute(insert(InvitadoAsistencia), visitas)
        r.invitados = len(nuevos)
        r.visitas_invitados = sum(max(i.visitas, len(f)) for i, _, f in nuevos)

    # --- informe ----------------------------------------------------------------
    def _informe(self, trabajo: Path, r: ResultadoImportacion, carpeta: Path | str,
                 ahora: datetime) -> Path:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        libro = Workbook()
        hoja = libro.active
        hoja.title = "Resumen"
        hoja.append(["Importación del programa anterior"])
        hoja["A1"].font = Font(bold=True, size=13)
        hoja.append([f"Generado el {fecha_hora_local(ahora)} · carpeta {carpeta}"])
        hoja.append([])
        for etiqueta, valor in r.lineas_resumen():
            hoja.append([etiqueta, valor])
        hoja.append([])
        hoja.append(["Registros leídos por archivo"])
        hoja[hoja.max_row][0].font = Font(bold=True)
        for archivo, cantidad in r.leidos.items():
            hoja.append([archivo, cantidad])
        if r.ruta_backup:
            hoja.append([])
            hoja.append(["Copia de seguridad previa", str(r.ruta_backup)])
        hoja.column_dimensions["A"].width = 42
        hoja.column_dimensions["B"].width = 40

        problemas = libro.create_sheet("Problemas")
        problemas.append(["Archivo", "Registro", "Código / documento", "Problema", "Qué se hizo"])
        for celda in problemas[1]:
            celda.font = Font(bold=True, color="FFFFFF")
            celda.fill = PatternFill("solid", fgColor="1F4E79")
        for p in sorted(r.problemas, key=lambda p: (p.tabla, p.fila)):
            problemas.append([p.tabla, p.fila or "", p.referencia, p.descripcion, p.accion])
        for columna, ancho in zip("ABCDE", (14, 10, 20, 60, 60)):
            problemas.column_dimensions[columna].width = ancho
        problemas.freeze_panes = "A2"

        nombre = "informe_importacion.xlsx" if r.guardado else "informe_prueba.xlsx"
        ruta = trabajo / nombre
        libro.save(ruta)
        return ruta


__all__ = ["ServicioImportacion", "ResultadoImportacion", "CLAVE_IMPORTADO", "NOMBRE_PLAN"]
