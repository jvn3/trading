"""Shared pytest fixtures.

Highlights:
- ``pytest-vcr``-style cassette directory is on each test via ``vcr_cassette_dir``.
- ``settings`` fixture provides a test ``Settings`` instance with in-memory SQLite
  and temp vault, so tests never touch the real env.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Default: every test runs with fake credentials and a temp vault."""
    monkeypatch.setenv("ALPACA_API_KEY", "TEST_KEY")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "TEST_SECRET")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("FMP_API_KEY", "TEST_FMP_KEY")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_URL", f"sqlite:///{tmp_path / 'jay_trading.db'}")
    (tmp_path / "vault").mkdir()
    (tmp_path / "data").mkdir()
    # Reset the lru_cache so each test gets a fresh Settings
    from jay_trading.config import get_settings
    from jay_trading.data.db import _reset_for_tests

    get_settings.cache_clear()
    _reset_for_tests()
    yield
    get_settings.cache_clear()
    _reset_for_tests()


@pytest.fixture
def cassette_dir() -> Path:
    return Path(__file__).parent / "cassettes"
