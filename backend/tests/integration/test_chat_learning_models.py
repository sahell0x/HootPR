from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ChatMessage, Learning, PullRequest
from tests.factories import make_installation, make_org, make_pr, make_repo

pytestmark = pytest.mark.integration


def test_chat_message_defaults_and_uniqueness(db: Session) -> None:
    org = make_org(db)
    pr = make_pr(db, make_repo(db, org, make_installation(db, org)))
    m = ChatMessage(
        org_id=org.id,
        pr_id=pr.id,
        provider_comment_id="555",
        author_username="bob",
        kind="chat",
        body="@hootpr why?",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.status == "received" and m.credits_charged == Decimal("0.00")
    assert m.input_tokens == 0 and m.thread_ref is None and m.meta == {}
    db.add(
        ChatMessage(
            org_id=org.id,
            pr_id=pr.id,
            provider_comment_id="555",
            author_username="bob",
            kind="chat",
            body="dup",
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_learning_stores_unconstrained_vectors(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    a = Learning(
        org_id=org.id,
        repo_id=repo.id,
        scope="repo",
        text="use logging",
        embedding=[0.1, 0.2, 0.3],
        embedding_model="m-3",
        created_by_username="bob",
    )
    b = Learning(
        org_id=org.id,
        repo_id=None,
        scope="org",
        text="no print",
        embedding=[0.1] * 1536,
        embedding_model="m-1536",
        created_by_username="bob",
    )
    db.add_all([a, b])
    db.commit()
    dims = db.execute(text("SELECT vector_dims(embedding) FROM learnings")).scalars().all()
    assert sorted(dims) == [3, 1536]
    db.refresh(a)
    assert [round(float(x), 3) for x in a.embedding or []] == [0.1, 0.2, 0.3]


def test_learning_repo_delete_keeps_learning_without_repo(db: Session) -> None:
    org = make_org(db)
    repo = make_repo(db, org, make_installation(db, org))
    row = Learning(
        org_id=org.id, repo_id=repo.id, scope="repo", text="x", created_by_username="bob"
    )
    db.add(row)
    db.commit()
    db.delete(repo)
    db.commit()
    db.refresh(row)
    assert row.repo_id is None


def test_pull_request_blocking_state_default(db: Session) -> None:
    org = make_org(db)
    pr = make_pr(db, make_repo(db, org, make_installation(db, org)))
    db.refresh(pr)
    assert isinstance(pr, PullRequest) and pr.blocking_state == "none"
