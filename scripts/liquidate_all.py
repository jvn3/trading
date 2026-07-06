"""Liquidate every open position on the paper account (M0 clean-slate reset).

Approved in redesign-2026-07-05.md: the 9 positions held through the
2026-05-13 → 07-06 outage are an accident of drift, not a portfolio; the
rebuild starts from cash. Submits market DAY closes for all positions via
Alpaca's close-all endpoint. Outside market hours the orders queue to the
next open (or are rejected per-position — the per-position HTTP status is
printed either way).

Run: uv run python scripts/liquidate_all.py --yes
"""
from __future__ import annotations

import sys

from jay_trading.data.alpaca_client import AlpacaPaperClient


def main() -> int:
    if "--yes" not in sys.argv:
        print("Refusing without --yes (this closes every open position).")
        return 2

    alpaca = AlpacaPaperClient()
    positions = alpaca.get_positions()
    if not positions:
        print("No open positions.")
        return 0

    print(f"Closing {len(positions)} positions:")
    for p in positions:
        print(f"  {p.symbol:6s} qty={p.qty} mv=${float(p.market_value):.2f} "
              f"pl=${float(p.unrealized_pl):+.2f}")

    results = alpaca.raw.close_all_positions(cancel_orders=True)
    print("\nClose-all responses:")
    failures = 0
    for r in results:
        status = getattr(r, "status", None)
        symbol = getattr(r, "symbol", "?")
        ok = status in (200, 207, None) or (isinstance(status, int) and status < 400)
        if not ok:
            failures += 1
        body = getattr(r, "body", None)
        order_status = getattr(body, "status", "?") if body is not None else "?"
        print(f"  {symbol:6s} http={status} order_status={order_status}")

    print(f"\n{'ALL CLOSES SUBMITTED' if failures == 0 else f'{failures} FAILURES — inspect above'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
