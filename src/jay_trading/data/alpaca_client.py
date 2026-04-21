"""Thin wrapper over ``alpaca-py``.

The wrapper enforces paper-only routing at construction time so any future
caller who wires the live URL in by mistake gets a loud failure instead of a
silent live order.

Every outbound call is logged to ``api_call_log`` via
:func:`jay_trading.data.store.record_api_call`, feeding the
``api_health`` circuit breaker in :mod:`jay_trading.risk.guards`.
"""
from __future__ import annotations

import logging
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from alpaca.trading.client import TradingClient

from jay_trading.config import get_settings

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _tracked(endpoint: str) -> Callable[[F], F]:
    """Wrap an Alpaca call, logging ``ok``/``fail`` to ``api_call_log``."""

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                _log_alpaca_call(endpoint, "fail",
                                 latency_ms=(time.monotonic() - start) * 1000,
                                 error_kind=type(e).__name__)
                raise
            _log_alpaca_call(endpoint, "ok",
                             latency_ms=(time.monotonic() - start) * 1000,
                             error_kind=None)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _log_alpaca_call(endpoint: str, status: str, *, latency_ms: float,
                     error_kind: str | None) -> None:
    try:
        from jay_trading.data import store
        store.record_api_call(
            provider="alpaca", endpoint=endpoint, status=status,
            latency_ms=latency_ms, error_kind=error_kind,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("api-call-log for alpaca %s failed: %s", endpoint, e)


class AlpacaPaperClient:
    """A paper-only Alpaca trading client.

    Construction raises if the configured base URL does not include ``paper-``.
    """

    def __init__(self) -> None:
        s = get_settings()
        if "paper-" not in s.alpaca_base_url:
            # Belt + suspenders: config.py already enforces this, but we want
            # the failure as close to the API call site as possible.
            raise RuntimeError(
                f"Refusing to construct trading client for non-paper URL "
                f"{s.alpaca_base_url!r}"
            )
        self._client = TradingClient(
            api_key=s.alpaca_api_key,
            secret_key=s.alpaca_secret_key,
            paper=True,
        )
        self._expected_account_id = s.alpaca_account_id

    # Account / portfolio -----------------------------------------------------

    @_tracked("get_account")
    def get_account(self) -> Any:
        acct = self._client.get_account()
        if self._expected_account_id and str(acct.account_number) != self._expected_account_id:
            raise RuntimeError(
                f"ALPACA_ACCOUNT_ID mismatch: .env has "
                f"{self._expected_account_id!r} but API returned "
                f"{acct.account_number!r}. Refusing to continue."
            )
        return acct

    @_tracked("get_positions")
    def get_positions(self) -> list[Any]:
        return list(self._client.get_all_positions())

    @_tracked("get_orders")
    def get_orders(self, status: str = "all", after: str | None = None) -> list[Any]:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        req = GetOrdersRequest(status=QueryOrderStatus(status), after=after)
        return list(self._client.get_orders(filter=req))

    # Thin passthrough; order construction lives in executor.order_builder.
    @_tracked("submit_order")
    def submit_order(self, order_request: Any) -> Any:
        return self._client.submit_order(order_request)

    @_tracked("close_position")
    def close_position(self, symbol: str, qty: float | None = None) -> Any:
        from alpaca.trading.requests import ClosePositionRequest

        req = ClosePositionRequest(qty=str(qty)) if qty is not None else None
        return self._client.close_position(symbol_or_asset_id=symbol, close_options=req)

    @property
    def raw(self) -> TradingClient:
        """Escape hatch for the rare caller that needs the underlying client."""
        return self._client
