"""usuarios roles y acceso multiempresa

Revision ID: b6d8e1f54044
Revises: a9c1e2f43044
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "b6d8e1f54044"
down_revision: Union[str, None] = "a9c1e2f43044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usuarios",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("es_superadmin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("intentos_fallidos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bloqueado_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_acceso", sa.DateTime(timezone=True), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_usuario_email"),
    )
    op.create_index("ix_usuarios_email", "usuarios", ["email"], unique=False)

    op.create_table(
        "usuarios_empresas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("usuario_id", sa.String(length=36), nullable=False),
        sa.Column("empresa_id", sa.String(length=36), nullable=False),
        sa.Column("rol", sa.String(length=30), nullable=False, server_default="auxiliar"),
        sa.Column("permisos_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresas.id"]),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usuario_id", "empresa_id", name="uq_usuario_empresa"),
    )
    op.create_index("ix_usuarios_empresas_usuario_id", "usuarios_empresas", ["usuario_id"], unique=False)
    op.create_index("ix_usuarios_empresas_empresa_id", "usuarios_empresas", ["empresa_id"], unique=False)
    op.create_index("ix_usuario_empresa_activo", "usuarios_empresas", ["usuario_id", "empresa_id", "activo"], unique=False)

    op.create_table(
        "configuracion_aplicacion",
        sa.Column("clave", sa.String(length=100), nullable=False),
        sa.Column("valor", sa.Text(), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("clave"),
    )


def downgrade() -> None:
    op.drop_table("configuracion_aplicacion")
    op.drop_index("ix_usuario_empresa_activo", table_name="usuarios_empresas")
    op.drop_index("ix_usuarios_empresas_empresa_id", table_name="usuarios_empresas")
    op.drop_index("ix_usuarios_empresas_usuario_id", table_name="usuarios_empresas")
    op.drop_table("usuarios_empresas")
    op.drop_index("ix_usuarios_email", table_name="usuarios")
    op.drop_table("usuarios")
