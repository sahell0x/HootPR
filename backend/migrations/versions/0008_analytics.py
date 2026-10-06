"""reports, report runs, audit logs, api keys, change stack chat (phase 8)

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _updated() -> sa.Column[object]:
    return sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _fk(table: str, col: str, ref: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{ref}.id"], name=op.f(f"fk_{table}_{col}_{ref}"), ondelete=ondelete
    )


def _jsonb(name: str, default: str = "{}") -> sa.Column[object]:
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def _arr(name: str, length: int) -> sa.Column[object]:
    return sa.Column(
        name, postgresql.ARRAY(sa.String(length=length)), server_default="{}", nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), server_default="", nullable=False),
        sa.Column("schedule", sa.String(length=16), server_default="weekly", nullable=False),
        sa.Column("hour_utc", sa.Integer(), server_default="9", nullable=False),
        sa.Column("weekday", sa.Integer(), server_default="0", nullable=False),
        _arr("repo_ids", 64),
        _arr("email_to", 320),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        _created(),
        _updated(),
        _fk("reports", "org_id", "organizations", "CASCADE"),
        _fk("reports", "created_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
    )
    op.create_index(op.f("ix_reports_org_id"), "reports", ["org_id"])
    op.create_index(op.f("ix_reports_next_run_at"), "reports", ["next_run_at"])

    op.create_table(
        "report_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), server_default="", nullable=False),
        sa.Column("trigger", sa.String(length=16), server_default="custom", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        _arr("repo_ids", 64),
        sa.Column("content", sa.Text(), nullable=True),
        _jsonb("metrics"),
        sa.Column("degraded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        _arr("emailed_to", 320),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _updated(),
        _fk("report_runs", "org_id", "organizations", "CASCADE"),
        _fk("report_runs", "report_id", "reports", "SET NULL"),
        _fk("report_runs", "created_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_runs")),
    )
    op.create_index(op.f("ix_report_runs_org_id"), "report_runs", ["org_id"])
    op.create_index(op.f("ix_report_runs_report_id"), "report_runs", ["report_id"])
    op.create_index("ix_report_runs_org_created", "report_runs", ["org_id", "created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_label", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=True),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        _jsonb("details"),
        _created(),
        _fk("audit_logs", "org_id", "organizations", "CASCADE"),
        _fk("audit_logs", "actor_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"])
    op.create_index("ix_audit_logs_org_created", "audit_logs", ["org_id", "created_at"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _updated(),
        _fk("api_keys", "org_id", "organizations", "CASCADE"),
        _fk("api_keys", "created_by_user_id", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("key_hash", name=op.f("uq_api_keys_key_hash")),
    )
    op.create_index(op.f("ix_api_keys_org_id"), "api_keys", ["org_id"])

    op.create_table(
        "change_stack_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=True),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="completed", nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "credits_charged", sa.Numeric(precision=8, scale=2), server_default="0", nullable=False
        ),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created(),
        _updated(),
        _fk("change_stack_messages", "org_id", "organizations", "CASCADE"),
        _fk("change_stack_messages", "pr_id", "pull_requests", "CASCADE"),
        _fk("change_stack_messages", "user_id", "users", "SET NULL"),
        _fk("change_stack_messages", "question_id", "change_stack_messages", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_stack_messages")),
    )
    op.create_index(op.f("ix_change_stack_messages_org_id"), "change_stack_messages", ["org_id"])
    op.create_index(
        "ix_change_stack_messages_pr_created", "change_stack_messages", ["pr_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("change_stack_messages")
    op.drop_table("api_keys")
    op.drop_table("audit_logs")
    op.drop_table("report_runs")
    op.drop_table("reports")
