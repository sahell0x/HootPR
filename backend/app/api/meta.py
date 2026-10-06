"""Public, non-secret configuration the dashboard needs before sign-in."""

from fastapi import APIRouter

from app.api.schemas import CreditPack, CreditPrices, Meta, ProvidersEnabled
from app.billing.disclaimer import DISCLAIMER_PLAIN
from app.billing.pricing import whole
from app.deps import SettingsDep
from app.settings import Settings

router = APIRouter(tags=["meta"])


def github_install_url(settings: Settings) -> str:
    web = settings.github_web_url.rstrip("/")
    return f"{web}/apps/{settings.github_app_slug}/installations/new"


@router.get("/api/meta", response_model=Meta)
async def meta(settings: SettingsDep) -> Meta:
    return Meta(
        github_app_slug=settings.github_app_slug,
        github_install_url=github_install_url(settings),
        gitlab_base_url=settings.gitlab_base_url.rstrip("/"),
        razorpay_key_id=settings.razorpay_key_id,
        disclaimer=DISCLAIMER_PLAIN,
        credit_pack=CreditPack(
            credits=settings.credit_pack_credits, price_paise=settings.credit_pack_price_paise
        ),
        credit_prices=CreditPrices(
            per_review=whole(settings.credits_typical_review),
            per_chat_reply=whole(settings.credits_typical_chat_reply),
            signup_bonus=whole(settings.credits_signup_bonus),
        ),
        providers_enabled=ProvidersEnabled(
            github=bool(settings.github_oauth_client_id),
            gitlab=bool(settings.gitlab_oauth_client_id),
        ),
    )
