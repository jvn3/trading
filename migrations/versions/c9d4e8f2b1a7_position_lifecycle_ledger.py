"""Position lifecycle ledger: keep closed positions with realized P&L.

Adds ``closed_at`` / ``exit_price`` / ``realized_pnl`` to ``positions`` and
relaxes the unique ticker index to non-unique — closed rows are retained as
the per-trade P&L ledger, so a ticker accumulates one row per round trip.

Revision ID: c9d4e8f2b1a7
Revises: a4f91c2d5e83
Create Date: 2026-07-06
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c9d4e8f2b1a7"
down_revision = "a4f91c2d5e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("positions") as batch_op:
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("exit_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("realized_pnl", sa.Float(), nullable=True))
        batch_op.drop_index(batch_op.f("ix_positions_ticker"))
        batch_op.create_index(batch_op.f("ix_positions_ticker"), ["ticker"], unique=False)
        batch_op.create_index(batch_op.f("ix_positions_closed_at"), ["closed_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("positions") as batch_op:
        batch_op.drop_index(batch_op.f("ix_positions_closed_at"))
        batch_op.drop_index(batch_op.f("ix_positions_ticker"))
        batch_op.create_index(batch_op.f("ix_positions_ticker"), ["ticker"], unique=True)
        batch_op.drop_column("realized_pnl")
        batch_op.drop_column("exit_price")
        batch_op.drop_column("closed_at")
