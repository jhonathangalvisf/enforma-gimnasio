"""clientes: columna busqueda (nombre normalizado para buscar rápido)

Revisión: 0003
Anterior: 0002
Creada: 2026-11-26

Guarda "nombres apellidos" en minúsculas y sin tildes. La búsqueda por nombre
(«gomez» encuentra «Gómez») usa esta columna y responde en pocos milisegundos
con 12.000 clientes. La calcula el modelo al guardar; aquí se llena para los
clientes que ya existían.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from gimnasio.texto import normalizar

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('busqueda', sa.String(length=170), server_default='', nullable=False)
        )
    conexion = op.get_bind()
    filas = conexion.execute(sa.text("SELECT id, nombres, apellidos FROM clientes")).all()
    if filas:
        conexion.execute(
            sa.text("UPDATE clientes SET busqueda = :busqueda WHERE id = :id"),
            [{"id": f.id, "busqueda": normalizar(f"{f.nombres} {f.apellidos}".strip())}
             for f in filas],
        )


def downgrade() -> None:
    with op.batch_alter_table('clientes', schema=None) as batch_op:
        batch_op.drop_column('busqueda')
