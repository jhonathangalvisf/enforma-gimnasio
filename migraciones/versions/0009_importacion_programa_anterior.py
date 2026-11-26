"""invitados: visitas traídas del programa anterior

Revisión: 0009
Anterior: 0008
Creada: 2026-11-26

El programa anterior solo guardaba, por invitado, cuántas veces vino y las fechas de
la primera y la última visita. Al importarlo, esas dos fechas se guardan como visitas
normales y las demás (sin fecha conocida) quedan en `visitas_anteriores`, que se suma
al contador total del invitado. No cuentan para el límite del mes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invitados') as tabla:
        tabla.add_column(sa.Column('visitas_anteriores', sa.Integer(), nullable=False,
                                   server_default='0'))


def downgrade() -> None:
    with op.batch_alter_table('invitados') as tabla:
        tabla.drop_column('visitas_anteriores')
