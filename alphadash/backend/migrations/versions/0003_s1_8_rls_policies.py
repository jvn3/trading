"""S1.8 row-level security policies (Postgres only).

Physical tenant isolation: every tenant-owned table gets ENABLE + FORCE ROW LEVEL SECURITY and a
single ``tenant_isolation`` policy keyed on ``current_setting('app.user_id', true)``. The app sets
``SET LOCAL app.user_id = <id>`` per transaction after authenticating; with no setting, policies
evaluate NULL → zero rows visible. FORCE makes the table owner obey too.

``users`` and ``auth_sessions`` are auth-bootstrap tables and stay outside RLS (reads happen
before identity is known); the auth service filters them explicitly.

On SQLite this migration is a no-op (unit tests; isolation is app-level there).

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_USER = "current_setting('app.user_id', true)"

# table -> USING expression
POLICIES: dict[str, str] = {
    "risk_profiles": f"user_id = {APP_USER}",
    "watchlists": f"user_id = {APP_USER}",
    "accounts": f"user_id = {APP_USER}",
    "cash_balances": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "positions": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "orders": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "suggestions": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "risk_limits": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "risk_events": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "journal_entries": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    "agent_runs": f"account_id IN (SELECT id FROM accounts WHERE user_id = {APP_USER})",
    # RLS applies inside subqueries too, so referencing an RLS'd table is enough:
    "fills": "order_id IN (SELECT id FROM orders)",
    "decisions": "suggestion_id IN (SELECT id FROM suggestions)",
    "watchlist_items": "watchlist_id IN (SELECT id FROM watchlists)",
    "data_snapshots": "agent_run_id IN (SELECT id FROM agent_runs)",
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, expr in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({expr}) WITH CHECK ({expr})")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in POLICIES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
