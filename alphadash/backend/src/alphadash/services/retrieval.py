"""Evidence retrieval + context assembly (S2.2).

Indexes ingested news/fundamentals into ``evidence_docs`` and retrieves cited, fresh evidence
for agent runs and chat. Retrieval is lexical: Postgres full-text search (tsvector, migration
0004); on sqlite a LIKE-based fallback keeps unit tests hermetic. The interface would take an
embeddings backend without callers changing (operator decision 2026-07-09: FTS first).

INJECTION SANDBOX: document text is untrusted third-party content. ``build_context`` neutralizes
markup (angle brackets), strips control characters, truncates, and wraps each doc in an envelope
that downstream prompts declare as data-not-instructions. Nothing from a document is ever placed
in the system prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from alphadash.db.models import EvidenceDoc
from alphadash.providers.dto import FundamentalSnapshot, NewsItem

MAX_BODY_CHARS = 2000
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def index_news(session: Session, items: list[NewsItem]) -> int:
    """Upsert news into the evidence corpus. Returns count of newly indexed docs."""
    added = 0
    for item in items:
        external_id = f"news:{item.id}"[:512]
        if session.scalar(select(EvidenceDoc.id).where(EvidenceDoc.external_id == external_id)):
            continue
        session.add(
            EvidenceDoc(
                external_id=external_id,
                doc_type="news",
                source=item.source[:120],
                symbols=[s.upper() for s in item.symbols],
                title=item.headline[:500],
                body=(item.summary or item.headline)[: MAX_BODY_CHARS * 2],
                url=item.url,
                published_at=item.published_at,
            )
        )
        added += 1
    session.flush()
    return added


def index_fundamentals(session: Session, snapshot: FundamentalSnapshot) -> int:
    """Index a fundamentals snapshot as a readable evidence doc (one per symbol per day)."""
    day = snapshot.as_of.date().isoformat()
    external_id = f"fundamentals:{snapshot.symbol}:{day}"
    if session.scalar(select(EvidenceDoc.id).where(EvidenceDoc.external_id == external_id)):
        return 0
    lines = [f"{key}: {value}" for key, value in sorted(snapshot.metrics.items())]
    session.add(
        EvidenceDoc(
            external_id=external_id,
            doc_type="fundamentals",
            source=snapshot.provenance.source[:120],
            symbols=[snapshot.symbol.upper()],
            title=f"{snapshot.symbol} fundamental metrics as of {day}",
            body="\n".join(lines)[: MAX_BODY_CHARS * 2],
            url=None,
            published_at=snapshot.as_of,
        )
    )
    session.flush()
    return 1


def search_evidence(
    session: Session,
    query: str,
    *,
    symbols: list[str] | None = None,
    limit: int = 6,
) -> list[EvidenceDoc]:
    """Rank evidence docs for a query. Postgres: FTS ts_rank; sqlite: LIKE term scoring."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        rows = session.execute(
            text(
                "SELECT id FROM evidence_docs "
                "WHERE search_tsv @@ plainto_tsquery('english', :q) "
                "ORDER BY ts_rank(search_tsv, plainto_tsquery('english', :q)) DESC, "
                "published_at DESC LIMIT :n"
            ),
            {"q": query, "n": limit * 3},
        ).all()
        docs = [session.get(EvidenceDoc, r.id) for r in rows]
    else:
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        if not terms:
            return []
        clauses = [
            or_(EvidenceDoc.title.ilike(f"%{t}%"), EvidenceDoc.body.ilike(f"%{t}%")) for t in terms
        ]
        candidates = session.scalars(
            select(EvidenceDoc).where(or_(*clauses)).order_by(EvidenceDoc.published_at.desc())
        ).all()

        def score(doc: EvidenceDoc) -> int:
            haystack = f"{doc.title}\n{doc.body}".lower()
            return sum(haystack.count(t) for t in terms)

        docs = sorted(candidates, key=score, reverse=True)[: limit * 3]

    if symbols:
        wanted = {s.upper() for s in symbols}
        preferred = [d for d in docs if wanted & set(d.symbols)]
        rest = [d for d in docs if not (wanted & set(d.symbols))]
        docs = preferred + rest
    return docs[:limit]


@dataclass(frozen=True)
class Citation:
    doc_id: str
    title: str
    source: str
    url: str | None
    published_at: str  # ISO


def _sanitize(raw: str) -> str:
    """Neutralize untrusted text for prompt inclusion: no markup, no control chars, bounded."""
    cleaned = _CONTROL_CHARS.sub("", raw)
    cleaned = cleaned.replace("<", "‹").replace(">", "›")
    return cleaned[:MAX_BODY_CHARS]


def build_context(docs: list[EvidenceDoc]) -> tuple[str, list[Citation]]:
    """Assemble the evidence block for a prompt + the citation list that travels with it."""
    parts: list[str] = []
    citations: list[Citation] = []
    for i, doc in enumerate(docs, start=1):
        published = (
            doc.published_at if doc.published_at.tzinfo else doc.published_at.replace(tzinfo=UTC)
        )
        parts.append(
            f'<evidence id="{i}" source="{_sanitize(doc.source)}" '
            f'published="{published.isoformat()}">\n'
            f"{_sanitize(doc.title)}\n{_sanitize(doc.body)}\n</evidence>"
        )
        citations.append(
            Citation(
                doc_id=doc.id,
                title=doc.title,
                source=doc.source,
                url=doc.url,
                published_at=published.isoformat(),
            )
        )
    return "\n".join(parts), citations


def freshness_note(docs: list[EvidenceDoc], *, now: datetime) -> str:
    """Human-readable freshness statement — stale evidence must lower confidence (S0.3 rule)."""
    if not docs:
        return "No supporting evidence documents were retrieved."
    newest = max(
        d.published_at if d.published_at.tzinfo else d.published_at.replace(tzinfo=UTC)
        for d in docs
    )
    age_days = (now - newest).days
    return f"Most recent evidence is {age_days} day(s) old."
