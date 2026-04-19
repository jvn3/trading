# jay-trading

Paper-only trading system driven by congressional (STOCK Act) and corporate insider
(Form 4) disclosure signals, executed against Alpaca's paper API. Starting equity
$10,000. See `implementation_plan.md` for the full spec.

## Safety posture

- **Alpaca paper only.** `ALPACA_BASE_URL` is validated at startup to contain `paper-`;
  misconfiguration raises before any client is constructed.
- Every order requires a rationale markdown note written to the Obsidian vault
  before submission. If the write fails, the order does not ship.
- Strategies ship in shadow mode for >=7 days before any live paper execution, and
  only flip live after explicit user approval.

## Repo layout

- `src/jay_trading/config.py` — pydantic settings loaded from `.env`
- `src/jay_trading/data/` — FMP + Alpaca clients, SQLAlchemy models, DAO
- `src/jay_trading/signals/` — politician scorer, cluster detectors
- `src/jay_trading/strategies/` — `Strategy` base class + concrete strategies
- `src/jay_trading/risk/` — sizing, portfolio heat, circuit breakers, stops
- `src/jay_trading/executor/` — order builder, fill reconciliation
- `src/jay_trading/vault/` — jinja2 templates + atomic markdown writer
- `src/jay_trading/schedule/` — APScheduler jobs + service bootstrap
- `scripts/` — one-off utilities (`smoke_test.py`, `reset_paper_to_10k.py`, ...)
- `tests/` — pytest + VCR cassettes

## Local development

```bash
# In WSL
cd /mnt/k/trading
uv sync
cp .env.example .env   # then fill in real values
uv run python scripts/smoke_test.py
uv run pytest
```

## Status

Phase tracking lives in the Obsidian vault at `trading/briefings/phase_*_complete.md`.
