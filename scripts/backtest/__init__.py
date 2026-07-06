"""M1 backtest harness: data fetching, metrics, vectorized engine, strategies.

Everything here is standalone from ``jay_trading`` — it is the gate that
strategies must pass (beat buy-and-hold) before they touch the live paper loop.
"""
