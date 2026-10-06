"""Remote MCP servers registered by org admins (spec §10.4)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class McpServer(IdMixin, TimestampMixin, Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (UniqueConstraint("org_id", "name"),)
    org_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # Short identifier used in tool names: mcp__<name>__<tool>.
    name: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(2048))
    # Fernet-encrypted JSON object of HTTP headers (e.g. Authorization); never returned by the API.
    headers_enc: Mapped[str | None] = mapped_column(Text)
    # Explicit allowlist of tool names exposed to agents; empty exposes nothing.
    allowed_tools: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Last discovery result: [{"name", "description"}].
    discovered_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
