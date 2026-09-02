"""historial tecnico siigo automatico

Revision ID: e5b7a6c41022
Revises: d4c9e8a77101
Create Date: 2026-08-25 15:35:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e5b7a6c41022"
down_revision: Union[str, None] = "d4c9e8a77101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historial_tecnico_siigo",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("empresa_id", sa.String(length=36), nullable=False),
        sa.Column("importacion_id", sa.String(length=36), nullable=True),
        sa.Column("cuenta_codigo", sa.String(length=30), nullable=False),
        sa.Column("nit", sa.String(length=30), nullable=True),
        sa.Column("tipo_comprobante", sa.String(length=20), nullable=True),
        sa.Column("codigo_comprobante", sa.String(length=20), nullable=True),
        sa.Column("numero_documento", sa.String(length=60), nullable=True),
        sa.Column("codigo_vendedor", sa.String(length=20), nullable=True),
        sa.Column("codigo_ciudad", sa.String(length=20), nullable=True),
        sa.Column("codigo_zona", sa.String(length=20), nullable=True),
        sa.Column("centro_costo", sa.String(length=30), nullable=True),
        sa.Column("subcentro_costo", sa.String(length=30), nullable=True),
        sa.Column("sucursal", sa.String(length=20), nullable=True),
        sa.Column("fecha_documento", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fila_origen", sa.Integer(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["importacion_id"], ["importaciones_historico.id"]),
    )
    op.create_index(op.f("ix_historial_tecnico_siigo_empresa_id"), "historial_tecnico_siigo", ["empresa_id"])
    op.create_index(op.f("ix_historial_tecnico_siigo_importacion_id"), "historial_tecnico_siigo", ["importacion_id"])
    op.create_index(op.f("ix_historial_tecnico_siigo_cuenta_codigo"), "historial_tecnico_siigo", ["cuenta_codigo"])
    op.create_index(op.f("ix_historial_tecnico_siigo_nit"), "historial_tecnico_siigo", ["nit"])
    op.create_index("ix_hist_siigo_cuenta_nit", "historial_tecnico_siigo", ["empresa_id", "cuenta_codigo", "nit"])
    op.create_index(
        "ix_hist_siigo_cuenta_comp", "historial_tecnico_siigo",
        ["empresa_id", "cuenta_codigo", "tipo_comprobante", "codigo_comprobante"],
    )


def downgrade() -> None:
    op.drop_index("ix_hist_siigo_cuenta_comp", table_name="historial_tecnico_siigo")
    op.drop_index("ix_hist_siigo_cuenta_nit", table_name="historial_tecnico_siigo")
    op.drop_index(op.f("ix_historial_tecnico_siigo_nit"), table_name="historial_tecnico_siigo")
    op.drop_index(op.f("ix_historial_tecnico_siigo_cuenta_codigo"), table_name="historial_tecnico_siigo")
    op.drop_index(op.f("ix_historial_tecnico_siigo_importacion_id"), table_name="historial_tecnico_siigo")
    op.drop_index(op.f("ix_historial_tecnico_siigo_empresa_id"), table_name="historial_tecnico_siigo")
    op.drop_table("historial_tecnico_siigo")
