"""Sync test factories (each commits)."""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.billing.ledger import CreditLedger
from app.crypto import Crypto
from app.models import (
    Identity,
    Installation,
    Membership,
    Organization,
    PullRequest,
    Repository,
    User,
)


def make_user(db: Session, name: str = "Alice", email: str | None = "alice@example.com") -> User:
    u = User(display_name=name, email=email, avatar_url=None)
    db.add(u)
    db.commit()
    return u


def make_identity(
    db: Session,
    crypto: Crypto,
    user: User,
    provider: str = "github",
    provider_user_id: str = "501",
    username: str = "alice",
    token: str = "gho_token",
) -> Identity:
    i = Identity(
        user_id=user.id,
        provider=provider,
        provider_user_id=provider_user_id,
        username=username,
        access_token_enc=crypto.encrypt(token),
    )
    db.add(i)
    db.commit()
    return i


def make_org(
    db: Session,
    provider: str = "github",
    provider_org_id: str = "9001",
    slug: str = "acme",
    name: str = "acme",
    kind: str = "org",
    balance: str = "0",
) -> Organization:
    o = Organization(
        provider=provider,
        provider_org_id=provider_org_id,
        kind=kind,
        name=name,
        slug=slug,
        credits_balance=Decimal("0"),
        settings={},
    )
    db.add(o)
    db.flush()
    if Decimal(balance) > 0:
        CreditLedger().grant(db, o.id, Decimal(balance), "manual")
    db.commit()
    return o


def make_member(db: Session, user: User, org: Organization, role: str = "admin") -> Membership:
    m = Membership(user_id=user.id, org_id=org.id, role=role)
    db.add(m)
    db.commit()
    return m


def make_installation(
    db: Session,
    org: Organization,
    github_installation_id: int | None = 42,
    gitlab_token: str | None = None,
    crypto: Crypto | None = None,
) -> Installation:
    inst = Installation(
        org_id=org.id,
        provider=org.provider,
        status="active",
        github_installation_id=github_installation_id if org.provider == "github" else None,
    )
    if gitlab_token is not None:
        assert crypto is not None
        inst.gitlab_bot_token_enc = crypto.encrypt(gitlab_token)
        inst.gitlab_bot_user_id = 5
        inst.gitlab_bot_username = "hootpr-bot"
    db.add(inst)
    db.commit()
    return inst


def make_repo(
    db: Session,
    org: Organization,
    installation: Installation | None = None,
    provider: str = "github",
    provider_repo_id: str = "1001",
    full_name: str = "acme/web",
    default_branch: str = "main",
    webhook_secret: str | None = None,
    crypto: Crypto | None = None,
) -> Repository:
    r = Repository(
        org_id=org.id,
        installation_id=installation.id if installation else None,
        provider=provider,
        provider_repo_id=provider_repo_id,
        full_name=full_name,
        default_branch=default_branch,
        private=True,
        enabled=True,
        settings={},
    )
    if webhook_secret is not None:
        assert crypto is not None
        r.webhook_secret_enc = crypto.encrypt(webhook_secret)
    db.add(r)
    db.commit()
    return r


def make_pr(
    db: Session,
    repo: Repository,
    number: int = 7,
    head_sha: str = "2" * 40,
    base_sha: str = "1" * 40,
    title: str = "Add login rate limiting",
    author: str = "alice",
    body: str = "",
) -> PullRequest:
    pr = PullRequest(
        repo_id=repo.id,
        number=number,
        title=title,
        body=body,
        author_username=author,
        state="open",
        is_draft=False,
        labels=[],
        base_ref="main",
        head_ref="feat",
        base_sha=base_sha,
        head_sha=head_sha,
        url=f"https://example/{number}",
    )
    db.add(pr)
    db.commit()
    return pr
