"""reglas cuentas control aprendizaje

Revision ID: c7a1f2b63055
Revises: b6d8e1f54044
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c7a1f2b63055"
down_revision: Union[str, None] = "b6d8e1f54044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reglas_cuentas_control",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("empresa_id", sa.String(length=36), nullable=False),
        sa.Column("rol", sa.String(length=40), nullable=False),
        sa.Column("direccion_documento", sa.String(length=20), nullable=True),
        sa.Column("naturaleza_documento", sa.String(length=40), nullable=True),
        sa.Column("cuenta_principal_codigo", sa.String(length=30), nullable=True),
        sa.Column("tercero_nit", sa.String(length=30), nullable=True),
        sa.Column("cuenta_control_id", sa.String(length=36), nullable=False),
        sa.Column("usos", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("origen", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["cuenta_control_id"], ["cuentas_contables.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "rol", "direccion_documento", "naturaleza_documento", "cuenta_principal_codigo", "tercero_nit", name="uq_regla_cuenta_control_contexto"),
    )
    op.create_index("ix_reglas_cuentas_control_empresa_id", "reglas_cuentas_control", ["empresa_id"], unique=False)
    op.create_index("ix_reglas_cuentas_control_rol", "reglas_cuentas_control", ["rol"], unique=False)
    op.create_index("ix_reglas_cuentas_control_cuenta_principal_codigo", "reglas_cuentas_control", ["cuenta_principal_codigo"], unique=False)
    op.create_index("ix_reglas_cuentas_control_tercero_nit", "reglas_cuentas_control", ["tercero_nit"], unique=False)
    op.create_index("ix_regla_control_busqueda", "reglas_cuentas_control", ["empresa_id", "rol", "cuenta_principal_codigo", "tercero_nit"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_regla_control_busqueda", table_name="reglas_cuentas_control")
    op.drop_index("ix_reglas_cuentas_control_tercero_nit", table_name="reglas_cuentas_control")
    op.drop_index("ix_reglas_cuentas_control_cuenta_principal_codigo", table_name="reglas_cuentas_control")
    op.drop_index("ix_reglas_cuentas_control_rol", table_name="reglas_cuentas_control")
    op.drop_index("ix_reglas_cuentas_control_empresa_id", table_name="reglas_cuentas_control")
    op.drop_table("reglas_cuentas_control")
