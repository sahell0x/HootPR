"""security scans: attack surface maps + security architecture reviews (phase 6)

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_scans",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("trigger", sa.String(length=16), server_default="dashboard", nullable=False),
        sa.Column("requested_by", sa.String(length=255), server_default="", nullable=False),
        sa.Column("pr_id", sa.Uuid(), nullable=True),
        sa.Column("chat_message_id", sa.Uuid(), nullable=True),
        sa.Column("branch", sa.String(length=255), server_default="", nullable=False),
        sa.Column("commit_sha", sa.String(length=64), server_default="", nullable=False),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "credits_charged", sa.Numeric(precision=8, scale=2), server_default="0", nullable=False
        ),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_security_scans_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"],
            ["repositories.id"],
            name=op.f("fk_security_scans_repo_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"],
            ["pull_requests.id"],
            name=op.f("fk_security_scans_pr_id_pull_requests"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_messages.id"],
            name=op.f("fk_security_scans_chat_message_id_chat_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_scans")),
    )
    op.create_index(
        "ix_security_scans_repo_kind_created",
        "security_scans",
        ["repo_id", "kind", "created_at"],
    )
    op.create_index("ix_security_scans_org_created", "security_scans", ["org_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_security_scans_org_created", table_name="security_scans")
    op.drop_index("ix_security_scans_repo_kind_created", table_name="security_scans")
    op.drop_table("security_scans")
