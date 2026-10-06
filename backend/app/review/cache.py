"""Review cache (spec §11.4, plan Q9): code graph + tool results per (repo, sha), 7-day TTL."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker
from uuid_utils.compat import uuid7

from app.logging import get_logger
from app.models import ReviewCacheEntry
from app.models.base import utcnow

log = get_logger(__name__)


class ReviewCache(Protocol):
    def get(self, sha: str, kind: str, key: str) -> Any | None: ...
    def put(self, sha: str, kind: str, key: str, payload: Any) -> None: ...
    def put_raw(self, sha: str, kind: str, key: str, json_text: str) -> None:
        """Store an already-serialized JSON document (no re-serialization of big payloads)."""
        ...


class NullCache:
    def get(self, sha: str, kind: str, key: str) -> Any | None:
        return None

    def put(self, sha: str, kind: str, key: str, payload: Any) -> None:
        return None

    def put_raw(self, sha: str, kind: str, key: str, json_text: str) -> None:
        return None


def cache_key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


class SqlReviewCache:
    """Never raises: a cache problem only costs a recomputation."""

    def __init__(
        self, session_factory: sessionmaker[Session], repo_id: UUID, *, max_bytes: int = 8_000_000
    ) -> None:
        self._sf, self._repo, self._max = session_factory, repo_id, max_bytes

    def get(self, sha: str, kind: str, key: str) -> Any | None:
        try:
            with self._sf() as s:
                blob = s.execute(
                    select(ReviewCacheEntry.payload_gz).where(
                        ReviewCacheEntry.repo_id == self._repo,
                        ReviewCacheEntry.sha == sha,
                        ReviewCacheEntry.kind == kind,
                        ReviewCacheEntry.cache_key == key,
                    )
                ).scalar_one_or_none()
            return None if blob is None else json.loads(gzip.decompress(blob))
        except Exception:
            log.exception("review_cache_get_failed")
            return None

    def put(self, sha: str, kind: str, key: str, payload: Any) -> None:
        try:
            text = json.dumps(payload, separators=(",", ":"))
        except (TypeError, ValueError):
            log.exception("review_cache_put_failed")
            return
        self.put_raw(sha, kind, key, text)

    def put_raw(self, sha: str, kind: str, key: str, json_text: str) -> None:
        try:
            blob = gzip.compress(json_text.encode())
            if len(blob) > self._max:
                return
            now = utcnow()
            with self._sf() as s:
                stmt = insert(ReviewCacheEntry).values(
                    id=uuid7(),
                    repo_id=self._repo,
                    sha=sha,
                    kind=kind,
                    cache_key=key,
                    payload_gz=blob,
                    created_at=now,
                    updated_at=now,
                )
                s.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["repo_id", "sha", "kind", "cache_key"],
                        set_={"payload_gz": blob, "updated_at": now},
                    )
                )
                s.commit()
        except Exception:
            log.exception("review_cache_put_failed")


def purge_review_cache(s: Session, *, ttl_days: int, now: datetime) -> int:
    res = s.execute(
        delete(ReviewCacheEntry).where(ReviewCacheEntry.created_at < now - timedelta(days=ttl_days))
    )
    return int(getattr(res, "rowcount", 0) or 0)
