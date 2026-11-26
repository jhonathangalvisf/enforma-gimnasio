"""pagos: un recibo puede tener varios conceptos (mensualidad + casillero)

Revisión: 0008
Anterior: 0007
Creada: 2026-11-26

Cuando el cliente paga la mensualidad y el casillero al mismo tiempo se entrega un
solo recibo: los dos pagos comparten el número (consecutivo). Por eso el índice
único pasa de `consecutivo` a `(consecutivo, concepto)`: un recibo tiene como
máximo un renglón de cada concepto y dos recibos distintos nunca comparten número.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_pagos_consecutivo', table_name='pagos')
    op.create_index('ix_pagos_consecutivo_concepto', 'pagos', ['consecutivo', 'concepto'],
                    unique=True)


def downgrade() -> None:
    # Solo funciona si ningún recibo tiene dos conceptos.
    op.drop_index('ix_pagos_consecutivo_concepto', table_name='pagos')
    op.create_index('ix_pagos_consecutivo', 'pagos', ['consecutivo'], unique=True)
