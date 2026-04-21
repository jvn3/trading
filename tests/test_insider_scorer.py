"""Tests for :mod:`jay_trading.signals.insider_scorer` role parser."""
from __future__ import annotations

import pytest

from jay_trading.signals import insider_scorer


@pytest.mark.parametrize(
    "raw,expected_label,expected_weight",
    [
        ("officer: President, CEO", "CEO", 3.0),
        ("CEO", "CEO", 3.0),
        ("Chief Executive Officer", "CEO", 3.0),
        ("officer: CFO", "CFO", 2.5),
        ("Chief Financial Officer", "CFO", 2.5),
        ("Chief Operating Officer", "COO", 2.0),
        ("10 percent owner", "10% holder", 1.5),
        ("10% owner", "10% holder", 1.5),
        ("director", "Director", 1.0),
        ("officer: EVP, Chief Human Resources Off", "Officer", 1.2),
        ("", "Other", 0.8),
        (None, "Other", 0.8),
        ("something random", "Other", 0.8),
    ],
)
def test_role_weight_mapping(raw: str | None, expected_label: str, expected_weight: float) -> None:
    rw = insider_scorer.role_weight(raw)
    assert rw.label == expected_label
    assert rw.weight == expected_weight


def test_role_weight_highest_wins_when_multiple_match() -> None:
    # "officer: President, CEO" matches both CEO (3.0) and Officer (1.2).
    rw = insider_scorer.role_weight("officer: President, CEO")
    assert rw.weight == 3.0
    assert rw.label == "CEO"


@pytest.mark.parametrize(
    "score,expected",
    [(0, 0.6), (4, 0.6), (5, 1.0), (6, 1.0), (7, 1.2), (9, 1.2), (None, 0.6)],
)
def test_piotroski_multiplier(score: int | None, expected: float) -> None:
    assert insider_scorer.piotroski_multiplier(score) == expected


def test_recency_multiplier() -> None:
    assert insider_scorer.recency_multiplier(0) == 1.1
    assert insider_scorer.recency_multiplier(5) == 1.1
    assert insider_scorer.recency_multiplier(6) == 1.0
    assert insider_scorer.recency_multiplier(30) == 1.0
