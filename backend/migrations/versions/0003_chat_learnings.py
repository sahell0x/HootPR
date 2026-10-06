"""chat messages, learnings, PR blocking state (phase 3)

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column[object]]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("provider_comment_id", sa.String(length=64), nullable=False),
        sa.Column("thread_ref", sa.String(length=128), nullable=True),
        sa.Column("author_username", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("command", sa.String(length=64), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("reply_comment_id", sa.String(length=64), nullable=True),
        sa.Column(
            "credits_charged", sa.Numeric(precision=8, scale=2), server_default="0", nullable=False
        ),
        sa.Column("status", sa.String(length=16), server_default="received", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_chat_messages_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"],
            ["pull_requests.id"],
            name=op.f("fk_chat_messages_pr_id_pull_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        sa.UniqueConstraint(
            "pr_id",
            "provider_comment_id",
            name=op.f("uq_chat_messages_pr_id_provider_comment_id"),
        ),
    )
    op.create_index(op.f("ix_chat_messages_org_id"), "chat_messages", ["org_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_pr_id"), "chat_messages", ["pr_id"], unique=False)
    op.create_table(
        "learnings",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("path_glob", sa.String(length=512), nullable=True),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("created_by_username", sa.String(length=255), nullable=False),
        sa.Column("chat_message_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_learnings_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"],
            ["repositories.id"],
            name=op.f("fk_learnings_repo_id_repositories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["chat_message_id"],
            ["chat_messages.id"],
            name=op.f("fk_learnings_chat_message_id_chat_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learnings")),
    )
    op.create_index("ix_learnings_org_repo", "learnings", ["org_id", "repo_id"], unique=False)
    op.add_column(
        "pull_requests",
        sa.Column("blocking_state", sa.String(length=24), server_default="none", nullable=False),
    )
    op.create_index(op.f("ix_llm_calls_chat_id"), "llm_calls", ["chat_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_llm_calls_chat_id"), table_name="llm_calls")
    op.drop_column("pull_requests", "blocking_state")
    op.drop_index("ix_learnings_org_repo", table_name="learnings")
    op.drop_table("learnings")
    op.drop_index(op.f("ix_chat_messages_pr_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_org_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
