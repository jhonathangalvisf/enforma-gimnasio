"""Ayuda integrada (sección 3.9).

El contenido vive en archivos Markdown, uno por módulo, dentro de `gimnasio/ayuda/`.
Se puede corregir el texto sin tocar la lógica: basta editar el archivo. Este servicio
no usa la base de datos; solo filtra los temas según el rol y busca palabras.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gimnasio.rutas import carpeta_ayuda
from gimnasio.servicios.errores import ErrorValidacion
from gimnasio.servicios.permisos import Permiso, UsuarioActual, exigir
from gimnasio.texto import normalizar

CARPETA_AYUDA = carpeta_ayuda()
TEMA_INICIO = "inicio"
ESQUEMA_ENLACE = "tema"  # los enlaces entre temas se escriben [Texto](tema:clave)


@dataclass(frozen=True)
class DefinicionTema:
    clave: str  # también es el nombre del archivo: <clave>.md
    titulo: str
    permiso: Permiso  # quién ve el tema (el mismo permiso que abre el módulo)


TEMAS: tuple[DefinicionTema, ...] = (
    DefinicionTema(TEMA_INICIO, "Primeros pasos y atajos", Permiso.AYUDA),
    DefinicionTema("recepcion", "Recepción", Permiso.REGISTRAR_ASISTENCIA),
    DefinicionTema("clientes", "Clientes", Permiso.VER_CLIENTES),
    DefinicionTema("asistencia", "Asistencia", Permiso.REGISTRAR_ASISTENCIA),
    DefinicionTema("casilleros", "Casilleros", Permiso.ASIGNAR_CASILLERO),
    DefinicionTema("invitados", "Invitados", Permiso.REGISTRAR_INVITADOS),
    DefinicionTema("pagos", "Pagos, membresías y caja", Permiso.REGISTRAR_PAGOS),
    DefinicionTema("reportes", "Reportes", Permiso.REPORTES_BASICOS),
    DefinicionTema("configuracion", "Configuración", Permiso.CONFIGURACION),
    DefinicionTema("usuarios", "Usuarios", Permiso.USUARIOS),
    DefinicionTema("backups", "Copias de seguridad", Permiso.BACKUPS),
)
POR_CLAVE = {t.clave: t for t in TEMAS}


@dataclass(frozen=True)
class Tema:
    clave: str
    titulo: str


@dataclass(frozen=True)
class ResultadoBusqueda:
    clave: str
    titulo: str
    coincidencias: int
    fragmento: str  # texto corto alrededor de la primera coincidencia


def texto_plano(markdown: str) -> str:
    """Quita las marcas de Markdown más comunes para buscar y mostrar fragmentos."""
    texto = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown)  # enlaces: deja el texto
    texto = re.sub(r"^\s*[#>|-]+\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"[*_`|]", "", texto)
    texto = re.sub(r"-{3,}", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def palabras(consulta: str) -> list[str]:
    return [p for p in normalizar(consulta).split() if p]


class ServicioAyuda:
    def __init__(self, carpeta: Path | None = None):
        self._carpeta = carpeta or CARPETA_AYUDA
        self._cache: dict[str, str] = {}

    # --- lectura --------------------------------------------------------------
    def temas(self, actual: UsuarioActual) -> list[Tema]:
        """Temas que este usuario puede ver, en el orden del menú."""
        exigir(actual, Permiso.AYUDA)
        return [Tema(t.clave, t.titulo) for t in TEMAS if actual.puede(t.permiso)]

    def puede_ver(self, actual: UsuarioActual, clave: str) -> bool:
        tema = POR_CLAVE.get(clave)
        return tema is not None and actual.puede(Permiso.AYUDA) and actual.puede(tema.permiso)

    def contenido(self, actual: UsuarioActual, clave: str) -> str:
        """Markdown del tema. Si el usuario no puede verlo, se rechaza."""
        exigir(actual, Permiso.AYUDA)
        tema = POR_CLAVE.get(clave)
        if tema is None:
            raise ErrorValidacion(f"No existe el tema de ayuda «{clave}».")
        exigir(actual, tema.permiso)
        return self._leer(clave)

    def tema_contextual(self, actual: UsuarioActual, clave: str | None) -> str:
        """Tema para F1: el del módulo si el usuario lo puede ver; si no, Primeros pasos."""
        if clave and self.puede_ver(actual, clave):
            return clave
        return TEMA_INICIO

    # --- búsqueda -------------------------------------------------------------
    def buscar(self, actual: UsuarioActual, consulta: str) -> list[ResultadoBusqueda]:
        """Temas que contienen todas las palabras (sin importar tildes ni mayúsculas).
        Primero los que más veces las contienen; el título cuenta más."""
        buscadas = palabras(consulta)
        temas = self.temas(actual)
        if not buscadas:
            return []
        resultados = []
        for tema in temas:
            plano = texto_plano(self._leer(tema.clave))
            normal = normalizar(plano)
            titulo = normalizar(tema.titulo)
            if not all(p in normal or p in titulo for p in buscadas):
                continue
            veces = sum(normal.count(p) for p in buscadas)
            veces_titulo = sum(titulo.count(p) for p in buscadas)
            resultados.append((veces + 10 * veces_titulo, ResultadoBusqueda(
                tema.clave, tema.titulo, veces, _fragmento(plano, normal, buscadas[0]))))
        resultados.sort(key=lambda r: (-r[0], TEMAS.index(POR_CLAVE[r[1].clave])))
        return [r for _, r in resultados]

    # --- interno --------------------------------------------------------------
    def _leer(self, clave: str) -> str:
        if clave not in self._cache:
            ruta = self._carpeta / f"{clave}.md"
            try:
                self._cache[clave] = ruta.read_text(encoding="utf-8")
            except OSError as e:
                raise ErrorValidacion(
                    f"No se encontró el archivo de ayuda «{ruta.name}». Reinstale el programa."
                ) from e
        return self._cache[clave]


def _fragmento(plano: str, normal: str, palabra: str, ancho: int = 70) -> str:
    """`normalizar` conserva la longitud del texto en español (solo quita tildes),
    así que la posición encontrada en `normal` sirve en `plano`."""
    pos = normal.find(palabra)
    if pos < 0 or len(normal) != len(plano):
        return plano[: ancho * 2] + ("…" if len(plano) > ancho * 2 else "")
    inicio, fin = max(0, pos - ancho), min(len(plano), pos + len(palabra) + ancho)
    return ("…" if inicio else "") + plano[inicio:fin].strip() + ("…" if fin < len(plano) else "")
