"""Engine + session factory.

One engine per process, sessions per request/unit-of-work. SQLite (unit tests, dev) gets
foreign-key enforcement switched on per connection — silently-off FKs are how orphan rows happen.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from alphadash.config import Settings, get_settings


def build_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record) -> None:  # pragma: no cover - trivial
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def set_tenant_context(session: Session, user_id: str) -> None:
    """Pin the RLS tenant for the CURRENT transaction (Postgres; no-op elsewhere).

    ``set_config(..., is_local=true)`` scopes the setting to the transaction, so a pooled
    connection never leaks one user's context to the next request.
    """
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text

        session.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id})


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit-on-success / rollback-on-error unit of work."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
