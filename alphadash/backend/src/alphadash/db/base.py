"""Declarative base and shared column helpers for the AlphaDash schema (S0.2).

Frozen-contract global rules encoded here:
- Primary keys are ``str`` UUIDs (``uuid4().hex``) generated app-side.
- Every table carries a tz-aware UTC ``created_at`` with a server default; mutable tables add
  ``updated_at``.
- Money and quantities are ``Numeric(24, 8)`` — never ``Float``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, MetaData, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names so Alembic migrations are stable across databases.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Single Numeric type for all money/quantity columns (frozen contract: Numeric(24, 8)).
MONEY = Numeric(24, 8)


def new_id() -> str:
    """App-side primary key generator (uuid4 hex, 32 chars)."""
    return uuid4().hex


class Base(DeclarativeBase):
    """Declarative base for every AlphaDash table."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PkMixin:
    """String UUID primary key, generated app-side."""

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class CreatedAtMixin:
    """Tz-aware UTC ``created_at`` with a server-side default."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpdatedAtMixin:
    """Tz-aware UTC ``updated_at`` for mutable tables (set on insert, refreshed on update)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
