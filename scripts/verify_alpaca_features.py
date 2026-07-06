"""One-shot verification of paper-account capabilities (M0 checklist).

Checks, read-only except one deliberately-unfillable test order:
1. Account flags: PDT status, multiplier, shorting, options level, crypto.
2. Bracket-order support: submit a whole-share LIMIT buy far below market
   with take-profit + stop-loss legs, confirm Alpaca accepts it and creates
   the legs, then cancel it. Never fills (limit ~50% under market).

Run: uv run python scripts/verify_alpaca_features.py
"""
from __future__ import annotations

import sys

from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import (
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from jay_trading.data.alpaca_client import AlpacaPaperClient


def main() -> int:
    alpaca = AlpacaPaperClient()
    acct = alpaca.get_account()

    print("== Account capability flags ==")
    for field in (
        "account_number", "status", "equity", "buying_power", "multiplier",
        "pattern_day_trader", "daytrade_count", "daytrading_buying_power",
        "shorting_enabled", "options_trading_level", "crypto_status",
    ):
        print(f"  {field}: {getattr(acct, field, '<absent>')}")

    print("\n== Bracket order test (limit far below market; will not fill) ==")
    # SPY ~ $740; a $370 limit cannot fill. Whole share (qty=1) because
    # bracket orders require whole shares.
    req = LimitOrderRequest(
        symbol="SPY",
        qty=1,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
        limit_price=370.00,
        order_class="bracket",
        take_profit=TakeProfitRequest(limit_price=400.00),
        stop_loss=StopLossRequest(stop_price=350.00),
    )
    try:
        order = alpaca.submit_order(req)
    except Exception as e:  # noqa: BLE001
        print(f"  BRACKET REJECTED at submit: {type(e).__name__}: {e}")
        return 1
    print(f"  submitted: id={order.id} status={order.status} class={order.order_class}")
    legs = getattr(order, "legs", None) or []
    print(f"  legs: {len(legs)}")
    for leg in legs:
        print(f"    leg: type={leg.order_type} status={leg.status}")
    ok = len(legs) == 2

    try:
        alpaca.raw.cancel_order_by_id(order.id)
        print("  test order canceled OK")
    except Exception as e:  # noqa: BLE001
        print(f"  WARNING: cancel failed ({e}) — cancel manually: {order.id}")

    print(f"\nBRACKET SUPPORT: {'CONFIRMED (2 legs created)' if ok else 'NOT CONFIRMED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
