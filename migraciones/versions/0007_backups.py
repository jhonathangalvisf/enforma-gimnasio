"""backups: tipo "seguridad", resultado controlado e índice por fecha

Revisión: 0007
Anterior: 0006
Creada: 2026-11-26

Fase 9 (Backups):
- `backups_log.tipo` acepta además "seguridad": la copia automática que se hace
  justo antes de restaurar otra.
- `backups_log.resultado` solo puede ser "exitoso" o "fallido".
- Índice por `fecha_hora` para encontrar rápido la última copia buena (aviso de
  "más de 2 días" al iniciar).

La tabla estaba vacía hasta esta fase; los valores antiguos no se tocan.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def _columnas() -> list[sa.Column]:
    return [
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fecha_hora', sa.DateTime(), nullable=False),
        sa.Column('tipo', sa.String(length=10), nullable=False),
        sa.Column('ruta', sa.String(length=500), nullable=False),
        sa.Column('tamano_bytes', sa.Integer(), nullable=True),
        sa.Column('resultado', sa.String(length=20), nullable=False),
        sa.Column('detalle', sa.Text(), nullable=True),
    ]


_TABLA_ANTERIOR = sa.Table(
    'backups_log', sa.MetaData(), *_columnas(),
    sa.CheckConstraint("tipo IN ('automatico','manual')", name='ck_backups_log_tipo'),
)


def upgrade() -> None:
    # SQLite no cambia un CHECK en su lugar: el modo batch recrea la tabla. Se le pasa
    # la definición anterior para que copie el CHECK con su nombre y lo pueda quitar.
    with op.batch_alter_table('backups_log', copy_from=_TABLA_ANTERIOR) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_backups_log_tipo'), type_='check')
        batch_op.create_check_constraint(
            batch_op.f('ck_backups_log_tipo'), "tipo IN ('automatico','manual','seguridad')"
        )
        batch_op.create_check_constraint(
            batch_op.f('ck_backups_log_resultado'), "resultado IN ('exitoso','fallido')"
        )
        batch_op.create_index('ix_backups_log_fecha_hora', ['fecha_hora'], unique=False)


def downgrade() -> None:
    op.execute("DELETE FROM backups_log WHERE tipo = 'seguridad'")
    op.drop_index('ix_backups_log_fecha_hora', table_name='backups_log')
    tabla_nueva = sa.Table(
        'backups_log', sa.MetaData(),
        *_columnas(),
        sa.CheckConstraint("tipo IN ('automatico','manual','seguridad')",
                           name='ck_backups_log_tipo'),
        sa.CheckConstraint("resultado IN ('exitoso','fallido')",
                           name='ck_backups_log_resultado'),
    )
    with op.batch_alter_table('backups_log', copy_from=tabla_nueva) as batch_op:
        batch_op.drop_constraint(batch_op.f('ck_backups_log_resultado'), type_='check')
        batch_op.drop_constraint(batch_op.f('ck_backups_log_tipo'), type_='check')
        batch_op.create_check_constraint(
            batch_op.f('ck_backups_log_tipo'), "tipo IN ('automatico','manual')"
        )
