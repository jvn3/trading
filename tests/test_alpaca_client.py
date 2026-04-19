"""Tests for the Alpaca client wrapper (no network)."""
from __future__ import annotations

import pytest

from jay_trading.config import get_settings


def test_alpaca_wrapper_refuses_live_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bypass the Settings-level validator to simulate an attacker/mistake that
    # somehow injected a live URL after settings were loaded.
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="paper-"):
        # Just constructing Settings should fail.
        get_settings()
