"""casilleros: zonas del gimnasio (1 al 411)

Revisión: 0010
Anterior: 0009
Creada: 2026-11-27

Solo cambia datos, no tablas. Aplica una vez la distribución del gimnasio a las bases
que ya tienen casilleros (por ejemplo, las importadas del programa anterior):

- Mujeres: 1 al 49 y 276 al 294.
- Hombres: 50 al 110, 251 al 275 y 307 al 328.
- Mixtos: el resto hasta el 411.

Se corrige la zona de los casilleros con número del 1 al 411 (sin importar si se
escribieron «15» o «015») y se crean los que falten. No se libera a nadie: quien ocupe
un casillero de la otra zona lo conserva y la lista de Casilleros lo marca «fuera de
su zona». Una base sin casilleros no se toca: la aplicación crea los 411 al arrancar.

Los rangos se copian aquí (y no se importan del código) para que esta migración no
cambie si algún día se cambia la distribución.
"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOTAL = 411
RANGOS = {
    "mujeres": ((1, 49), (276, 294)),
    "hombres": ((50, 110), (251, 275), (307, 328)),
}

casilleros = sa.table(
    'casilleros',
    sa.column('id', sa.Integer), sa.column('numero', sa.String),
    sa.column('zona', sa.String), sa.column('estado', sa.String),
)
auditoria = sa.table(
    'auditoria',
    sa.column('fecha_hora', sa.DateTime), sa.column('accion', sa.String),
    sa.column('entidad', sa.String), sa.column('detalle_json', sa.Text),
)


def _zona(numero: int) -> str:
    for zona, rangos in RANGOS.items():
        if any(desde <= numero <= hasta for desde, hasta in rangos):
            return zona
    return "mixto"


def upgrade() -> None:
    conexion = op.get_bind()
    filas = conexion.execute(sa.select(casilleros.c.id, casilleros.c.numero,
                                       casilleros.c.zona)).all()
    if not filas:
        return
    existentes: set[int] = set()
    cambiados = 0
    for id_, numero, zona in filas:
        sin_ceros = (numero or "").lstrip("0") or "0"
        if not sin_ceros.isdigit():
            continue
        n = int(sin_ceros)
        if not 1 <= n <= TOTAL:
            continue
        existentes.add(n)
        correcta = _zona(n)
        if zona != correcta:
            conexion.execute(casilleros.update().where(casilleros.c.id == id_)
                             .values(zona=correcta))
            cambiados += 1
    usados = {numero for _, numero, _ in filas}
    nuevos = [
        {"numero": f"{n:03d}", "zona": _zona(n), "estado": "disponible"}
        for n in range(1, TOTAL + 1)
        if n not in existentes and f"{n:03d}" not in usados
    ]
    if nuevos:
        conexion.execute(casilleros.insert(), nuevos)
    if cambiados or nuevos:
        conexion.execute(auditoria.insert().values(
            fecha_hora=datetime.now(timezone.utc).replace(tzinfo=None),
            accion="casilleros_zonas_gimnasio", entidad="casilleros",
            detalle_json=json.dumps({"zona_corregida": cambiados, "creados": len(nuevos)},
                                    ensure_ascii=False),
        ))


def downgrade() -> None:
    # Solo datos: no se deshace (las zonas anteriores no se guardaron).
    pass
