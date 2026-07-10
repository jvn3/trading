"""S3.1/S3.2: users.onboarded_at + notifications table (with RLS on Postgres)

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_USER = "current_setting('app.user_id', true)"


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("digest", "nudge", "risk", name="notification_kind", native_enum=False),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    # Tenant isolation, same pattern as migration 0003.
    if op.get_bind().dialect.name == "postgresql":
        expr = f"user_id = {APP_USER}"
        op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE notifications FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON notifications USING ({expr}) WITH CHECK ({expr})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON notifications")
    op.drop_table("notifications")
    op.drop_column("users", "onboarded_at")
