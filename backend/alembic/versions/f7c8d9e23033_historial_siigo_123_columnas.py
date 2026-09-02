"""historial siigo 123 columnas\n\nRevision ID: f7c8d9e23033\nRevises: e5b7a6c41022\nCreate Date: 2026-08-25 17:45:00.000000\n"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "f7c8d9e23033"
down_revision: Union[str, None] = "e5b7a6c41022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("historial_tecnico_siigo", sa.Column("descripcion_secuencia", sa.String(length=500), nullable=True))
    op.add_column("historial_tecnico_siigo", sa.Column("valores_columnas_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("historial_tecnico_siigo", "valores_columnas_json")
    op.drop_column("historial_tecnico_siigo", "descripcion_secuencia")
