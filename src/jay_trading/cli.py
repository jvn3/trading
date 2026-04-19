"""Thin CLI entry point used by the ``jay-trading`` script."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("jay-trading — subcommands: smoke-test, ingest, serve")
        return 0
    cmd = argv[0]
    if cmd == "smoke-test":
        from scripts.smoke_test import run  # pragma: no cover
        return run()
    if cmd == "ingest":
        from jay_trading.schedule.jobs import ingest_disclosures

        ingest_disclosures()
        return 0
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
