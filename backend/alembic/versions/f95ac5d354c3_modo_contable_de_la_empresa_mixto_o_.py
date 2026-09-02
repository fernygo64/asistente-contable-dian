"""modo contable de la empresa (mixto o solo gastos)

Revision ID: f95ac5d354c3
Revises: 2ef9a9818925
Create Date: 2026-08-14 19:16:56.280423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f95ac5d354c3'
down_revision: Union[str, None] = '2ef9a9818925'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default: las empresas ya existentes en producción deben
    # quedar en "mixto" (el comportamiento de siempre) sin intervención.
    op.add_column('empresas', sa.Column('modo_contable', sa.String(length=20), nullable=False, server_default='mixto'))


def downgrade() -> None:
    op.drop_column('empresas', 'modo_contable')
