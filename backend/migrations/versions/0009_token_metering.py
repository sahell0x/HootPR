"""token-metered credits: llm_calls.stage + llm_calls.credits (docs/token-metered-billing.md)

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("stage", sa.String(length=32), nullable=True))
    op.add_column("llm_calls", sa.Column("credits", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "credits")
    op.drop_column("llm_calls", "stage")
