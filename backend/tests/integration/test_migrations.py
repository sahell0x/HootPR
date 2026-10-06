import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.models import Base, Organization, User

pytestmark = pytest.mark.integration


def test_migrations_match_models(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_vector_extension_installed(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        assert conn.execute(text("SELECT 1 FROM pg_extension WHERE extname='vector'")).scalar() == 1


def test_uuid7_ids_are_time_ordered(db: Session) -> None:
    a = User(display_name="a")
    b = User(display_name="b")
    db.add_all([a, b])
    db.flush()
    assert a.id.version == 7
    assert a.id < b.id


def test_org_defaults(db: Session) -> None:
    org = Organization(provider="github", provider_org_id="1", kind="org", name="acme", slug="acme")
    db.add(org)
    db.commit()
    db.refresh(org)
    assert str(org.credits_balance) == "0.00"
    assert org.settings == {}
    assert org.purchases_count == 0
    assert org.created_at.tzinfo is not None


def test_server_defaults_apply_to_raw_inserts(db: Session) -> None:
    db.execute(
        text(
            "INSERT INTO organizations (id, provider, provider_org_id, kind, name, slug) "
            "VALUES (gen_random_uuid(), 'gitlab', '9', 'group', 'g', 'gl-g')"
        )
    )
    row = db.execute(
        text("SELECT credits_balance, blocked, settings FROM organizations WHERE slug='gl-g'")
    ).one()
    assert str(row.credits_balance) == "0.00"
    assert row.blocked is False
    assert row.settings == {}
