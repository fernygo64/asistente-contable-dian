"""siigo persistencia exportacion por destino

Revision ID: d4c9e8a77101
Revises: c1f4a9b7d302
Create Date: 2026-08-25 14:40:00.000000
"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa

revision: str = 'd4c9e8a77101'
down_revision: Union[str, None] = 'c1f4a9b7d302'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('plantillas_exportacion') as batch:
        batch.add_column(sa.Column('version_formato', sa.Integer(), nullable=False, server_default='1'))
        batch.add_column(sa.Column('plantilla_origen_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_plantilla_origen', 'plantillas_exportacion', ['plantilla_origen_id'], ['id'])
    op.execute("UPDATE plantillas_exportacion SET actualizado_en = creado_en WHERE actualizado_en IS NULL")

    op.create_table(
        'configuraciones_comprobante_siigo',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('tipo_documento', sa.String(length=40), nullable=False),
        sa.Column('tipo_comprobante', sa.String(length=20), nullable=True),
        sa.Column('codigo_comprobante', sa.String(length=20), nullable=True),
        sa.Column('codigo_vendedor_default', sa.String(length=20), nullable=True),
        sa.Column('codigo_ciudad_default', sa.String(length=20), nullable=True),
        sa.Column('codigo_zona_default', sa.String(length=20), nullable=True),
        sa.Column('centro_costo_default', sa.String(length=30), nullable=True),
        sa.Column('subcentro_costo_default', sa.String(length=30), nullable=True),
        sa.Column('sucursal_default', sa.String(length=20), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
        sa.UniqueConstraint('empresa_id', 'tipo_documento', name='uq_cfg_siigo_empresa_tipo_doc'),
    )
    op.create_index('ix_cfg_siigo_empresa_tipo_doc', 'configuraciones_comprobante_siigo', ['empresa_id', 'tipo_documento'])
    op.create_index(op.f('ix_configuraciones_comprobante_siigo_empresa_id'), 'configuraciones_comprobante_siigo', ['empresa_id'])

    op.create_table(
        'consecutivos_siigo',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('tipo_comprobante', sa.String(length=20), nullable=False),
        sa.Column('codigo_comprobante', sa.String(length=20), nullable=False),
        sa.Column('ultimo_consecutivo_usado', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
        sa.UniqueConstraint('empresa_id', 'tipo_comprobante', 'codigo_comprobante', name='uq_consecutivo_siigo'),
    )
    op.create_index('ix_consecutivo_siigo_clave', 'consecutivos_siigo', ['empresa_id', 'tipo_comprobante', 'codigo_comprobante'])
    op.create_index(op.f('ix_consecutivos_siigo_empresa_id'), 'consecutivos_siigo', ['empresa_id'])

    op.create_table(
        'parametrizaciones_cuenta_siigo',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('cuenta_id', sa.String(length=36), nullable=False),
        sa.Column('maneja_tercero', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('nit_tecnico_exportacion', sa.String(length=30), nullable=True, server_default='0'),
        sa.Column('codigo_vendedor', sa.String(length=20), nullable=True),
        sa.Column('codigo_ciudad', sa.String(length=20), nullable=True),
        sa.Column('codigo_zona', sa.String(length=20), nullable=True),
        sa.Column('centro_costo', sa.String(length=30), nullable=True),
        sa.Column('subcentro_costo', sa.String(length=30), nullable=True),
        sa.Column('sucursal', sa.String(length=20), nullable=True),
        sa.Column('activa', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
        sa.ForeignKeyConstraint(['cuenta_id'], ['cuentas_contables.id']),
        sa.UniqueConstraint('empresa_id', 'cuenta_id', name='uq_param_cuenta_siigo'),
    )
    op.create_index('ix_param_cuenta_siigo_empresa', 'parametrizaciones_cuenta_siigo', ['empresa_id', 'cuenta_id'])
    op.create_index(op.f('ix_parametrizaciones_cuenta_siigo_empresa_id'), 'parametrizaciones_cuenta_siigo', ['empresa_id'])
    op.create_index(op.f('ix_parametrizaciones_cuenta_siigo_cuenta_id'), 'parametrizaciones_cuenta_siigo', ['cuenta_id'])

    op.create_table(
        'exportaciones_facturas',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('empresa_id', sa.String(length=36), nullable=False),
        sa.Column('exportacion_id', sa.String(length=36), nullable=True),
        sa.Column('factura_id', sa.String(length=36), nullable=False),
        sa.Column('sistema_contable', sa.String(length=20), nullable=False),
        sa.Column('tipo_comprobante', sa.String(length=20), nullable=True),
        sa.Column('codigo_comprobante', sa.String(length=20), nullable=True),
        sa.Column('numero_documento', sa.String(length=60), nullable=True),
        sa.Column('usuario', sa.String(length=120), nullable=True),
        sa.Column('creado_en', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['empresas.id']),
        sa.ForeignKeyConstraint(['exportacion_id'], ['exportaciones.id']),
        sa.ForeignKeyConstraint(['factura_id'], ['facturas.id']),
        sa.UniqueConstraint('exportacion_id', 'factura_id', name='uq_exportacion_factura'),
    )
    op.create_index('ix_exp_factura_destino', 'exportaciones_facturas', ['empresa_id', 'factura_id', 'sistema_contable'])
    op.create_index(op.f('ix_exportaciones_facturas_empresa_id'), 'exportaciones_facturas', ['empresa_id'])
    op.create_index(op.f('ix_exportaciones_facturas_exportacion_id'), 'exportaciones_facturas', ['exportacion_id'])
    op.create_index(op.f('ix_exportaciones_facturas_factura_id'), 'exportaciones_facturas', ['factura_id'])

    # Compatibilidad histórica: las exportaciones generadas existentes marcan su destino,
    # para que no vuelvan a ofrecer las mismas facturas automáticamente al mismo software.
    bind = op.get_bind()
    filas = bind.execute(sa.text(
        "SELECT id, empresa_id, sistema_contable, usuario, facturas_incluidas_json, creado_en "
        "FROM exportaciones WHERE estado = 'generada'"
    )).mappings().all()
    for e in filas:
        try:
            ids = json.loads(e['facturas_incluidas_json'] or '[]')
        except Exception:
            ids = []
        for factura_id in ids:
            bind.execute(sa.text(
                "INSERT INTO exportaciones_facturas "
                "(id, empresa_id, exportacion_id, factura_id, sistema_contable, usuario, creado_en) "
                "VALUES (:id,:empresa_id,:exportacion_id,:factura_id,:sistema,:usuario,:creado_en)"
            ), {
                'id': str(uuid.uuid4()), 'empresa_id': e['empresa_id'], 'exportacion_id': e['id'],
                'factura_id': factura_id, 'sistema': e['sistema_contable'], 'usuario': e['usuario'],
                'creado_en': e['creado_en'],
            })


def downgrade() -> None:
    op.drop_index(op.f('ix_exportaciones_facturas_factura_id'), table_name='exportaciones_facturas')
    op.drop_index(op.f('ix_exportaciones_facturas_exportacion_id'), table_name='exportaciones_facturas')
    op.drop_index(op.f('ix_exportaciones_facturas_empresa_id'), table_name='exportaciones_facturas')
    op.drop_index('ix_exp_factura_destino', table_name='exportaciones_facturas')
    op.drop_table('exportaciones_facturas')

    op.drop_index(op.f('ix_parametrizaciones_cuenta_siigo_cuenta_id'), table_name='parametrizaciones_cuenta_siigo')
    op.drop_index(op.f('ix_parametrizaciones_cuenta_siigo_empresa_id'), table_name='parametrizaciones_cuenta_siigo')
    op.drop_index('ix_param_cuenta_siigo_empresa', table_name='parametrizaciones_cuenta_siigo')
    op.drop_table('parametrizaciones_cuenta_siigo')

    op.drop_index(op.f('ix_consecutivos_siigo_empresa_id'), table_name='consecutivos_siigo')
    op.drop_index('ix_consecutivo_siigo_clave', table_name='consecutivos_siigo')
    op.drop_table('consecutivos_siigo')

    op.drop_index(op.f('ix_configuraciones_comprobante_siigo_empresa_id'), table_name='configuraciones_comprobante_siigo')
    op.drop_index('ix_cfg_siigo_empresa_tipo_doc', table_name='configuraciones_comprobante_siigo')
    op.drop_table('configuraciones_comprobante_siigo')

    with op.batch_alter_table('plantillas_exportacion') as batch:
        batch.drop_constraint('fk_plantilla_origen', type_='foreignkey')
        batch.drop_column('actualizado_en')
        batch.drop_column('plantilla_origen_id')
        batch.drop_column('version_formato')
