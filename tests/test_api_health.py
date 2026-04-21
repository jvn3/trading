"""Tests for :mod:`jay_trading.risk.api_health`."""
from __future__ import annotations

import time

from jay_trading.data import store
from jay_trading.data.db import create_all
from jay_trading.risk import api_health


def test_summary_reports_zeros_with_no_data() -> None:
    create_all()
    s = api_health.summary("fmp")
    assert s.provider == "fmp"
    assert s.fails == 0
    assert s.total == 0
    assert s.fail_rate == 0.0
    assert s.enough_data is False


def test_summary_computes_fail_rate() -> None:
    create_all()
    for _ in range(4):
        store.record_api_call("fmp", "/stable/quote", "fail", 100.0, "http_500")
    for _ in range(6):
        store.record_api_call("fmp", "/stable/quote", "ok", 80.0)
    s = api_health.summary("fmp")
    assert s.fails == 4
    assert s.total == 10
    assert s.fail_rate == 0.4
    assert s.enough_data is True


def test_ttl_cache_respects_expiry() -> None:
    cache = api_health.TTLCache(default_ttl_sec=0.15)
    cache.set("x", 1)
    assert cache.get("x") == 1
    time.sleep(0.25)  # comfortably above Windows monotonic resolution
    assert cache.get("x") is None


def test_ttl_cache_per_key_ttl_override() -> None:
    cache = api_health.TTLCache(default_ttl_sec=60.0)
    cache.set("short", "v", ttl_sec=0.1)
    cache.set("long", "w")
    time.sleep(0.25)
    assert cache.get("short") is None
    assert cache.get("long") == "w"
