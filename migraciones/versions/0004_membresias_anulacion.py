"""membresías: datos de anulación; pagos: índice por membresía

Revisión: 0004
Anterior: 0003
Creada: 2026-11-26

Las membresías no se borran: se anulan con motivo, usuario y fecha (RN-07).
Las que ya estaban anuladas sin motivo (datos de prueba) reciben un motivo
genérico para cumplir la nueva restricción. El índice `ix_pagos_membresia_id`
acelera el cálculo del saldo pendiente de cada membresía.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('membresias', schema=None) as batch_op:
        batch_op.add_column(sa.Column('motivo_anulacion', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('anulada_por', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('anulada_en', sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE membresias SET motivo_anulacion = 'Anulada antes de registrar motivos' "
        "WHERE estado = 'anulada' AND (motivo_anulacion IS NULL OR trim(motivo_anulacion) = '')"
    )
    with op.batch_alter_table('membresias', schema=None) as batch_op:
        batch_op.create_foreign_key(
            batch_op.f('fk_membresias_anulada_por_usuarios'), 'usuarios', ['anulada_por'], ['id']
        )
        batch_op.create_check_constraint(
            batch_op.f('ck_membresias_motivo_anulacion'),
            "estado = 'activa' OR (motivo_anulacion IS NOT NULL AND trim(motivo_anulacion) <> '')",
        )
    with op.batch_alter_table('pagos', schema=None) as batch_op:
        batch_op.create_index('ix_pagos_membresia_id', ['membresia_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('pagos', schema=None) as batch_op:
        batch_op.drop_index('ix_pagos_membresia_id')
    with op.batch_alter_table('membresias', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_membresias_motivo_anulacion'), type_='check')
        batch_op.drop_constraint(batch_op.f('fk_membresias_anulada_por_usuarios'), type_='foreignkey')
        batch_op.drop_column('anulada_en')
        batch_op.drop_column('anulada_por')
        batch_op.drop_column('motivo_anulacion')
