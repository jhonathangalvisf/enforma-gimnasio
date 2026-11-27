"""config: precio sugerido del casillero en $1

Revisión: 0011
Anterior: 0010
Creada: 2026-11-27

Solo cambia datos, no tablas. Igual que los planes, el casillero se cobra con un precio
simbólico de $1 (en el recibo importa qué se pagó; el gimnasio sabe cuánto vale). Si una
base guardó el precio sugerido en $0 («sin precio sugerido»), queda en $1. Si el
administrador ya puso otro precio, no se toca. Las bases que nunca lo guardaron toman
el nuevo valor por defecto ($1) sin necesidad de esta migración.
"""
import json
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

config = sa.table('config', sa.column('clave', sa.String), sa.column('valor', sa.Text))
auditoria = sa.table(
    'auditoria',
    sa.column('fecha_hora', sa.DateTime), sa.column('accion', sa.String),
    sa.column('entidad', sa.String), sa.column('detalle_json', sa.Text),
)


def upgrade() -> None:
    conexion = op.get_bind()
    resultado = conexion.execute(
        config.update()
        .where(config.c.clave == 'casillero_precio', sa.func.trim(config.c.valor) == '0')
        .values(valor='1')
    )
    if resultado.rowcount:
        conexion.execute(auditoria.insert().values(
            fecha_hora=datetime.now(timezone.utc).replace(tzinfo=None),
            accion="configuracion_cambiada", entidad="config",
            detalle_json=json.dumps({"casillero_precio": {"antes": 0, "despues": 1}}),
        ))


def downgrade() -> None:
    # Solo datos: no se deshace.
    pass
