"""rescale HootPR credits x100 (same price ratio, whole-number amounts)

Every stored credit amount is multiplied by 100: balances, ledger deltas / balances, payments,
per-job ``credits_charged`` and the per-call metered ``llm_calls.credits``. NUMERIC(8,2) holds up
to 999,999.99 (balances are capped at MAX_CREDIT_BALANCE=1000) and NUMERIC(12,6) up to
999,999.999999, so no column needs widening.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("organizations", ("credits_balance",)),
    ("credit_ledger", ("delta", "balance_after")),
    ("payments", ("credits",)),
    ("reviews", ("credits_charged",)),
    ("chat_messages", ("credits_charged",)),
    ("security_scans", ("credits_charged",)),
    ("finishing_jobs", ("credits_charged",)),
    ("change_stack_messages", ("credits_charged",)),
    ("llm_calls", ("credits",)),
)


def _scale(op_sql: str) -> None:
    for table, cols in COLUMNS:
        sets = ", ".join(f"{c} = {c} {op_sql}" for c in cols)
        where = " OR ".join(f"{c} IS NOT NULL" for c in cols)
        op.execute(f"UPDATE {table} SET {sets} WHERE {where}")  # noqa: S608 (constants)


def upgrade() -> None:
    _scale("* 100")


def downgrade() -> None:
    _scale("/ 100")
