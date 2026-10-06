"""finishing-touch jobs (phase 4)

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finishing_jobs",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("chat_message_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("recipe_name", sa.String(length=64), nullable=True),
        sa.Column("trigger", sa.String(length=16), server_default="command", nullable=False),
        sa.Column("delivery", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("requested_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("head_sha", sa.String(length=64), server_default="", nullable=False),
        sa.Column("result_sha", sa.String(length=64), nullable=True),
        sa.Column("result_pr_number", sa.Integer(), nullable=True),
        sa.Column("result_url", sa.String(length=1024), nullable=True),
        sa.Column("verification", sa.String(length=16), server_default="not_run", nullable=False),
        sa.Column("verification_detail", sa.Text(), nullable=True),
        sa.Column("files_changed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "credits_charged", sa.Numeric(precision=8, scale=2), server_default="0", nullable=False
        ),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
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
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_finishing_jobs_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"],
            ["pull_requests.id"],
            name=op.f("fk_finishing_jobs_pr_id_pull_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_messages.id"],
            name=op.f("fk_finishing_jobs_chat_message_id_chat_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_finishing_jobs")),
    )
    op.create_index(
        "ix_finishing_jobs_pr_created", "finishing_jobs", ["pr_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_finishing_jobs_org_created", "finishing_jobs", ["org_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_finishing_jobs_org_created", table_name="finishing_jobs")
    op.drop_index("ix_finishing_jobs_pr_created", table_name="finishing_jobs")
    op.drop_table("finishing_jobs")
