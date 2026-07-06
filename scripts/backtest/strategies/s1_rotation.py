"""S1: regime-gated leveraged rotation on QQQ's long moving average.

Rule (evaluated on QQQ closes):
- QQQ close > ``ma_len``-day SMA  -> risk-on
- QQQ close <= SMA (or SMA not yet defined during warmup) -> 100% cash

Variants (allocation while risk-on):
- ``tqqq``:     100% TQQQ
- ``qqq_only``: 100% QQQ
- ``blend``:    50% TQQQ / 50% QQQ

This is a PURE function: no I/O, no state. It emits TARGET weights per day;
the engine applies them with a 1-day shift (next-day convention), so using
day t's close in day t's signal here is not lookahead.
"""
from __future__ import annotations

import pandas as pd

VARIANTS = ("tqqq", "qqq_only", "blend")


def signal_weights(qqq: pd.Series, ma_len: int = 200, variant: str = "tqqq") -> pd.DataFrame:
    """Target weights over {TQQQ, QQQ} (cash = remainder) from QQQ closes."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")
    if ma_len < 1:
        raise ValueError("ma_len must be >= 1")

    sma = qqq.rolling(ma_len).mean()
    # NaN SMA during warmup compares False -> cash, as intended.
    risk_on = (qqq > sma).astype(float)

    weights = pd.DataFrame(0.0, index=qqq.index, columns=["TQQQ", "QQQ"])
    if variant == "tqqq":
        weights["TQQQ"] = risk_on
    elif variant == "qqq_only":
        weights["QQQ"] = risk_on
    else:  # blend
        weights["TQQQ"] = 0.5 * risk_on
        weights["QQQ"] = 0.5 * risk_on
    return weights
