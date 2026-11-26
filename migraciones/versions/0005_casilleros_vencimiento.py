"""casilleros: vencimiento propio y pagos ligados a la asignación

Revisión: 0005
Anterior: 0004
Creada: 2026-11-26

El casillero tiene su propio vencimiento, independiente de la membresía
(decisión del dueño en la Fase 5): `casillero_asignaciones.fecha_vencimiento`
es el último día pagado (inclusive). Los pagos de concepto "casillero" pueden
quedar ligados a la asignación que renuevan. Se agrega además un índice por
fecha de liberación para la lista "por día".

Las asignaciones activas que ya existían (datos de prueba) quedan con
vencimiento vacío: la pantalla las muestra como "sin fecha" para que se renueven.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('casillero_asignaciones', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fecha_vencimiento', sa.Date(), nullable=True))
        batch_op.create_index(
            'ix_casillero_asignaciones_fecha_liberacion', ['fecha_liberacion'], unique=False
        )
    with op.batch_alter_table('pagos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('casillero_asignacion_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f('fk_pagos_casillero_asignacion_id_casillero_asignaciones'),
            'casillero_asignaciones', ['casillero_asignacion_id'], ['id'],
        )
        batch_op.create_check_constraint(
            batch_op.f('ck_pagos_casillero_asignacion'),
            "casillero_asignacion_id IS NULL OR concepto = 'casillero'",
        )
        batch_op.create_index(
            'ix_pagos_casillero_asignacion_id', ['casillero_asignacion_id'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('pagos', schema=None) as batch_op:
        batch_op.drop_index('ix_pagos_casillero_asignacion_id')
        batch_op.drop_constraint(batch_op.f('ck_pagos_casillero_asignacion'), type_='check')
        batch_op.drop_constraint(
            batch_op.f('fk_pagos_casillero_asignacion_id_casillero_asignaciones'),
            type_='foreignkey',
        )
        batch_op.drop_column('casillero_asignacion_id')
    with op.batch_alter_table('casillero_asignaciones', schema=None) as batch_op:
        batch_op.drop_index('ix_casillero_asignaciones_fecha_liberacion')
        batch_op.drop_column('fecha_vencimiento')
