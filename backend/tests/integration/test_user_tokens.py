import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.auth.provider_clients import GitHubUserClient, GitLabUserClient
from app.auth.tokens import UserTokens
from app.crypto import Crypto
from app.models import Identity
from app.settings import Settings
from tests.factories import make_identity, make_user

pytestmark = pytest.mark.integration
GH = "https://github.com"


async def test_parallel_requests_refresh_a_single_use_token_once(
    app: FastAPI, db: Session, crypto: Crypto, int_settings: Settings
) -> None:
    """GitHub refresh tokens are single use: two requests racing after expiry must not both
    spend it (the loser would get bad_refresh_token and force a re-login)."""
    user = make_user(db)
    ident = make_identity(db, crypto, user, token="ghu_old")
    ident.refresh_token_enc = crypto.encrypt("ghr_1")
    ident.token_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    used: list[str] = []

    async def refresh(request: httpx.Request) -> httpx.Response:
        rt = dict(httpx.QueryParams(request.content.decode()))["refresh_token"]
        used.append(rt)
        await asyncio.sleep(0.2)
        if rt != "ghr_1" or used.count(rt) > 1:
            return httpx.Response(200, json={"error": "bad_refresh_token"})
        return httpx.Response(
            200, json={"access_token": "ghu_new", "refresh_token": "ghr_2", "expires_in": 28800}
        )

    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    http = app.state.http

    async def get_token() -> str:
        async with maker() as s:
            row = (await s.execute(select(Identity))).scalar_one()
            tokens = UserTokens(
                s,
                crypto,
                GitHubUserClient(int_settings, http),
                GitLabUserClient(int_settings, http),
            )
            return await tokens.token(row)

    with respx.mock(assert_all_mocked=False, assert_all_called=False) as mock:
        mock.post(f"{GH}/login/oauth/access_token").mock(side_effect=refresh)
        results = await asyncio.gather(get_token(), get_token())
    assert results == ["ghu_new", "ghu_new"]
    assert used == ["ghr_1"]
    db.expire_all()
    row = db.execute(select(Identity)).scalar_one()
    assert crypto.decrypt(row.refresh_token_enc or "") == "ghr_2"
