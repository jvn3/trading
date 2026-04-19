"""Tests for :mod:`jay_trading.config`."""
from __future__ import annotations

import pytest

from jay_trading.config import Settings, get_settings


def test_settings_load_from_env() -> None:
    s = get_settings()
    assert s.alpaca_api_key == "TEST_KEY"
    assert "paper-" in s.alpaca_base_url


def test_rejects_live_alpaca_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="paper-"):
        Settings()  # type: ignore[call-arg]


def test_vault_trading_root_points_into_vault() -> None:
    s = get_settings()
    assert s.vault_trading_root == s.obsidian_vault_path
