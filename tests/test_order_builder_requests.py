"""M2 executor tests: TradeIntent → Alpaca request building (crypto TIF,
OTO stop legs, limit orders). Pure request construction — no network."""
from __future__ import annotations

from alpaca.trading.enums import OrderClass, TimeInForce
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

from jay_trading.executor.order_builder import _build_request, is_crypto
from jay_trading.strategies.base import TradeIntent


def _intent(**kw) -> TradeIntent:
    base = dict(strategy_name="t", ticker="SPY", side="buy", notional=500.0)
    base.update(kw)
    return TradeIntent(**base)


def test_is_crypto_detection() -> None:
    assert is_crypto("BTCUSD") and is_crypto("BTC/USD") and is_crypto("ETHUSD")
    assert not is_crypto("SPY") and not is_crypto("TQQQ")


def test_equity_default_is_day_market_notional() -> None:
    req = _build_request(_intent(), "cid")
    assert isinstance(req, MarketOrderRequest)
    assert req.time_in_force == TimeInForce.DAY
    assert req.notional == 500.0 and req.qty is None


def test_crypto_forces_gtc() -> None:
    req = _build_request(
        _intent(ticker="BTCUSD", time_in_force="day"), "cid"
    )
    assert req.time_in_force == TimeInForce.GTC


def test_crypto_honors_ioc() -> None:
    req = _build_request(
        _intent(ticker="ETHUSD", time_in_force="ioc"), "cid"
    )
    assert req.time_in_force == TimeInForce.IOC


def test_whole_share_buy_with_stop_gets_oto_leg() -> None:
    req = _build_request(
        _intent(notional=None, qty=10.0, stop_price=90.0), "cid"
    )
    assert isinstance(req, MarketOrderRequest)
    assert req.order_class == OrderClass.OTO
    assert req.stop_loss is not None
    assert float(req.stop_loss.stop_price) == 90.0


def test_fractional_stop_falls_back_to_plain_market() -> None:
    req = _build_request(
        _intent(notional=None, qty=1.5, stop_price=90.0), "cid"
    )
    assert isinstance(req, MarketOrderRequest)
    assert getattr(req, "order_class", None) != OrderClass.OTO
    assert getattr(req, "stop_loss", None) is None


def test_notional_stop_falls_back_to_plain_market() -> None:
    req = _build_request(_intent(stop_price=90.0), "cid")
    assert isinstance(req, MarketOrderRequest)
    assert getattr(req, "stop_loss", None) is None


def test_crypto_never_gets_stop_leg() -> None:
    req = _build_request(
        _intent(ticker="BTCUSD", notional=None, qty=1.0, stop_price=50_000.0),
        "cid",
    )
    assert isinstance(req, MarketOrderRequest)
    assert getattr(req, "stop_loss", None) is None


def test_sell_close_never_gets_stop_leg() -> None:
    req = _build_request(
        _intent(side="sell", notional=None, qty=10.0, stop_price=90.0,
                action="close"),
        "cid",
    )
    assert isinstance(req, MarketOrderRequest)
    assert getattr(req, "stop_loss", None) is None


def test_limit_order_built_when_requested() -> None:
    req = _build_request(
        _intent(order_type="limit", limit_price=450.25), "cid"
    )
    assert isinstance(req, LimitOrderRequest)
    assert float(req.limit_price) == 450.25
