"""invitados: búsqueda por nombre, eliminación con autor y autorización por límite

Revisión: 0006
Anterior: 0005
Creada: 2026-11-26

Fase 6 (Invitados):
- `invitados.busqueda`: nombre en minúsculas y sin tildes («jose» encuentra «José»).
  La calcula el modelo al guardar; aquí se llena para los invitados que ya existían.
- `invitado_asistencias.eliminada_por` y `eliminada_en`: quién y cuándo anuló una
  visita (igual que en asistencias de clientes).
- `invitado_asistencias.autorizada_por`: administrador que autorizó una visita por
  encima del límite mensual (parámetro `invitado_visitas_mes`; 0 = sin límite).
- Índice por cliente anfitrión para el reporte de invitados por anfitrión.

El número de visitas no se guarda: se cuenta desde invitado_asistencias (RN-10).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from gimnasio.texto import normalizar

revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('invitados', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('busqueda', sa.String(length=160), server_default='', nullable=False)
        )
    with op.batch_alter_table('invitado_asistencias', schema=None) as batch_op:
        batch_op.add_column(sa.Column('eliminada_por', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('eliminada_en', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('autorizada_por', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f('fk_invitado_asistencias_eliminada_por_usuarios'),
            'usuarios', ['eliminada_por'], ['id'],
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_invitado_asistencias_autorizada_por_usuarios'),
            'usuarios', ['autorizada_por'], ['id'],
        )
        batch_op.create_index(
            'ix_invitado_asistencias_cliente_anfitrion_id', ['cliente_anfitrion_id'],
            unique=False,
        )
    conexion = op.get_bind()
    filas = conexion.execute(sa.text("SELECT id, nombre FROM invitados")).all()
    if filas:
        conexion.execute(
            sa.text("UPDATE invitados SET busqueda = :busqueda WHERE id = :id"),
            [{"id": f.id, "busqueda": normalizar(f.nombre)} for f in filas],
        )


def downgrade() -> None:
    with op.batch_alter_table('invitado_asistencias', schema=None) as batch_op:
        batch_op.drop_index('ix_invitado_asistencias_cliente_anfitrion_id')
        batch_op.drop_constraint(
            batch_op.f('fk_invitado_asistencias_autorizada_por_usuarios'), type_='foreignkey'
        )
        batch_op.drop_constraint(
            batch_op.f('fk_invitado_asistencias_eliminada_por_usuarios'), type_='foreignkey'
        )
        batch_op.drop_column('autorizada_por')
        batch_op.drop_column('eliminada_en')
        batch_op.drop_column('eliminada_por')
    with op.batch_alter_table('invitados', schema=None) as batch_op:
        batch_op.drop_column('busqueda')
