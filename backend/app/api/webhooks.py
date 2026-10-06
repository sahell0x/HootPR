"""Webhook ingestion (spec §6.5): verify before parsing, dedupe, normalize, enqueue, fast ack.

No platform API call happens in the request path. Invalid signatures get ``401`` and leave no
delivery row; a repeated delivery id gets ``200 duplicate``; accepted events ``202 queued``. If
the side effect (enqueue, Razorpay fulfillment) fails, the delivery row is not kept and the
response is ``503`` so the provider's retry is processed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid_utils.compat import uuid7

from app.billing.ledger import CreditLedger
from app.billing.razorpay import verify_webhook_signature
from app.billing.service import FulfillResult, fulfill
from app.crypto import DecryptionError
from app.deps import CryptoDep, Db, SettingsDep, get_queue
from app.errors import api_error
from app.events.models import PlatformEvent, event_adapter
from app.logging import get_logger
from app.models import Repository, WebhookDelivery
from app.models.base import utcnow
from app.platforms.github import webhooks as gh
from app.platforms.gitlab import webhooks as gl
from app.worker.queue import TaskQueue

router = APIRouter()
log = get_logger(__name__)
Queue = Annotated[TaskQueue, Depends(get_queue)]
RAZORPAY_FULFILL_EVENTS = ("payment.captured", "order.paid")
_MAX_ID = 100  # delivery_id column is 128 chars incl. the "<provider>:" prefix


def _reject(provider: str, reason: str) -> HTTPException:
    log.warning("webhook_rejected", provider=provider, reason=reason)
    return api_error(401, "invalid_signature", "Webhook signature verification failed")


def _loads(body: bytes) -> dict[str, Any]:
    try:
        data = json.loads(body)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _delivery_id(candidate: str | None, body: bytes) -> str:
    if not candidate:
        return hashlib.sha256(body).hexdigest()
    return (
        candidate if len(candidate) <= _MAX_ID else hashlib.sha256(candidate.encode()).hexdigest()
    )


async def _record(
    db: Db,
    provider: str,
    delivery_id: str,
    event: str,
    action: str | None,
    status: str,
    *,
    commit: bool = True,
) -> UUID | None:
    """Insert the delivery row; ``None`` when this delivery id was already seen."""
    now = utcnow()
    stmt = (
        insert(WebhookDelivery)
        .values(
            id=uuid7(),
            created_at=now,
            updated_at=now,
            provider=provider,
            delivery_id=f"{provider}:{delivery_id}",
            event=event[:64],
            action=action[:64] if action else None,
            status=status,
        )
        .on_conflict_do_nothing(index_elements=["delivery_id"])
        .returning(WebhookDelivery.id)
    )
    row_id: UUID | None = (await db.execute(stmt)).scalar_one_or_none()
    if commit:
        await db.commit()
    return row_id


def _retry_later() -> JSONResponse:
    return JSONResponse({"status": "retry"}, status_code=503)


async def _ingest(
    db: Db,
    queue: TaskQueue,
    provider: str,
    delivery_id: str,
    event_name: str,
    action: str | None,
    event: PlatformEvent | None,
) -> JSONResponse:
    status = "received" if event is not None else "ignored"
    row_id = await _record(db, provider, delivery_id, event_name, action, status)
    if row_id is None:
        log.info("webhook_duplicate", provider=provider, delivery_id=delivery_id)
        return JSONResponse({"status": "duplicate"}, status_code=200)
    if event is None:
        log.info(
            "webhook_ignored", provider=provider, delivery_id=delivery_id, event_name=event_name
        )
        return JSONResponse({"status": "ignored"}, status_code=200)
    try:
        queue.enqueue("events.process", str(row_id), event_adapter.dump_python(event, mode="json"))
    except Exception:
        # Forget the delivery so the provider's redelivery is processed, not a "duplicate".
        log.exception("webhook_enqueue_failed", provider=provider, delivery_id=delivery_id)
        await db.execute(delete(WebhookDelivery).where(WebhookDelivery.id == row_id))
        await db.commit()
        return _retry_later()
    log.info("webhook_queued", provider=provider, delivery_id=delivery_id, kind=event.kind)
    return JSONResponse({"status": "queued"}, status_code=202)


@router.post("/api/webhooks/github")
async def github_webhook(
    request: Request, db: Db, settings: SettingsDep, queue: Queue
) -> JSONResponse:
    body = await request.body()
    if not gh.verify_signature(
        settings.github_webhook_secret.get_secret_value(),
        body,
        request.headers.get("x-hub-signature-256"),
    ):
        raise _reject("github", "bad signature")
    payload = _loads(body)
    delivery = _delivery_id(request.headers.get("x-github-delivery"), body)
    event_name = request.headers.get("x-github-event", "unknown")
    event = gh.parse_event(event_name, payload, delivery) if payload else None
    return await _ingest(db, queue, "github", delivery, event_name, gh.event_action(payload), event)


async def _gitlab_secret(db: Db, crypto: CryptoDep, project_id: str | None) -> str:
    """The per-project hook secret HootPR generated; empty (never verifies) when unknown."""
    if project_id is None:
        return ""
    repo = (
        await db.execute(
            select(Repository).where(
                Repository.provider == "gitlab", Repository.provider_repo_id == project_id
            )
        )
    ).scalar_one_or_none()
    if repo is None or not repo.webhook_secret_enc:
        return ""
    try:
        return crypto.decrypt(repo.webhook_secret_enc)
    except DecryptionError:
        return ""


@router.post("/api/webhooks/gitlab")
async def gitlab_webhook(request: Request, db: Db, crypto: CryptoDep, queue: Queue) -> JSONResponse:
    body = await request.body()
    token = request.headers.get("x-gitlab-token")
    if not token:  # cheap reject before touching the body
        raise _reject("gitlab", "missing token")
    # The secret is per project, so the project id must be read before verification. The body
    # is only JSON-decoded here; nothing is acted on until the token matches.
    payload = _loads(body)
    secret = await _gitlab_secret(db, crypto, gl.extract_project_id(payload))
    if not gl.verify_token(secret, token):
        raise _reject("gitlab", "bad token or unknown project")
    delivery = _delivery_id(
        request.headers.get("idempotency-key") or request.headers.get("x-gitlab-event-uuid"), body
    )
    event_name = request.headers.get("x-gitlab-event") or str(payload.get("object_kind", "unknown"))
    attrs = payload.get("object_attributes")
    action = attrs.get("action") if isinstance(attrs, dict) else None
    event = gl.parse_event(event_name, payload, delivery)
    return await _ingest(
        db, queue, "gitlab", delivery, event_name, str(action) if action else None, event
    )


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Db, settings: SettingsDep) -> JSONResponse:
    body = await request.body()
    if not verify_webhook_signature(
        settings.razorpay_webhook_secret.get_secret_value(),
        body,
        request.headers.get("x-razorpay-signature"),
    ):
        raise _reject("razorpay", "bad signature")
    payload = _loads(body)
    event_name = str(payload.get("event", "unknown"))
    event_id = _delivery_id(request.headers.get("x-razorpay-event-id"), body)
    payment = (((payload.get("payload") or {}).get("payment") or {}).get("entity")) or {}
    order_id = payment.get("order_id") if isinstance(payment, dict) else None
    handled = event_name in RAZORPAY_FULFILL_EVENTS and bool(order_id)
    # The delivery row and the fulfillment share one transaction: if fulfill fails, both roll
    # back and Razorpay's retry is processed instead of being treated as a duplicate.
    row_id = await _record(
        db,
        "razorpay",
        event_id,
        event_name,
        None,
        "processed" if handled else "ignored",
        commit=not handled,
    )
    if row_id is None:
        await db.rollback()
        return JSONResponse({"status": "duplicate"})
    if not handled:
        return JSONResponse({"status": "ignored"})
    payment_id = payment.get("id")

    def _fulfill(s: Session) -> FulfillResult:
        return fulfill(
            s, CreditLedger(), settings, str(order_id), str(payment_id) if payment_id else None
        )

    try:
        res = await db.run_sync(_fulfill)
        if res.status == "unknown_order":
            delivery = await db.get(WebhookDelivery, row_id)
            if delivery is not None:
                delivery.status = "ignored"
        await db.commit()
    except Exception:
        await db.rollback()
        log.exception("razorpay_webhook_failed", rzp_event=event_name)
        return _retry_later()
    log.info("razorpay_webhook", rzp_event=event_name, result=res.status, org_id=str(res.org_id))
    if res.status == "unknown_order":
        return JSONResponse({"status": "ignored"})
    return JSONResponse({"status": "processed"})
