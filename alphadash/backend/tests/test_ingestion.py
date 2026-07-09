"""S1.2 tests: snapshot persisted with citations + timestamps, degraded feeds recorded."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from alphadash.db.base import Base
from alphadash.db.models import DataSnapshot
from alphadash.providers.factory import ProviderBundle, build_stub_bundle
from alphadash.providers.stub import FIXTURE_AS_OF
from alphadash.services.ingestion import snapshot_market_context

NOW = FIXTURE_AS_OF + timedelta(hours=1)


@pytest.fixture()
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_snapshot_persists_cited_timestamped_payload(session: Session) -> None:
    snap = snapshot_market_context(
        session,
        build_stub_bundle(),
        ["AAPL", "MSFT"],
        news_since=NOW - timedelta(days=7),
        macro_series=["FEDFUNDS"],
        now=NOW,
    )
    session.commit()

    stored = session.get(DataSnapshot, snap.id)
    p = stored.payload
    assert p["as_of"] == NOW.isoformat()
    assert p["symbols"] == ["AAPL", "MSFT"]
    assert len(p["quotes"]) == 2
    # Citations: every quote carries provenance with source + as_of
    q = p["quotes"][0]
    assert q["provenance"]["source"] == "stub"
    assert "as_of" in q["provenance"]
    # Decimal-as-string over JSON, never float
    assert isinstance(q["price"], str)
    assert p["news"], "stub news expected"
    assert all("published_at" in n and "source" in n for n in p["news"])
    assert p["macro"]["FEDFUNDS"]
    assert all(isinstance(pt["value"], str) for pt in p["macro"]["FEDFUNDS"])
    assert p["errors"] == []


class ExplodingNews:
    def get_news(self, symbols, since, limit=50):
        raise RuntimeError("news API down")


def test_failing_feed_degrades_snapshot_not_kills_it(session: Session) -> None:
    stub = build_stub_bundle()
    bundle = ProviderBundle(
        market_data=stub.market_data,
        news=ExplodingNews(),
        fundamentals=stub.fundamentals,
        macro=stub.macro,
    )
    snap = snapshot_market_context(
        session,
        bundle,
        ["AAPL"],
        news_since=NOW - timedelta(days=7),
        macro_series=[],
        now=NOW,
    )
    session.commit()
    p = session.get(DataSnapshot, snap.id).payload
    assert p["quotes"], "healthy feeds still ingested"
    assert p["news"] == []
    assert p["errors"] == [{"feed": "news", "symbol": None, "error": "news API down"}]


@pytest.mark.integration
def test_live_snapshot() -> None:
    from alphadash.config import get_settings
    from alphadash.providers.factory import build_real_bundle

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        snap = snapshot_market_context(
            s,
            build_real_bundle(get_settings()),
            ["AAPL"],
            news_since=datetime.now(UTC) - timedelta(days=7),
            macro_series=["FEDFUNDS"],
            now=datetime.now(UTC),
        )
        s.commit()
        assert snap.payload["quotes"] and not snap.payload["errors"]
