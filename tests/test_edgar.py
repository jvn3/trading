"""Tests for :mod:`jay_trading.data.edgar` (offline-only).

Network tests are skipped; we exercise the pattern matcher and the
URL-resolution logic via monkeypatched responses.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx

from jay_trading.data import edgar


class _FakeResp:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


def test_10b5_1_pattern_matches_variants() -> None:
    assert edgar._10B5_1_PATTERN.search("Sale made under a 10b5-1 plan") is not None
    assert edgar._10B5_1_PATTERN.search("rule 10b51 plan") is not None  # no hyphen
    assert edgar._10B5_1_PATTERN.search("RULE 10b5-1") is not None  # case-insensitive
    assert edgar._10B5_1_PATTERN.search("ordinary insider purchase") is None


def test_index_to_xml_picks_form4_when_present(monkeypatch: Any) -> None:
    index_html = """
    <html><body>
    <a href="wk-form4_123.xml">Form 4 XML</a>
    <a href="form4_schema.xsd">schema</a>
    </body></html>
    """
    monkeypatch.setattr(edgar, "_fetch", lambda url: _FakeResp(200, index_html))
    url = "https://www.sec.gov/Archives/edgar/data/123/000012300000001/0000123-00-000001-index.htm"
    result = edgar._index_url_to_xml(url)
    assert result is not None
    assert result.endswith("wk-form4_123.xml")


def test_index_to_xml_returns_none_on_404(monkeypatch: Any) -> None:
    monkeypatch.setattr(edgar, "_fetch", lambda url: _FakeResp(404, ""))
    assert edgar._index_url_to_xml("http://x/foo-index.htm") is None


def test_check_10b5_1_flags_positive_on_footnote(monkeypatch: Any) -> None:
    index_html = '<a href="form4.xml">x</a>'
    xml_body = """<?xml version="1.0"?>
    <ownershipDocument>
        <footnotes>
            <footnote id="F1">Sales executed pursuant to a Rule 10b5-1 trading plan</footnote>
        </footnotes>
    </ownershipDocument>
    """

    def fake_fetch(url: str, *, timeout: float = 15.0) -> _FakeResp:
        if url.endswith("-index.htm"):
            return _FakeResp(200, index_html)
        return _FakeResp(200, xml_body)

    monkeypatch.setattr(edgar, "_fetch", fake_fetch)
    result = edgar.check_10b5_1(
        "https://www.sec.gov/Archives/edgar/data/123/000012300000001/foo-index.htm"
    )
    assert result.fetched is True
    assert result.has_10b5_1 is True


def test_check_10b5_1_returns_false_when_no_match(monkeypatch: Any) -> None:
    index_html = '<a href="form4.xml">x</a>'
    xml_body = "<ownershipDocument><footnotes></footnotes></ownershipDocument>"

    def fake_fetch(url: str, **_: Any) -> _FakeResp:
        if url.endswith("-index.htm"):
            return _FakeResp(200, index_html)
        return _FakeResp(200, xml_body)

    monkeypatch.setattr(edgar, "_fetch", fake_fetch)
    result = edgar.check_10b5_1(
        "https://www.sec.gov/Archives/edgar/data/123/000012300000001/foo-index.htm"
    )
    assert result.fetched is True
    assert result.has_10b5_1 is False


def test_check_10b5_1_returns_fetched_false_on_exception(monkeypatch: Any) -> None:
    def boom(*_a: Any, **_k: Any) -> _FakeResp:
        raise httpx.ConnectError("simulated")

    monkeypatch.setattr(edgar, "_fetch", boom)
    result = edgar.check_10b5_1("http://x/foo-index.htm")
    assert result.fetched is False
    assert result.has_10b5_1 is None


def test_empty_url_returns_not_fetched() -> None:
    result = edgar.check_10b5_1("")
    assert result.fetched is False
    assert result.has_10b5_1 is None
