"""Provider wiring (S1.1): build real providers from settings, or the stub bundle for tests/dev."""

from __future__ import annotations

from dataclasses import dataclass

from alphadash.config import Settings
from alphadash.providers.base import (
    FundamentalsProvider,
    MacroProvider,
    MarketDataProvider,
    NewsProvider,
)
from alphadash.providers.stub import StubProviders


@dataclass(frozen=True)
class ProviderBundle:
    market_data: MarketDataProvider
    news: NewsProvider
    fundamentals: FundamentalsProvider
    macro: MacroProvider


def build_stub_bundle() -> ProviderBundle:
    stub = StubProviders()
    return ProviderBundle(market_data=stub, news=stub, fundamentals=stub, macro=stub)


def build_real_bundle(settings: Settings) -> ProviderBundle:
    """Construct the jay_trading-backed providers. Imports deferred so unit tests and the stub
    path never touch the engine package."""
    from jay_trading.data.fmp import FMPClient
    from jay_trading.data.fred import FREDClient

    from alphadash.providers.real import (
        FMPFundamentalsProvider,
        FMPMarketDataProvider,
        FMPNewsProvider,
        FREDMacroProvider,
    )

    api_key = settings.fmp_api_key or _root_env_fmp_key()
    fmp = FMPClient(api_key=api_key)
    fred = FREDClient()
    return ProviderBundle(
        market_data=FMPMarketDataProvider(fmp),
        news=FMPNewsProvider(api_key=api_key),
        fundamentals=FMPFundamentalsProvider(fmp),
        macro=FREDMacroProvider(fred),
    )


def _root_env_fmp_key() -> str:
    """Dev fallback: pull FMP_API_KEY from the engine repo's root .env.

    The engine's own Settings loads ``.env`` relative to the CWD (and demands Alpaca keys we
    don't need), so it can't be used from the alphadash process. Deployment sets
    ``ALPHADASH_FMP_API_KEY`` explicitly instead.
    """
    from pathlib import Path

    from dotenv import dotenv_values

    root_env = Path(__file__).resolve().parents[4].parent / ".env"
    key = dotenv_values(root_env).get("FMP_API_KEY") if root_env.exists() else None
    if not key:
        raise RuntimeError(
            "No FMP API key: set ALPHADASH_FMP_API_KEY (or FMP_API_KEY in the repo root .env)"
        )
    return key


def build_bundle(settings: Settings) -> ProviderBundle:
    return build_stub_bundle() if settings.providers == "stub" else build_real_bundle(settings)
