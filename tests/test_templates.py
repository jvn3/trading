"""Render jinja2 templates and check they're valid markdown-ish structures."""
from __future__ import annotations

from jay_trading.vault.templates import render_data_briefing, render_phase_complete


def test_data_briefing_renders_with_empty_inputs() -> None:
    md = render_data_briefing(
        date="2026-04-19",
        generated_at="2026-04-19T12:00:00+00:00",
        report={"inserted": 0, "skipped": 0, "total_seen": 0},
        counts={},
        senate_new=[],
        house_new=[],
        insider_new=[],
        top_tickers=[],
    )
    assert md.startswith("---\n")
    assert "Data ingestion" in md
    assert "_(no rows yet)_" in md


def test_data_briefing_renders_rows() -> None:
    md = render_data_briefing(
        date="2026-04-19",
        generated_at="2026-04-19T12:00:00+00:00",
        report={"inserted": 3, "skipped": 1, "total_seen": 4},
        counts={"senate": 2, "house": 1},
        senate_new=[{
            "person_name": "Jane Doe", "ticker": "NVDA",
            "transaction_type": "buy", "transaction_date": "2026-04-10",
            "filing_date": "2026-04-14", "amount_range": "$15,001–$50,000",
        }],
        house_new=[],
        insider_new=[],
        top_tickers=[("NVDA", 2), ("AAPL", 1)],
    )
    assert "| Jane Doe | NVDA | buy |" in md
    assert "| NVDA | 2 |" in md


def test_phase_complete_checklist() -> None:
    md = render_phase_complete(
        phase=0,
        date="2026-04-19",
        built=["project scaffold", "vault structure"],
        tested=["config validation", "vault atomic write"],
        deferred=["systemd unit install"],
        acceptance=[
            {"ok": True, "text": "smoke test passes", "note": ""},
            {"ok": False, "text": "MCP server installed", "note": "user-side"},
        ],
        next_step="Phase 1: data layer",
    )
    assert "- [x] smoke test passes" in md
    assert "- [ ] MCP server installed — user-side" in md
