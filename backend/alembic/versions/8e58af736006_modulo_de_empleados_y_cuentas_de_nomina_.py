"""modulo de empleados y cuentas de nomina configurables

Revision ID: 8e58af736006
Revises: a23b3db42855
Create Date: 2026-08-19 19:21:17.204217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e58af736006'
down_revision: Union[str, None] = 'a23b3db42855'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'empleados',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('nit', sa.String(length=30), nullable=False),
        sa.Column('nombre', sa.String(length=200), nullable=True),
        sa.Column('eps_nit', sa.String(length=30), nullable=True),
        sa.Column('eps_nombre', sa.String(length=200), nullable=True),
        sa.Column('afp_nit', sa.String(length=30), nullable=True),
        sa.Column('afp_nombre', sa.String(length=200), nullable=True),
        sa.Column('arl_nit', sa.String(length=30), nullable=True),
        sa.Column('arl_nombre', sa.String(length=200), nullable=True),
        sa.Column('caja_compensacion_nit', sa.String(length=30), nullable=True),
        sa.Column('caja_compensacion_nombre', sa.String(length=200), nullable=True),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('empresa_id', 'nit', name='uq_empleado_empresa_nit'),
    )
    op.create_index('ix_empleado_empresa_nit', 'empleados', ['empresa_id', 'nit'], unique=False)
    op.create_index(op.f('ix_empleados_empresa_id'), 'empleados', ['empresa_id'], unique=False)

    op.add_column('facturas', sa.Column('nomina_detalle_json', sa.Text(), nullable=True))

    with op.batch_alter_table('empresas') as batch_op:
        batch_op.add_column(sa.Column('cuenta_salario_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_auxilio_transporte_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_nomina_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_salud_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_pension_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_cesantias_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_cesantias_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_intereses_cesantias_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_intereses_cesantias_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_prima_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_prima_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_vacaciones_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_vacaciones_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_arl_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_arl_por_pagar_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_caja_compensacion_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('cuenta_caja_compensacion_por_pagar_id', sa.String(length=36), nullable=True))

        batch_op.create_foreign_key('fk_empresa_cuenta_salario', 'cuentas_contables', ['cuenta_salario_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_auxtte', 'cuentas_contables', ['cuenta_auxilio_transporte_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_nom_pagar', 'cuentas_contables', ['cuenta_nomina_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_salud_pagar', 'cuentas_contables', ['cuenta_salud_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_pension_pagar', 'cuentas_contables', ['cuenta_pension_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_cesantias', 'cuentas_contables', ['cuenta_cesantias_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_cesantias_pagar', 'cuentas_contables', ['cuenta_cesantias_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_intcesantias', 'cuentas_contables', ['cuenta_intereses_cesantias_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_intcesantias_pagar', 'cuentas_contables', ['cuenta_intereses_cesantias_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_prima', 'cuentas_contables', ['cuenta_prima_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_prima_pagar', 'cuentas_contables', ['cuenta_prima_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_vacaciones', 'cuentas_contables', ['cuenta_vacaciones_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_vacaciones_pagar', 'cuentas_contables', ['cuenta_vacaciones_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_arl', 'cuentas_contables', ['cuenta_arl_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_arl_pagar', 'cuentas_contables', ['cuenta_arl_por_pagar_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_caja', 'cuentas_contables', ['cuenta_caja_compensacion_id'], ['id'])
        batch_op.create_foreign_key('fk_empresa_cuenta_caja_pagar', 'cuentas_contables', ['cuenta_caja_compensacion_por_pagar_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('empresas') as batch_op:
        batch_op.drop_constraint('fk_empresa_cuenta_caja_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_caja', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_arl_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_arl', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_vacaciones_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_vacaciones', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_prima_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_prima', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_intcesantias_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_intcesantias', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_cesantias_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_cesantias', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_pension_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_salud_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_nom_pagar', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_auxtte', type_='foreignkey')
        batch_op.drop_constraint('fk_empresa_cuenta_salario', type_='foreignkey')

        batch_op.drop_column('cuenta_caja_compensacion_por_pagar_id')
        batch_op.drop_column('cuenta_caja_compensacion_id')
        batch_op.drop_column('cuenta_arl_por_pagar_id')
        batch_op.drop_column('cuenta_arl_id')
        batch_op.drop_column('cuenta_vacaciones_por_pagar_id')
        batch_op.drop_column('cuenta_vacaciones_id')
        batch_op.drop_column('cuenta_prima_por_pagar_id')
        batch_op.drop_column('cuenta_prima_id')
        batch_op.drop_column('cuenta_intereses_cesantias_por_pagar_id')
        batch_op.drop_column('cuenta_intereses_cesantias_id')
        batch_op.drop_column('cuenta_cesantias_por_pagar_id')
        batch_op.drop_column('cuenta_cesantias_id')
        batch_op.drop_column('cuenta_pension_por_pagar_id')
        batch_op.drop_column('cuenta_salud_por_pagar_id')
        batch_op.drop_column('cuenta_nomina_por_pagar_id')
        batch_op.drop_column('cuenta_auxilio_transporte_id')
        batch_op.drop_column('cuenta_salario_id')

    op.drop_column('facturas', 'nomina_detalle_json')

    op.drop_index(op.f('ix_empleados_empresa_id'), table_name='empleados')
    op.drop_index('ix_empleado_empresa_nit', table_name='empleados')
    op.drop_table('empleados')
