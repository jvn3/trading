"""Quick operator sanity check: account + orders + positions."""
from __future__ import annotations

from jay_trading.data.alpaca_client import AlpacaPaperClient


def main() -> int:
    a = AlpacaPaperClient()
    acct = a.get_account()
    print(f"Account {acct.account_number} ({acct.status}):")
    print(f"  equity=${float(acct.equity):,.2f}")
    print(f"  cash=${float(acct.cash):,.2f}")
    print(f"  buying_power=${float(acct.buying_power):,.2f}")
    print()

    print("Open orders:")
    opens = a.get_orders(status="open")
    if not opens:
        print("  (none)")
    for o in opens:
        n = o.notional or "-"
        q = o.qty or "-"
        print(
            f"  {o.id} {o.symbol} {o.side} notional={n} qty={q} "
            f"status={o.status} client_order_id={o.client_order_id}"
        )
    print()

    print("All orders (last 10):")
    for o in a.get_orders(status="all")[:10]:
        n = o.notional or "-"
        print(f"  {o.symbol:6s} {o.side:4s} notional={n} status={o.status} id={o.id}")
    print()

    print("Positions:")
    positions = a.get_positions()
    if not positions:
        print("  (none)")
    for p in positions:
        print(
            f"  {p.symbol} qty={p.qty} avg=${p.avg_entry_price} "
            f"market_value=${p.market_value} unrealized_pl=${p.unrealized_pl}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
