"""Identity upsert and account linking (spec §6.1)."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.provider_clients import ProviderProfile, TokenSet
from app.crypto import Crypto
from app.models import Identity, User


class IdentityInUse(Exception):
    """The provider identity already belongs to a different HootPR user."""


def upsert_identity(
    s: Session,
    crypto: Crypto,
    profile: ProviderProfile,
    tokens: TokenSet,
    link_user_id: UUID | None,
) -> User:
    """Sign in (``link_user_id=None``) or attach the identity to the signed-in user.

    At most one identity per provider is linked to a user; signing in with another account of a
    provider the user already has switches to that account's user instead of linking it.
    An identity always keeps its owner: signing in with it logs into that user, and linking it to a
    different signed-in user raises ``IdentityInUse``. Users are never merged by e-mail.
    """
    if link_user_id is not None:
        same_provider = s.execute(
            select(Identity.provider_user_id).where(
                Identity.user_id == link_user_id, Identity.provider == profile.provider
            )
        ).scalar_one_or_none()
        if same_provider is not None and same_provider != profile.provider_user_id:
            link_user_id = None  # a different account of the same provider: plain sign-in
    ident = s.execute(
        select(Identity).where(
            Identity.provider == profile.provider,
            Identity.provider_user_id == profile.provider_user_id,
        )
    ).scalar_one_or_none()
    user: User | None
    if ident is not None:
        if link_user_id is not None and ident.user_id != link_user_id:
            raise IdentityInUse(profile.username)
        user = s.get(User, ident.user_id)
        if user is None:  # FK with ON DELETE CASCADE makes this unreachable
            raise LookupError(f"identity {ident.id} has no user")
    else:
        user = s.get(User, link_user_id) if link_user_id else None
        if user is None:
            user = User(
                display_name=profile.display_name,
                email=profile.email,
                avatar_url=profile.avatar_url,
            )
            s.add(user)
            s.flush()
        ident = Identity(
            user_id=user.id,
            provider=profile.provider,
            provider_user_id=profile.provider_user_id,
            username=profile.username,
        )
        s.add(ident)
    ident.username = profile.username
    ident.access_token_enc = crypto.encrypt(tokens.access_token)
    ident.refresh_token_enc = crypto.encrypt(tokens.refresh_token) if tokens.refresh_token else None
    ident.token_expires_at = tokens.expires_at
    user.email = user.email or profile.email
    user.avatar_url = user.avatar_url or profile.avatar_url
    s.flush()
    return user


def decrypt_identity_token(crypto: Crypto, identity: Identity) -> str:
    return crypto.decrypt(identity.access_token_enc or "")
