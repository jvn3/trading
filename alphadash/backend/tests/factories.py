"""Shared test factories: in-memory DB with a funded paper account."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from alphadash.db.base import Base
from alphadash.db.models import Account, CashBalance, User


def make_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def funded_account(
    session: Session, *, cash: str = "10000", email: str = "t@example.com"
) -> Account:
    user = User(email=email, display_name="Test")
    session.add(user)
    session.flush()
    account = Account(user_id=user.id, starting_equity=Decimal(cash))
    session.add(account)
    session.flush()
    session.add(
        CashBalance(account_id=account.id, currency=account.base_currency, amount=Decimal(cash))
    )
    session.flush()
    return account
