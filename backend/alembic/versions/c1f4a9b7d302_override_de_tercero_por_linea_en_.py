"""override de tercero por linea en movimiento (nomina multilinea)

Revision ID: c1f4a9b7d302
Revises: 8e58af736006
Create Date: 2026-08-20 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1f4a9b7d302'
down_revision: Union[str, None] = '8e58af736006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('movimientos', sa.Column('tercero_nit_override', sa.String(length=30), nullable=True))
    op.add_column('movimientos', sa.Column('tercero_nombre_override', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('movimientos', 'tercero_nombre_override')
    op.drop_column('movimientos', 'tercero_nit_override')
