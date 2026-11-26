"""Copias de seguridad cifradas y restauración (sección 8 de la especificación).

Cada copia se guarda **en este PC** (`<datos>/backups`) y, si está configurado, en el
**disco externo o USB** (parámetro `backup_destino`). Si el disco no está conectado,
la copia queda en el PC y se avisa. La tercera copia de la regla 3-2-1 (un disco que el
dueño se lleva del local) se hace con `copiar_a_otro_disco`, con recordatorio semanal.

Hacer una copia tiene tres pasos para que la interfaz pueda correr el del medio en
segundo plano sin compartir conexiones de la base entre hilos:

1. `preparar()`: valida permisos y lee la configuración (hilo principal).
2. `ejecutar()`: instantánea, zip, cifrado, escritura, verificación y rotación. Solo
   toca archivos (usa su propia conexión sqlite3), así que puede ir en otro hilo.
3. `registrar()`: guarda el resultado en `backups_log` y en la auditoría.

`hacer_backup()` hace los tres seguidos.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.backup import cifrado, paquete, rotacion
from gimnasio.backup.cifrado import ClaveIncorrecta, ErrorBackup
from gimnasio.backup.paquete import Resumen
from gimnasio.backup.protector import AlmacenClave, ProtectorClave
from gimnasio.db.migraciones import actualizar_esquema, configuracion_alembic
from gimnasio.modelos import BackupLog, Config, Usuario, ahora_utc
from gimnasio.servicios import auditoria
from gimnasio.servicios.claves import LONGITUD_MINIMA
from gimnasio.servicios.configuracion import ServicioConfiguracion
from gimnasio.servicios.errores import ErrorNegocio, ErrorPermiso, ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir

TIPO_AUTOMATICO = "automatico"
TIPO_MANUAL = "manual"
TIPO_SEGURIDAD = "seguridad"
TIPOS = {TIPO_AUTOMATICO: "Automática", TIPO_MANUAL: "Manual",
         TIPO_SEGURIDAD: "Antes de restaurar"}
EXITOSO = "exitoso"
FALLIDO = "fallido"

DIAS_ALERTA = 2  # aviso al iniciar si la última copia buena es más vieja
DIAS_RECORDATORIO_EXTERNO = 7  # recordatorio semanal de la copia fuera del local
COPIAS_SEGURIDAD = 5  # copias "antes de restaurar" que se conservan
MINUTOS_REINTENTO = 60  # si la copia diaria falla, se reintenta cada hora
CARPETA_LOCAL = "backups"
CARPETA_SEGURIDAD = "antes_de_restaurar"
CLAVE_ULTIMA_EXTERNA = "backup_ultima_copia_externa"
PREFIJO = "enforma_"
UBICACION_PC = "Este PC"
UBICACION_EXTERNO = "Disco externo"
UBICACION_SEGURIDAD = "Antes de restaurar"

Reloj = Callable[[], datetime]


class ErrorBackupNegocio(ErrorNegocio):
    """Error de backup que se muestra al usuario tal cual."""


@dataclass(frozen=True)
class TareaBackup:
    """Todo lo que `ejecutar()` necesita, leído antes en el hilo principal."""

    tipo: str
    clave: str
    ruta_base: Path
    carpeta_datos: Path
    carpeta_local: Path
    destino_externo: Path | None
    creado: datetime  # UTC
    usuario_id: int | None


@dataclass
class EscrituraDestino:
    ubicacion: str
    ruta: Path
    exitoso: bool
    detalle: str = ""


@dataclass
class ResultadoBackup:
    tipo: str
    creado: datetime
    exitoso: bool
    escrituras: list[EscrituraDestino] = field(default_factory=list)
    resumen: Resumen | None = None
    tamano: int = 0
    error: str = ""
    borradas: list[Path] = field(default_factory=list)
    usuario_id: int | None = None

    @property
    def avisos(self) -> list[str]:
        return [f"{e.ubicacion}: {e.detalle}" for e in self.escrituras if not e.exitoso]

    @property
    def rutas(self) -> list[Path]:
        return [e.ruta for e in self.escrituras if e.exitoso]


@dataclass(frozen=True)
class ArchivoBackup:
    ruta: Path
    ubicacion: str
    creado: datetime | None  # UTC (del encabezado)
    tipo: str
    tamano: int
    resumen: dict
    legible: bool = True


@dataclass(frozen=True)
class EstadoBackups:
    ultima_exitosa: datetime | None  # UTC
    clave_configurada: bool
    clave_protegida: bool  # False fuera de Windows (sin DPAPI)
    destino: str
    destino_disponible: bool | None  # None = no hay disco externo configurado
    hora_diaria: int
    ultima_copia_externa: datetime | None
    ahora: datetime

    @property
    def dias_sin_copia(self) -> int | None:
        if self.ultima_exitosa is None:
            return None
        return (self.ahora - self.ultima_exitosa).days

    @property
    def alerta_antigua(self) -> bool:
        """Sin copias o la última buena tiene más de 2 días."""
        return (self.ultima_exitosa is None
                or self.ahora - self.ultima_exitosa > timedelta(days=DIAS_ALERTA))

    @property
    def recordatorio_externo(self) -> bool:
        return (self.ultima_copia_externa is None
                or self.ahora - self.ultima_copia_externa
                > timedelta(days=DIAS_RECORDATORIO_EXTERNO))


@dataclass(frozen=True)
class FilaHistorial:
    fecha_hora: datetime
    tipo: str
    ruta: str
    tamano_bytes: int | None
    resultado: str
    detalle: str


def destino_disponible(carpeta: Path) -> tuple[bool, str]:
    """La carpeta existe y se puede escribir en ella."""
    if not carpeta.is_dir():
        return False, f"No se encuentra la carpeta {carpeta}. ¿El disco está conectado?"
    try:
        with tempfile.NamedTemporaryFile(dir=carpeta, prefix=".prueba_", delete=True):
            pass
    except OSError:
        return False, f"No se puede escribir en {carpeta}. Revise el disco."
    return True, ""


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _escribir_verificado(datos: bytes, destino: Path) -> None:
    """Escribe a un temporal, lo lee de nuevo y compara; luego lo deja con su nombre."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name("." + destino.name + ".tmp")
    with open(temporal, "wb") as f:
        f.write(datos)
        f.flush()
        os.fsync(f.fileno())
    if _sha256(temporal) != hashlib.sha256(datos).hexdigest():
        temporal.unlink(missing_ok=True)
        raise ErrorBackup("La copia escrita no coincide al leerla de nuevo (disco con fallas).")
    os.replace(temporal, destino)


def nombre_archivo(creado_utc: datetime, tipo: str) -> str:
    local = creado_utc.astimezone(cfg.ZONA_HORARIA)
    marca = local.strftime("%Y-%m-%d_%H%M%S")
    if tipo == TIPO_SEGURIDAD:
        return f"{PREFIJO}antes_de_restaurar_{marca}{cifrado.EXTENSION}"
    return f"{PREFIJO}{marca}{cifrado.EXTENSION}"


def listar_carpeta(carpeta: Path, ubicacion: str) -> list[ArchivoBackup]:
    """Copias .enfbak de una carpeta (sin subcarpetas), leyendo solo el encabezado."""
    if not carpeta.is_dir():
        return []
    archivos = []
    for ruta in carpeta.glob(f"*{cifrado.EXTENSION}"):
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        try:
            encabezado = cifrado.leer_encabezado(ruta)
            creado = datetime.fromisoformat(encabezado.get("creado_utc"))
            archivos.append(ArchivoBackup(
                ruta=ruta, ubicacion=ubicacion, creado=creado,
                tipo=encabezado.get("tipo", ""), tamano=ruta.stat().st_size,
                resumen=encabezado.get("resumen") or {},
            ))
        except (ErrorBackup, OSError, ValueError, TypeError):
            archivos.append(ArchivoBackup(ruta=ruta, ubicacion=ubicacion, creado=None,
                                          tipo="", tamano=ruta.stat().st_size, resumen={},
                                          legible=False))
    return sorted(archivos, key=lambda a: a.creado or datetime.min.replace(
        tzinfo=ahora_utc().tzinfo), reverse=True)


def rotar_carpeta(carpeta: Path, ubicacion: str) -> list[Path]:
    """Aplica 7/4/12 a las copias normales de la carpeta. Devuelve las borradas."""
    copias = [a for a in listar_carpeta(carpeta, ubicacion)
              if a.legible and a.tipo in (TIPO_AUTOMATICO, TIPO_MANUAL)]
    borradas = []
    for archivo in rotacion.a_borrar(copias, lambda a: a.creado):
        try:
            archivo.ruta.unlink()
            borradas.append(archivo.ruta)
        except OSError:
            pass  # se intentará en la próxima copia
    return borradas


def rotar_seguridad(carpeta: Path) -> list[Path]:
    copias = [a for a in listar_carpeta(carpeta, UBICACION_SEGURIDAD) if a.legible]
    borradas = []
    for archivo in copias[COPIAS_SEGURIDAD:]:
        try:
            archivo.ruta.unlink()
            borradas.append(archivo.ruta)
        except OSError:
            pass
    return borradas


def revisiones_conocidas() -> list[str]:
    """Revisiones de Alembic de esta versión del programa, de la más vieja a la nueva."""
    script = ScriptDirectory.from_config(configuracion_alembic())
    return [r.revision for r in reversed(list(script.walk_revisions()))]


def abrir_y_revisar(ruta: Path, clave: str, carpeta: Path) -> Resumen:
    """Descifra la copia, la extrae en `carpeta` y revisa la base (sin tocar los datos
    actuales). Lo usan la restauración, el botón Verificar y `verificar_backup.py`."""
    try:
        archivo = ruta.read_bytes()
    except OSError as e:
        raise ErrorBackup(f"No se pudo leer el archivo de copia: {e}") from e
    _encabezado, contenido = cifrado.descifrar(archivo, clave)
    resumen = paquete.extraer_paquete(contenido, carpeta)
    if not resumen.integra:
        raise ErrorBackup(f"La base de la copia no pasó la revisión de integridad: "
                          f"{resumen.integridad}")
    if not resumen.tiene_datos:
        raise ErrorBackup("La copia no tiene datos (no hay usuarios).")
    return resumen


class ServicioBackups:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        configuracion: ServicioConfiguracion,
        carpeta_datos: Path | None = None,
        reloj: Reloj = ahora_utc,
        protector: ProtectorClave | None = None,
    ):
        self._fabrica = fabrica
        self._configuracion = configuracion
        self._carpeta = carpeta_datos
        self._reloj = reloj
        self._protector = protector
        self._candado = threading.Lock()

    # --- rutas ---------------------------------------------------------------
    @property
    def _motor(self):
        return self._fabrica.kw["bind"]

    def ruta_base(self) -> Path:
        base = self._motor.url.database
        if not base or base == ":memory:":
            raise ErrorBackupNegocio("La base de datos no está en un archivo.")
        return Path(base)

    def carpeta_datos(self) -> Path:
        return self._carpeta or cfg.carpeta_datos()

    def carpeta_local(self) -> Path:
        return self.carpeta_datos() / CARPETA_LOCAL

    def carpeta_seguridad(self) -> Path:
        return self.carpeta_local() / CARPETA_SEGURIDAD

    def _almacen(self) -> AlmacenClave:
        return AlmacenClave(self.carpeta_datos(), self._protector)

    def destino_externo(self) -> Path | None:
        texto = (self._configuracion.obtener("backup_destino") or "").strip()
        return Path(texto) if texto else None

    # --- contraseña ----------------------------------------------------------
    def clave_configurada(self) -> bool:
        return self._almacen().leer() is not None

    def configurar_clave(self, actual: UsuarioActual, clave: str, confirmacion: str) -> None:
        """Crea o cambia la contraseña de backups. Las copias viejas siguen pidiendo la
        contraseña con la que se hicieron."""
        exigir(actual, Permiso.BACKUPS)
        if len(clave) < LONGITUD_MINIMA:
            raise ErrorValidacion(
                f"La contraseña de backups debe tener al menos {LONGITUD_MINIMA} caracteres.")
        if clave != confirmacion:
            raise ErrorValidacion("Las contraseñas no coinciden.")
        habia = self.clave_configurada()
        self._almacen().guardar(clave)
        with self._fabrica() as sesion:
            auditoria.registrar(
                sesion, "backup_clave_cambiada" if habia else "backup_clave_configurada",
                "backups", usuario_id=actual.id, momento=self._reloj())
            sesion.commit()

    def clave_coincide(self, actual: UsuarioActual, clave: str) -> bool:
        exigir(actual, Permiso.BACKUPS)
        return self._almacen().leer() == clave

    # --- destino -------------------------------------------------------------
    def cambiar_destino(self, actual: UsuarioActual, carpeta: Path | str | None) -> None:
        exigir(actual, Permiso.BACKUPS)
        texto = ""
        if carpeta:
            ruta = Path(carpeta)
            ok, motivo = destino_disponible(ruta)
            if not ok:
                raise ErrorValidacion(motivo)
            if ruta.resolve() == self.carpeta_local().resolve():
                raise ErrorValidacion(
                    "Elija una carpeta en el disco externo o USB, no la carpeta del PC.")
            texto = str(ruta)
        self._configuracion.guardar(actual, {"backup_destino": texto})

    # --- estado --------------------------------------------------------------
    def ultima_exitosa(self) -> datetime | None:
        with self._fabrica() as sesion:
            return sesion.scalar(
                select(func.max(BackupLog.fecha_hora)).where(
                    BackupLog.resultado == EXITOSO,
                    BackupLog.tipo.in_((TIPO_AUTOMATICO, TIPO_MANUAL)),
                )
            )

    def estado(self, actual: UsuarioActual) -> EstadoBackups:
        """Lo puede leer cualquier usuario con sesión (aviso de copia vieja al iniciar)."""
        if actual is None:
            raise ErrorPermiso("Debe iniciar sesión para realizar esta acción.")
        destino = self.destino_externo()
        disponible = destino_disponible(destino)[0] if destino else None
        with self._fabrica() as sesion:
            fila = sesion.get(Config, CLAVE_ULTIMA_EXTERNA)
        externa = datetime.fromisoformat(fila.valor) if fila and fila.valor else None
        almacen = self._almacen()
        return EstadoBackups(
            ultima_exitosa=self.ultima_exitosa(),
            clave_configurada=almacen.leer() is not None,
            clave_protegida=almacen.protector.protege_de_verdad,
            destino=str(destino) if destino else "",
            destino_disponible=disponible,
            hora_diaria=self._configuracion.obtener("backup_hora"),
            ultima_copia_externa=externa,
            ahora=self._reloj(),
        )

    def toca_copia_diaria(self) -> bool:
        """True si ya pasó la hora diaria de hoy (Bogotá) y no hay copia buena desde
        entonces. Tras un intento fallido espera una hora para reintentar."""
        ahora = self._reloj()
        local = ahora.astimezone(cfg.ZONA_HORARIA)
        hora = self._configuracion.obtener("backup_hora")
        inicio = datetime.combine(local.date(), time(hour=hora), tzinfo=cfg.ZONA_HORARIA)
        if local < inicio:
            return False
        inicio_utc = inicio.astimezone(ahora.tzinfo)
        with self._fabrica() as sesion:
            buena = sesion.scalar(select(func.count()).select_from(BackupLog).where(
                BackupLog.resultado == EXITOSO,
                BackupLog.tipo.in_((TIPO_AUTOMATICO, TIPO_MANUAL)),
                BackupLog.fecha_hora >= inicio_utc))
            if buena:
                return False
            ultimo_intento = sesion.scalar(select(func.max(BackupLog.fecha_hora)).where(
                BackupLog.tipo == TIPO_AUTOMATICO, BackupLog.fecha_hora >= inicio_utc))
        return (ultimo_intento is None
                or ahora - ultimo_intento >= timedelta(minutes=MINUTOS_REINTENTO))

    # --- hacer copias --------------------------------------------------------
    def preparar(self, actual: UsuarioActual | None, tipo: str = TIPO_MANUAL) -> TareaBackup:
        """Las copias automáticas (al cerrar y diaria) las dispara el sistema para
        cualquier usuario, o sin sesión. La copia manual es solo del administrador."""
        if tipo == TIPO_MANUAL:
            exigir(actual, Permiso.BACKUPS)
        elif tipo != TIPO_AUTOMATICO:
            raise ErrorValidacion("Tipo de copia no válido.")
        clave = self._almacen().leer()
        if clave is None:
            raise ErrorBackupNegocio(
                "Falta configurar la contraseña de las copias de seguridad "
                "(Copias de seguridad → Contraseña).")
        return TareaBackup(
            tipo=tipo, clave=clave, ruta_base=self.ruta_base(),
            carpeta_datos=self.carpeta_datos(), carpeta_local=self.carpeta_local(),
            destino_externo=self.destino_externo(), creado=self._reloj(),
            usuario_id=actual.id if actual else None,
        )

    def ejecutar(self, tarea: TareaBackup) -> ResultadoBackup:
        """Hace la copia. No usa la sesión de SQLAlchemy: se puede llamar en otro hilo."""
        resultado = ResultadoBackup(tipo=tarea.tipo, creado=tarea.creado, exitoso=False,
                                    usuario_id=tarea.usuario_id)
        if not self._candado.acquire(blocking=False):
            resultado.error = "Ya se está haciendo otra copia de seguridad."
            return resultado
        try:
            contenido, resumen = paquete.crear_paquete(tarea.ruta_base, tarea.carpeta_datos)
            resultado.resumen = resumen
            metadatos = {
                "creado_utc": tarea.creado.isoformat(), "tipo": tarea.tipo,
                "revision": resumen.revision, "programa": "Enforma",
                "resumen": {"conteos": resumen.conteos, "fotos": resumen.fotos},
            }
            archivo = cifrado.cifrar(contenido, tarea.clave, metadatos)
            resultado.tamano = len(archivo)
            nombre = nombre_archivo(tarea.creado, tarea.tipo)
            destinos: list[tuple[str, Path | None, str]] = []
            if tarea.tipo == TIPO_SEGURIDAD:
                destinos.append((UBICACION_SEGURIDAD,
                                 tarea.carpeta_local / CARPETA_SEGURIDAD, ""))
            else:
                destinos.append((UBICACION_PC, tarea.carpeta_local, ""))
                if tarea.destino_externo is not None:
                    ok, motivo = destino_disponible(tarea.destino_externo)
                    destinos.append((UBICACION_EXTERNO, tarea.destino_externo if ok else None,
                                     motivo))
            for ubicacion, carpeta, motivo in destinos:
                if carpeta is None:
                    resultado.escrituras.append(EscrituraDestino(
                        ubicacion, tarea.destino_externo, False, motivo))
                    continue
                ruta = carpeta / nombre
                try:
                    _escribir_verificado(archivo, ruta)
                    resultado.escrituras.append(EscrituraDestino(ubicacion, ruta, True))
                except (OSError, ErrorBackup) as e:
                    resultado.escrituras.append(EscrituraDestino(
                        ubicacion, ruta, False, f"No se pudo escribir la copia: {e}"))
                    continue
                if tarea.tipo == TIPO_SEGURIDAD:
                    resultado.borradas += rotar_seguridad(carpeta)
                else:
                    resultado.borradas += rotar_carpeta(carpeta, ubicacion)
            resultado.exitoso = any(e.exitoso for e in resultado.escrituras)
            if not resultado.exitoso:
                resultado.error = "; ".join(resultado.avisos)
        except (ErrorBackup, OSError) as e:
            resultado.error = str(e)
        except Exception as e:  # noqa: BLE001 - nunca debe tumbar el cierre del programa
            resultado.error = f"Error inesperado: {e.__class__.__name__}"
        finally:
            self._candado.release()
        return resultado

    def registrar(self, resultado: ResultadoBackup) -> None:
        """Guarda el resultado en backups_log (una fila por destino) y en la auditoría."""
        with self._fabrica() as sesion:
            usuario_id = resultado.usuario_id
            if usuario_id is not None and sesion.get(Usuario, usuario_id) is None:
                usuario_id = None
            if resultado.escrituras:
                for e in resultado.escrituras:
                    sesion.add(BackupLog(
                        fecha_hora=resultado.creado, tipo=resultado.tipo,
                        ruta=str(e.ruta or "")[:500],
                        tamano_bytes=resultado.tamano if e.exitoso else None,
                        resultado=EXITOSO if e.exitoso else FALLIDO,
                        detalle=(e.detalle or (resultado.resumen.texto()
                                               if resultado.resumen else ""))[:2000],
                    ))
            else:
                sesion.add(BackupLog(fecha_hora=resultado.creado, tipo=resultado.tipo,
                                     ruta="", resultado=FALLIDO, detalle=resultado.error[:2000]))
            auditoria.registrar(
                sesion, "backup_creado" if resultado.exitoso else "backup_fallido", "backups",
                usuario_id=usuario_id, momento=resultado.creado,
                detalle={
                    "tipo": TIPOS.get(resultado.tipo, resultado.tipo),
                    "archivos": [str(r) for r in resultado.rutas],
                    "avisos": resultado.avisos or None,
                    "error": resultado.error or None,
                    "borradas_por_rotacion": len(resultado.borradas) or None,
                },
            )
            sesion.commit()

    def hacer_backup(self, actual: UsuarioActual | None,
                     tipo: str = TIPO_MANUAL) -> ResultadoBackup:
        """Copia completa. Para las automáticas, un fallo al preparar (p. ej. sin
        contraseña) también queda registrado y no lanza error."""
        try:
            tarea = self.preparar(actual, tipo)
        except ErrorBackupNegocio as e:
            if tipo == TIPO_MANUAL:
                raise
            resultado = ResultadoBackup(tipo=tipo, creado=self._reloj(), exitoso=False,
                                        error=str(e), usuario_id=actual.id if actual else None)
            self.registrar(resultado)
            return resultado
        resultado = self.ejecutar(tarea)
        self.registrar(resultado)
        return resultado

    # --- consultas -----------------------------------------------------------
    def listar(self, actual: UsuarioActual) -> list[ArchivoBackup]:
        exigir(actual, Permiso.BACKUPS)
        archivos = listar_carpeta(self.carpeta_local(), UBICACION_PC)
        destino = self.destino_externo()
        if destino and destino_disponible(destino)[0]:
            archivos += listar_carpeta(destino, UBICACION_EXTERNO)
        archivos += listar_carpeta(self.carpeta_seguridad(), UBICACION_SEGURIDAD)
        minimo = datetime.min.replace(tzinfo=ahora_utc().tzinfo)
        return sorted(archivos, key=lambda a: a.creado or minimo, reverse=True)

    def historial(self, actual: UsuarioActual, limite: int = 200) -> list[FilaHistorial]:
        exigir(actual, Permiso.BACKUPS)
        with self._fabrica() as sesion:
            filas = sesion.scalars(select(BackupLog).order_by(
                BackupLog.fecha_hora.desc(), BackupLog.id.desc()).limit(limite)).all()
        return [FilaHistorial(f.fecha_hora, f.tipo, f.ruta, f.tamano_bytes, f.resultado,
                              f.detalle or "") for f in filas]

    # --- tercera copia (fuera del local) ---------------------------------------
    def copiar_a_otro_disco(self, actual: UsuarioActual, carpeta: Path | str) -> Path:
        """Copia la copia buena más reciente a otro disco (el que el dueño se lleva)."""
        exigir(actual, Permiso.BACKUPS)
        carpeta = Path(carpeta)
        ok, motivo = destino_disponible(carpeta)
        if not ok:
            raise ErrorValidacion(motivo)
        normales = [a for a in self.listar(actual)
                    if a.legible and a.tipo in (TIPO_AUTOMATICO, TIPO_MANUAL)]
        if not normales:
            raise ErrorValidacion("Todavía no hay copias para llevar. Haga primero una copia.")
        ultima = normales[0]
        destino = carpeta / ultima.ruta.name
        try:
            if destino.resolve() != ultima.ruta.resolve():
                _escribir_verificado(ultima.ruta.read_bytes(), destino)
        except (OSError, ErrorBackup) as e:
            raise ErrorValidacion(f"No se pudo copiar: {e}") from e
        ahora = self._reloj()
        with self._fabrica() as sesion:
            sesion.merge(Config(clave=CLAVE_ULTIMA_EXTERNA, valor=ahora.isoformat()))
            auditoria.registrar(sesion, "backup_copiado_externo", "backups",
                                usuario_id=actual.id, momento=ahora,
                                detalle={"archivo": str(destino)})
            sesion.commit()
        return destino

    # --- verificar y restaurar -------------------------------------------------
    def verificar(self, actual: UsuarioActual, ruta: Path | str, clave: str) -> Resumen:
        """Abre la copia en una carpeta temporal y la revisa, sin tocar los datos."""
        exigir(actual, Permiso.BACKUPS)
        with tempfile.TemporaryDirectory(prefix="enforma_verificar_") as temporal:
            try:
                return abrir_y_revisar(Path(ruta), clave, Path(temporal))
            except ErrorBackup as e:
                raise ErrorBackupNegocio(str(e)) from e

    def restaurar(self, actual: UsuarioActual, ruta: Path | str, clave: str) -> Resumen:
        """Reemplaza la base, las fotos y el logo por los de la copia.

        Antes hace una copia "antes de restaurar" del estado actual. Si la copia es de
        una versión anterior del programa, actualiza el esquema. Al terminar, la
        interfaz debe cerrar la sesión (los datos cambiaron).
        """
        exigir(actual, Permiso.BACKUPS)
        ruta = Path(ruta)
        with tempfile.TemporaryDirectory(prefix="enforma_restaurar_") as temporal:
            extraido = Path(temporal)
            try:
                resumen = abrir_y_revisar(ruta, clave, extraido)
            except ClaveIncorrecta as e:
                raise ErrorBackupNegocio(str(e)) from e
            except ErrorBackup as e:
                raise ErrorBackupNegocio(f"No se puede restaurar esta copia: {e}") from e
            conocidas = revisiones_conocidas()
            if resumen.revision not in conocidas:
                raise ErrorBackupNegocio(
                    "La copia fue hecha con una versión más nueva del programa. "
                    "Actualice el programa antes de restaurarla.")
            if not self._permiso_vigente(actual):
                raise ErrorPermiso("No tiene permiso para realizar esta acción.")

            # 1. Copia de seguridad del estado actual (con la contraseña guardada o,
            #    si no hay, con la que se escribió para restaurar).
            clave_seguridad = self._almacen().leer() or clave
            seguridad = self.ejecutar(TareaBackup(
                tipo=TIPO_SEGURIDAD, clave=clave_seguridad, ruta_base=self.ruta_base(),
                carpeta_datos=self.carpeta_datos(), carpeta_local=self.carpeta_local(),
                destino_externo=None, creado=self._reloj(), usuario_id=actual.id))
            self.registrar(seguridad)
            if not seguridad.exitoso:
                raise ErrorBackupNegocio(
                    "No se pudo hacer la copia de seguridad previa; no se restauró nada. "
                    f"Detalle: {seguridad.error}")

            # 2. Historial de copias actual (para no perderlo al cambiar la base).
            with self._fabrica() as sesion:
                historial = [
                    dict(fecha_hora=f.fecha_hora, tipo=f.tipo, ruta=f.ruta,
                         tamano_bytes=f.tamano_bytes, resultado=f.resultado, detalle=f.detalle)
                    for f in sesion.scalars(select(BackupLog))
                ]

            # 3. Reemplazar archivos con la base cerrada y actualizar el esquema.
            if not self._candado.acquire(timeout=120):
                raise ErrorBackupNegocio("Hay una copia de seguridad en curso. Intente de nuevo.")
            try:
                self._motor.dispose()
                paquete.reemplazar_datos(extraido, self.ruta_base(), self.carpeta_datos())
                self._motor.dispose()
                actualizar_esquema(self._motor.url.render_as_string(hide_password=False))
            finally:
                self._candado.release()

        # 4. Volver a poner el historial de copias y registrar la restauración.
        ahora = self._reloj()
        with self._fabrica() as sesion:
            existentes = {(f.fecha_hora, f.ruta, f.tipo) for f in sesion.scalars(select(BackupLog))}
            for fila in historial:
                if (fila["fecha_hora"], fila["ruta"], fila["tipo"]) not in existentes:
                    sesion.add(BackupLog(**fila))
            usuario_id = actual.id if sesion.get(Usuario, actual.id) else None
            auditoria.registrar(
                sesion, "backup_restaurado", "backups", usuario_id=usuario_id, momento=ahora,
                detalle={"archivo": str(ruta), "restaurado_por": actual.usuario,
                         "copia_previa": str(seguridad.rutas[0]),
                         "contenido": resumen.texto()},
            )
            sesion.commit()
        return resumen

    def _permiso_vigente(self, actual: UsuarioActual) -> bool:
        """Relee al usuario: si lo desactivaron o le quitaron el rol, no restaura."""
        with self._fabrica() as sesion:
            usuario = sesion.get(Usuario, actual.id)
            return bool(usuario and usuario.activo and usuario.rol == actual.rol)
