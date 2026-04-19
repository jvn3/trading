"""Tests for :mod:`jay_trading.vault.writer`."""
from __future__ import annotations

from jay_trading.config import get_settings
from jay_trading.vault.writer import write_vault_file


def test_write_vault_file_creates_parents_and_file() -> None:
    p = write_vault_file("briefings/test.md", "hello")
    assert p.exists()
    assert p.read_text(encoding="utf-8") == "hello"
    assert p.is_relative_to(get_settings().vault_trading_root)


def test_write_vault_file_overwrites_atomically() -> None:
    write_vault_file("briefings/a.md", "v1")
    p = write_vault_file("briefings/a.md", "v2")
    assert p.read_text(encoding="utf-8") == "v2"


def test_write_vault_file_leaves_no_tmp_files() -> None:
    write_vault_file("trades/tmp_check.md", "x")
    root = get_settings().vault_trading_root
    stragglers = list(root.rglob(".tmp_*"))
    assert stragglers == [], f"stray tmp files: {stragglers}"
