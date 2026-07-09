"""Append-only journal (S1.6).

``record`` is the only write path. There is deliberately no update/delete API, and ORM-level
UPDATE/DELETE of ``JournalEntry`` raises — the journal is evidence, not state.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from alphadash.db.models import JournalEntry, JournalEntryType


class JournalTamperError(RuntimeError):
    """Raised when code attempts to mutate or delete a journal entry."""


@event.listens_for(Session, "before_flush")
def _forbid_journal_mutation(session: Session, _ctx, _instances) -> None:
    for obj in session.dirty:
        if isinstance(obj, JournalEntry) and session.is_modified(obj):
            raise JournalTamperError("journal entries are append-only (update blocked)")
    for obj in session.deleted:
        if isinstance(obj, JournalEntry):
            raise JournalTamperError("journal entries are append-only (delete blocked)")


def record(
    session: Session,
    *,
    account_id: str,
    entry_type: JournalEntryType,
    ref_id: str,
    payload: dict[str, Any],
) -> JournalEntry:
    entry = JournalEntry(
        account_id=account_id, entry_type=entry_type, ref_id=ref_id, payload=payload
    )
    session.add(entry)
    session.flush()
    return entry
