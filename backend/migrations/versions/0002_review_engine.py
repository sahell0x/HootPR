"""review engine (phase 2)

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column(
            "stages", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "review_tasks",
        sa.Column(
            "focus", postgresql.ARRAY(sa.String(length=32)), server_default="{}", nullable=False
        ),
    )
    op.add_column(
        "review_tasks",
        sa.Column(
            "related_symbols", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
    )
    op.add_column("review_tasks", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "findings",
        sa.Column(
            "evidence", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.create_table(
        "review_cache",
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("payload_gz", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"],
            ["repositories.id"],
            name=op.f("fk_review_cache_repo_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_cache")),
        sa.UniqueConstraint(
            "repo_id",
            "sha",
            "kind",
            "cache_key",
            name=op.f("uq_review_cache_repo_id_sha_kind_cache_key"),
        ),
    )
    op.create_index("ix_review_cache_created", "review_cache", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_review_cache_created", table_name="review_cache")
    op.drop_table("review_cache")
    op.drop_column("findings", "evidence")
    op.drop_column("review_tasks", "summary")
    op.drop_column("review_tasks", "related_symbols")
    op.drop_column("review_tasks", "focus")
    op.drop_column("reviews", "stages")
