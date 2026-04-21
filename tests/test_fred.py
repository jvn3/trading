"""Tests for the FRED CSV client (used by Strategy V macro regime)."""
from __future__ import annotations

from datetime import date

import pytest

from jay_trading.data import fred


# ---- _parse_csv pure parser tests ---------------------------------------


def test_parse_csv_happy_path() -> None:
    csv = "DATE,VIXCLS\n2026-04-15,17.42\n2026-04-16,18.10\n"
    rows = fred._parse_csv("VIXCLS", csv)
    assert len(rows) == 2
    assert rows[0] == fred.Observation(date=date(2026, 4, 15), value=17.42)
    assert rows[1].value == 18.10


def test_parse_csv_preserves_missing_values_as_none() -> None:
    # FRED writes "." for non-trading days / missing observations.
    csv = "DATE,VIXCLS\n2026-04-15,17.42\n2026-04-16,.\n2026-04-17,18.55\n"
    rows = fred._parse_csv("VIXCLS", csv)
    assert [r.value for r in rows] == [17.42, None, 18.55]


def test_parse_csv_skips_malformed_dates() -> None:
    csv = "DATE,VIXCLS\nnot-a-date,17.42\n2026-04-16,18.10\n"
    rows = fred._parse_csv("VIXCLS", csv)
    assert len(rows) == 1
    assert rows[0].date == date(2026, 4, 16)


def test_parse_csv_rejects_unexpected_header() -> None:
    csv = "FOO,BAR\n2026-04-15,17.42\n"
    with pytest.raises(fred.FREDError, match="unexpected header"):
        fred._parse_csv("VIXCLS", csv)


def test_parse_csv_rejects_empty_body() -> None:
    with pytest.raises(fred.FREDError, match="empty CSV body"):
        fred._parse_csv("VIXCLS", "")


# ---- helper: series_values + moving_average -----------------------------


def test_series_values_drops_none() -> None:
    obs = [
        fred.Observation(date(2026, 1, 1), 1.0),
        fred.Observation(date(2026, 1, 2), None),
        fred.Observation(date(2026, 1, 3), 2.0),
    ]
    assert fred.series_values(obs) == [1.0, 2.0]


def test_moving_average_basic() -> None:
    assert fred.moving_average([10.0, 20.0, 30.0], 3) == 20.0
    assert fred.moving_average([1.0, 2.0, 3.0, 4.0, 5.0], 3) == 4.0  # mean of [3,4,5]


def test_moving_average_returns_none_when_window_too_large() -> None:
    assert fred.moving_average([1.0, 2.0], 5) is None
    assert fred.moving_average([], 1) is None


def test_moving_average_rejects_nonpositive_window() -> None:
    assert fred.moving_average([1.0, 2.0, 3.0], 0) is None


# ---- Client behaviour with injected fetcher -----------------------------


def test_accepts_observation_date_header() -> None:
    # FRED's actual CSV header (post-2024) — must accept this not just "DATE".
    csv = "observation_date,VIXCLS\n2026-04-15,17.42\n2026-04-16,18.10\n"
    client = fred.FREDClient(fetcher=lambda _id: csv)
    rows = client.get_series("VIXCLS")
    assert [r.value for r in rows] == [17.42, 18.10]


def test_get_series_via_injected_fetcher() -> None:
    csv = "DATE,T10Y2Y\n2026-04-15,0.55\n2026-04-16,0.60\n"
    client = fred.FREDClient(fetcher=lambda _id: csv)
    rows = client.get_series("T10Y2Y")
    assert [r.value for r in rows] == [0.55, 0.60]


def test_latest_skips_trailing_none() -> None:
    csv = (
        "observation_date,VIXCLS\n"
        "2026-04-15,17.42\n"
        "2026-04-16,18.10\n"
        "2026-04-17,.\n"
    )
    client = fred.FREDClient(fetcher=lambda _id: csv)
    latest = client.latest("VIXCLS")
    assert latest is not None
    assert latest.date == date(2026, 4, 16)
    assert latest.value == 18.10


def test_fetcher_error_propagates() -> None:
    def boom(_id: str) -> str:
        raise fred.FREDError("simulated failure")

    client = fred.FREDClient(fetcher=boom)
    with pytest.raises(fred.FREDError, match="simulated failure"):
        client.get_series("VIXCLS")
