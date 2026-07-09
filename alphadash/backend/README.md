# AlphaDash backend

FastAPI BFF + services for the beginner strategy-agent product. Isolated from the personal
`jay-trading` engine (own `pyproject.toml` / `uv.lock`).

## Develop

```
uv sync                 # resolve + install into a local venv
uv run pytest           # run the test suite (S0.1: /health)
uv run ruff check .     # lint
uv run ruff format .    # format
uv run uvicorn alphadash.main:app --reload --port 8000
```

`GET /health` → `{ "status": "ok", "version": "...", "trading_mode": "paper" }`.

## Config

Settings come from `ALPHADASH_`-prefixed env vars or a local `.env` (see `.env.example`).
`trading_mode` defaults to `paper` and is a hard product invariant — see the blueprint §13.4 / §16.

## Reusing the personal engine (from S1.1)

The `jay_trading` package (`../../src/jay_trading`) already provides Alpaca/FMP/FRED/EDGAR adapters,
risk guards, sizing, and executor primitives. S1.1 adds:

```toml
[tool.uv.sources]
jay-trading = { path = "../..", editable = true }
```

and the corresponding `dependencies` entry, then imports behind the provider interfaces (S0.3).
