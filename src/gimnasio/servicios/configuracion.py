"""Parámetros del sistema (RF-K1). Se guardan en la tabla `config` como texto.

Cada parámetro tiene tipo, valor por defecto y validación. Leer está permitido a
cualquier usuario con sesión (Recepción necesita, por ejemplo, el umbral de
"por vencer"); cambiar es solo para el administrador y queda en la auditoría.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from gimnasio import config as cfg
from gimnasio.modelos import Config
from gimnasio.servicios import auditoria
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir


@dataclass(frozen=True)
class Parametro:
    clave: str
    etiqueta: str
    tipo: str  # "entero", "texto" u "opcion"
    defecto: Any
    minimo: int | None = None
    maximo: int | None = None
    opciones: tuple[tuple[str, str], ...] = ()  # (valor, etiqueta)
    largo_maximo: int = 200
    ayuda: str = ""
    grupo: str = "General"


PARAMETROS: tuple[Parametro, ...] = (
    Parametro("dias_por_vencer", "Días para avisar \"por vencer\"", "entero",
              cfg.DIAS_POR_VENCER, 1, 60,
              ayuda="La tarjeta de Recepción se pone amarilla cuando faltan estos días o menos.",
              grupo="Membresías y asistencia"),
    Parametro("asistencia_duplicada", "Si el cliente ya ingresó hoy", "opcion", "avisar",
              opciones=(("avisar", "Avisar y pedir confirmación"),
                        ("bloquear", "No permitir un segundo ingreso"),
                        ("permitir", "Registrar sin avisar")),
              grupo="Membresías y asistencia"),
    Parametro("minutos_inactividad", "Cerrar sesión tras minutos sin uso", "entero",
              cfg.MINUTOS_INACTIVIDAD, 1, 240,
              ayuda="No aplica a la pantalla de Recepción, que permanece abierta.",
              grupo="Seguridad"),
    Parametro("intentos_login_max", "Intentos fallidos antes de bloquear", "entero",
              cfg.INTENTOS_LOGIN_MAX, 3, 20, grupo="Seguridad"),
    Parametro("minutos_bloqueo", "Minutos de bloqueo", "entero", 15, 1, 1440,
              grupo="Seguridad"),
    Parametro("gimnasio_nombre", "Nombre del gimnasio", "texto", "Enforma",
              largo_maximo=120, grupo="Datos del gimnasio"),
    Parametro("gimnasio_nit", "NIT", "texto", "", largo_maximo=30, grupo="Datos del gimnasio"),
    Parametro("gimnasio_direccion", "Dirección", "texto", "", largo_maximo=200,
              grupo="Datos del gimnasio"),
    Parametro("gimnasio_telefono", "Teléfono", "texto", "", largo_maximo=40,
              grupo="Datos del gimnasio"),
    Parametro("recibo_prefijo", "Prefijo de recibos", "texto", "R-", largo_maximo=10,
              grupo="Recibos"),
    Parametro("recibo_siguiente", "Siguiente número de recibo", "entero", 1, 1, 999_999_999,
              ayuda="Solo puede aumentar, para no repetir números ya entregados.",
              grupo="Recibos"),
)
POR_CLAVE = {p.clave: p for p in PARAMETROS}
CLAVE_LOGO = "gimnasio_logo"  # nombre del archivo dentro de la carpeta de datos
EXTENSIONES_LOGO = {".png", ".jpg", ".jpeg"}


def _convertir(parametro: Parametro, valor: Any) -> Any:
    """Valida y normaliza un valor. Lanza ErrorValidacion con mensaje claro."""
    if parametro.tipo == "entero":
        try:
            numero = int(str(valor).strip())
        except ValueError:
            raise ErrorValidacion(f"«{parametro.etiqueta}» debe ser un número entero.") from None
        if not parametro.minimo <= numero <= parametro.maximo:
            raise ErrorValidacion(
                f"«{parametro.etiqueta}» debe estar entre {parametro.minimo} y {parametro.maximo}."
            )
        return numero
    if parametro.tipo == "opcion":
        validas = [v for v, _ in parametro.opciones]
        if valor not in validas:
            raise ErrorValidacion(f"Valor no válido para «{parametro.etiqueta}».")
        return valor
    texto = str(valor or "").strip()
    if len(texto) > parametro.largo_maximo:
        raise ErrorValidacion(
            f"«{parametro.etiqueta}» admite máximo {parametro.largo_maximo} caracteres."
        )
    return texto


class ServicioConfiguracion:
    def __init__(self, fabrica: sessionmaker[Session], carpeta_datos: Path | None = None):
        self._fabrica = fabrica
        self._carpeta = carpeta_datos

    # --- lectura -----------------------------------------------------------
    def obtener(self, clave: str, sesion: Session | None = None) -> Any:
        """Valor tipado de un parámetro (o su valor por defecto si no se ha guardado)."""
        parametro = POR_CLAVE[clave]
        if sesion is None:
            with self._fabrica() as s:
                return self.obtener(clave, s)
        guardado = sesion.get(Config, clave)
        if guardado is None or guardado.valor is None:
            return parametro.defecto
        try:
            return _convertir(parametro, guardado.valor)
        except ErrorValidacion:
            return parametro.defecto  # valor dañado: se usa el de fábrica

    def obtener_todos(self) -> dict[str, Any]:
        with self._fabrica() as sesion:
            return {p.clave: self.obtener(p.clave, sesion) for p in PARAMETROS}

    def ruta_logo(self) -> Path | None:
        with self._fabrica() as sesion:
            fila = sesion.get(Config, CLAVE_LOGO)
        if not fila or not fila.valor:
            return None
        ruta = self._carpeta_datos() / fila.valor
        return ruta if ruta.exists() else None

    # --- escritura ---------------------------------------------------------
    def guardar(self, actual: UsuarioActual, cambios: dict[str, Any]) -> dict[str, Any]:
        """Valida todo antes de guardar; si algo falla no se guarda nada.

        Devuelve solo los parámetros que realmente cambiaron.
        """
        exigir(actual, Permiso.CONFIGURACION)
        desconocidas = set(cambios) - set(POR_CLAVE)
        if desconocidas:
            raise ErrorValidacion(f"Parámetros desconocidos: {', '.join(sorted(desconocidas))}.")
        nuevos = {clave: _convertir(POR_CLAVE[clave], v) for clave, v in cambios.items()}
        with self._fabrica() as sesion:
            diferencias = {}
            for clave, valor in nuevos.items():
                anterior = self.obtener(clave, sesion)
                if anterior == valor:
                    continue
                if clave == "recibo_siguiente" and valor < anterior:
                    raise ErrorValidacion(
                        "El siguiente número de recibo no puede ser menor que el actual "
                        f"({anterior}): se repetirían recibos."
                    )
                diferencias[clave] = {"antes": anterior, "despues": valor}
                sesion.merge(Config(clave=clave, valor=str(valor)))
            if diferencias:
                auditoria.registrar(
                    sesion, "configuracion_cambiada", "config",
                    usuario_id=actual.id, detalle=diferencias,
                )
                sesion.commit()
            return {k: v["despues"] for k, v in diferencias.items()}

    def guardar_logo(self, actual: UsuarioActual, ruta_origen: Path | None) -> Path | None:
        """Copia el logo a la carpeta de datos (o lo quita si `ruta_origen` es None)."""
        exigir(actual, Permiso.CONFIGURACION)
        destino = None
        nombre = None
        if ruta_origen is not None:
            ruta_origen = Path(ruta_origen)
            extension = ruta_origen.suffix.lower()
            if extension not in EXTENSIONES_LOGO:
                raise ErrorValidacion("El logo debe ser una imagen PNG o JPG.")
            if not ruta_origen.is_file():
                raise ErrorValidacion("No se encontró el archivo del logo.")
            if ruta_origen.stat().st_size > 2 * 1024 * 1024:
                raise ErrorValidacion("El logo no debe pesar más de 2 MB.")
            nombre = f"logo{extension}"
            destino = self._carpeta_datos() / nombre
            shutil.copyfile(ruta_origen, destino)
        with self._fabrica() as sesion:
            sesion.merge(Config(clave=CLAVE_LOGO, valor=nombre))
            auditoria.registrar(
                sesion, "configuracion_cambiada", "config", usuario_id=actual.id,
                detalle={CLAVE_LOGO: "actualizado" if nombre else "eliminado"},
            )
            sesion.commit()
        return destino

    def _carpeta_datos(self) -> Path:
        return self._carpeta or cfg.carpeta_datos()
