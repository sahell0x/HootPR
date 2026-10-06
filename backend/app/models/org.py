from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("provider", "provider_org_id"),)
    provider: Mapped[str] = mapped_column(String(16))
    provider_org_id: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # org | group | personal
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    credits_balance: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0"), server_default="0"
    )
    purchases_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    knowledge_base_opt_out: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # admin | member | billing_admin
    # True once a HootPR admin set the role (PATCH /members); provider re-syncs then keep it.
    role_manual: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Installation(IdMixin, TimestampMixin, Base):
    __tablename__ = "installations"
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    github_installation_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    gitlab_bot_user_id: Mapped[int | None] = mapped_column(BigInteger)
    gitlab_bot_username: Mapped[str | None] = mapped_column(String(255))
    gitlab_bot_token_enc: Mapped[str | None] = mapped_column(Text)
    gitlab_whole_group: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # active | suspended | revoked
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")


class Repository(IdMixin, TimestampMixin, Base):
    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("provider", "provider_repo_id"),)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("installations.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(String(16))
    provider_repo_id: Mapped[str] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(255), default="main", server_default="main")
    private: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    gitlab_hook_id: Mapped[int | None] = mapped_column(BigInteger)
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)
