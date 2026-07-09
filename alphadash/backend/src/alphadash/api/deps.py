"""Request-scoped dependencies: DB session, authenticated user, tenant-scoped session.

Order matters: ``get_tenant_db`` yields a session whose transaction carries
``app.user_id`` (Postgres ``set_config(..., is_local=true)``), so RLS policies from migration
0003 apply to every query made through it. On SQLite (unit tests) the setting is a no-op and
isolation relies on explicit filtering — which is why anything security-sensitive is also
integration-tested against Postgres.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from alphadash.db.models import User
from alphadash.db.session import set_tenant_context
from alphadash.services import auth as auth_service

SESSION_COOKIE = "alphadash_session"


def get_db(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def now_utc() -> datetime:
    return datetime.now(UTC)


def get_current_user(
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    if not session_token:
        raise HTTPException(status_code=401, detail="not signed in")
    try:
        return auth_service.resolve_session(db, token=session_token, now=now_utc())
    except auth_service.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from None


def get_tenant_db(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Session:
    """The session every tenant-data endpoint must use: RLS context pinned to this user."""
    set_tenant_context(db, user.id)
    return db
