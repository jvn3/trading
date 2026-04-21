"""Engine + session helpers. Tests use an in-memory URL; prod uses the configured DB_URL."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from jay_trading.config import get_settings
from jay_trading.data.models import Base


def _make_engine() -> Engine:
    url = get_settings().db_url
    # SQLite + threading = check_same_thread false for scheduler contexts.
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Convenience context manager with commit/rollback semantics."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all() -> None:
    """Create tables from the declarative metadata.

    Alembic migrations are the source of truth in production; this is a
    convenience for tests and the first-run smoke test.
    """
    Base.metadata.create_all(get_engine())


def _reset_for_tests() -> None:
    """Tear down cached engine/session. Internal use only."""
    global _engine, _SessionFactory
    _engine = None
    _SessionFactory = None
