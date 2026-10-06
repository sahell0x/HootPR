"""pre-merge results, linked issues, issue + PR embeddings (phase 5)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list[sa.Column[object]]:
    return [
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
    ]


def _fk(table: str, col: str, ref: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], [f"{ref}.id"], name=op.f(f"fk_{table}_{col}_{ref}"), ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "pre_merge_results",
        *_base(),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("review_id", sa.Uuid(), nullable=True),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("ignored", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("ignored_by", sa.String(length=255), nullable=True),
        _fk("pre_merge_results", "pr_id", "pull_requests", "CASCADE"),
        _fk("pre_merge_results", "review_id", "reviews", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pre_merge_results")),
    )
    op.create_index(
        "ix_pre_merge_results_pr_sha", "pre_merge_results", ["pr_id", "head_sha"], unique=False
    )
    op.create_table(
        "issue_links",
        *_base(),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("issue_repo", sa.String(length=512), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("assessment", sa.String(length=16), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        _fk("issue_links", "pr_id", "pull_requests", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_links")),
        sa.UniqueConstraint(
            "pr_id",
            "issue_repo",
            "issue_number",
            name=op.f("uq_issue_links_pr_id_issue_repo_issue_number"),
        ),
    )
    op.create_table(
        "issue_embeddings",
        *_base(),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        _fk("issue_embeddings", "org_id", "organizations", "CASCADE"),
        _fk("issue_embeddings", "repo_id", "repositories", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue_embeddings")),
        sa.UniqueConstraint(
            "repo_id", "issue_number", name=op.f("uq_issue_embeddings_repo_id_issue_number")
        ),
    )
    op.create_index("ix_issue_embeddings_org", "issue_embeddings", ["org_id"], unique=False)
    op.create_table(
        "pr_embeddings",
        *_base(),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("repo_id", sa.Uuid(), nullable=False),
        sa.Column("pr_id", sa.Uuid(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("embedding_model", sa.String(length=128), nullable=True),
        _fk("pr_embeddings", "org_id", "organizations", "CASCADE"),
        _fk("pr_embeddings", "repo_id", "repositories", "CASCADE"),
        _fk("pr_embeddings", "pr_id", "pull_requests", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pr_embeddings")),
        sa.UniqueConstraint("pr_id", name=op.f("uq_pr_embeddings_pr_id")),
    )
    op.create_index(
        "ix_pr_embeddings_org_repo", "pr_embeddings", ["org_id", "repo_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_pr_embeddings_org_repo", table_name="pr_embeddings")
    op.drop_table("pr_embeddings")
    op.drop_index("ix_issue_embeddings_org", table_name="issue_embeddings")
    op.drop_table("issue_embeddings")
    op.drop_table("issue_links")
    op.drop_index("ix_pre_merge_results_pr_sha", table_name="pre_merge_results")
    op.drop_table("pre_merge_results")
