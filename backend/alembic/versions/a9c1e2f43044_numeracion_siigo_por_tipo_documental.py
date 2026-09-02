"""numeracion siigo por tipo documental

Revision ID: a9c1e2f43044
Revises: f7c8d9e23033
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a9c1e2f43044"
down_revision: Union[str, None] = "f7c8d9e23033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "configuraciones_comprobante_siigo",
        sa.Column("modo_numeracion", sa.String(length=20), nullable=False, server_default="interna"),
    )


def downgrade() -> None:
    op.drop_column("configuraciones_comprobante_siigo", "modo_numeracion")
