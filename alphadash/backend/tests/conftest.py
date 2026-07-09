"""Shared test config: integration tests only run when explicitly requested."""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("ALPHADASH_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="integration test; set ALPHADASH_RUN_INTEGRATION=1 to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
