import gzip

import pytest
from sqlalchemy.orm import Session

from app.models import Finding, Review, ReviewCacheEntry, ReviewTask
from tests.factories import make_installation, make_org, make_pr, make_repo

pytestmark = pytest.mark.integration


def test_phase2_columns_have_defaults(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    pr = make_pr(db, repo)
    review = Review(pr_id=pr.id, org_id=org.id, trigger="auto", head_sha=pr.head_sha)
    db.add(review)
    db.flush()
    task = ReviewTask(review_id=review.id, ordinal=0, title="t")
    db.add(task)
    db.flush()
    finding = Finding(
        review_id=review.id,
        task_id=task.id,
        path="a.py",
        end_line=1,
        severity="minor",
        category="bug",
        title="t",
        body="b",
        fingerprint="f" * 32,
    )
    db.add(finding)
    db.commit()
    db.refresh(review)
    db.refresh(task)
    db.refresh(finding)
    assert review.stages == []
    assert task.focus == [] and task.related_symbols == [] and task.summary is None
    assert finding.evidence == []


def test_review_cache_entry_roundtrip(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    blob = gzip.compress(b'{"version":1}')
    db.add(
        ReviewCacheEntry(
            repo_id=repo.id, sha="a" * 40, kind="graph", cache_key="k" * 64, payload_gz=blob
        )
    )
    db.commit()
    row = db.query(ReviewCacheEntry).one()
    assert gzip.decompress(row.payload_gz) == b'{"version":1}'


def test_migration_0002_downgrades_and_upgrades(migrated_db: str) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from tests.conftest import BACKEND_DIR

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", migrated_db)
    engine = create_engine(migrated_db)
    try:
        command.downgrade(cfg, "0001")
        assert "review_cache" not in inspect(engine).get_table_names()
        command.upgrade(cfg, "head")
        insp = inspect(engine)
        assert "review_cache" in insp.get_table_names()
        assert "stages" in {c["name"] for c in insp.get_columns("reviews")}
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
