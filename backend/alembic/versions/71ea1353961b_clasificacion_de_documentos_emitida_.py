"""clasificacion de documentos: emitida-recibida, notas credito, nomina, documento equivalente

Revision ID: 71ea1353961b
Revises: 5e8c6d4846ff
Create Date: 2026-08-12 20:06:44.521130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71ea1353961b'
down_revision: Union[str, None] = '5e8c6d4846ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default en las columnas NOT NULL: la base ya puede tener
    # filas reales (facturas y cargas ya procesadas) — sin un valor por
    # defecto, agregar una columna NOT NULL fallaría contra esas filas
    # existentes en PostgreSQL.
    op.add_column('cargas_documentos_dian',
                   sa.Column('total_pendientes_clasificacion', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('cargas_documentos_dian',
                   sa.Column('total_descartados', sa.Integer(), nullable=False, server_default='0'))

    op.add_column('facturas',
                   sa.Column('naturaleza_documento', sa.String(length=30), nullable=False, server_default='factura'))
    op.add_column('facturas',
                   sa.Column('direccion_documento', sa.String(length=20), nullable=False, server_default='recibida'))

    # batch_alter_table: SQLite no soporta agregar restricciones de llave
    # foránea con ALTER TABLE directo (sí PostgreSQL/Neon) — el modo por
    # lotes de Alembic funciona correctamente en ambos motores.
    with op.batch_alter_table('empresas') as batch_op:
        batch_op.add_column(sa.Column('cuenta_ingresos_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_clientes_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_iva_generado_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_nomina_id', sa.String(length=36), nullable=True))
        batch_op.create_foreign_key('fk_empresa_cuenta_ingresos', 'cuentas_contables', ['cuenta_ingresos_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_clientes', 'cuentas_contables', ['cuenta_clientes_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_iva_generado', 'cuentas_contables', ['cuenta_iva_generado_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_nomina', 'cuentas_contables', ['cuenta_nomina_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('empresas') as batch_op:
        batch_op.drop_constraint('fk_empresa_cuenta_nomina', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_iva_generado', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_clientes', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_ingresos', type_='foreignkey')
        batch_op.drop_column('cuenta_nomina_id')
        batch_op.drop_column('cuenta_iva_generado_id')
        batch_op.drop_column('cuenta_clientes_id')
        batch_op.drop_column('cuenta_ingresos_id')

    op.drop_column('facturas', 'direccion_documento')
    op.drop_column('facturas', 'naturaleza_documento')
    op.drop_column('cargas_documentos_dian', 'total_descartados')
    op.drop_column('cargas_documentos_dian', 'total_pendientes_clasificacion')
