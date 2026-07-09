"""Auth + provisioning (S1.8).

Email + password (argon2id), server-side sessions: the browser holds an opaque random token in an
httpOnly cookie; the DB stores only its SHA-256. Registration provisions the full beginner setup —
balanced risk profile, funded paper account, default risk limits — so a new user can trade
(paper) immediately.

``users`` and ``auth_sessions`` are auth-bootstrap tables: they are NOT under RLS (you must read
them before knowing who the user is) and every query here filters explicitly.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    AuthSession,
    CashBalance,
    RiskProfile,
    RiskProfileName,
    User,
)
from alphadash.db.session import set_tenant_context

_hasher = PasswordHasher()  # argon2id, library defaults (OWASP-aligned)

SESSION_TTL = timedelta(days=14)
MIN_PASSWORD_LEN = 10

# Default "balanced" beginner profile — conservative by design; user can loosen later (S3.6).
BALANCED_PROFILE = {
    "max_position_pct": Decimal("10"),
    "max_asset_class_pct": {"equity": 80, "crypto": 10},
    "max_trades_per_week": 5,
    "cash_floor_pct": Decimal("10"),
    "per_suggestion_max_pct": Decimal("5"),
    "drawdown_pause_pct": Decimal("15"),
}
DEFAULT_STARTING_EQUITY = Decimal("10000")


class AuthError(Exception):
    """Invalid credentials / session. Message is safe to show the user."""


@dataclass(frozen=True)
class RegisteredUser:
    user: User
    account: Account
    profile: RiskProfile


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    starting_equity: Decimal = DEFAULT_STARTING_EQUITY,
) -> RegisteredUser:
    email = email.strip().lower()
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LEN} characters")
    if session.scalar(select(User).where(User.email == email)):
        raise AuthError("an account with this email already exists")

    user = User(email=email, display_name=display_name, password_hash=_hasher.hash(password))
    session.add(user)
    session.flush()
    set_tenant_context(
        session, user.id
    )  # RLS WITH CHECK must see the new owner before provisioning

    profile = RiskProfile(user_id=user.id, name=RiskProfileName.balanced, **BALANCED_PROFILE)
    account = Account(user_id=user.id, starting_equity=starting_equity)
    session.add_all([profile, account])
    session.flush()
    session.add(
        CashBalance(account_id=account.id, currency=account.base_currency, amount=starting_equity)
    )
    session.flush()
    return RegisteredUser(user=user, account=account, profile=profile)


def login(session: Session, *, email: str, password: str, now: datetime) -> tuple[User, str]:
    """Verify credentials, mint a session. Returns (user, raw token for the cookie)."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.password_hash is None:
        # Hash anyway: keep timing indistinguishable from the wrong-password path.
        _hasher.hash(password)
        raise AuthError("invalid email or password")
    try:
        _hasher.verify(user.password_hash, password)
    except VerifyMismatchError:
        raise AuthError("invalid email or password") from None

    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(user_id=user.id, token_hash=_token_hash(token), expires_at=now + SESSION_TTL)
    )
    session.flush()
    return user, token


def resolve_session(session: Session, *, token: str, now: datetime) -> User:
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if auth is None or auth.revoked_at is not None:
        raise AuthError("not signed in")
    expires = auth.expires_at if auth.expires_at.tzinfo else auth.expires_at.replace(tzinfo=UTC)
    if expires <= now:
        raise AuthError("session expired — please sign in again")
    user = session.get(User, auth.user_id)
    if user is None:
        raise AuthError("not signed in")
    return user


def logout(session: Session, *, token: str, now: datetime) -> None:
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if auth is not None and auth.revoked_at is None:
        auth.revoked_at = now
        session.flush()
