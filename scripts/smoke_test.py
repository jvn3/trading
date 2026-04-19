"""Phase 0 smoke test.

Three round-trips, all must succeed:

1. Alpaca paper: GET /v2/account -> print equity/cash/buying_power.
2. FMP: GET recent senate trades -> print 5 rows.
3. Obsidian vault: write a dated summary markdown.

Exit code is 0 only if all three legs pass.

Run with::

    uv run python scripts/smoke_test.py
"""
from __future__ import annotations

import sys
import textwrap
from datetime import date, datetime, timezone

import httpx
from alpaca.trading.client import TradingClient

from jay_trading.config import get_settings
from jay_trading.vault.writer import write_vault_file

# Centralized FMP endpoint paths, kept here until Phase 1 pulls them into the
# real FMP client module. Paths drift between v3/v4/stable -- fail loudly if
# the chosen one 404s.
FMP_SENATE_TRADES_URLS: tuple[str, ...] = (
    "https://financialmodelingprep.com/stable/senate-latest",
    "https://financialmodelingprep.com/stable/senate-trades?limit=5",
    "https://financialmodelingprep.com/api/v4/senate-trading?limit=5",
)


def _check(label: str, ok: bool, detail: str = "") -> str:
    mark = "PASS" if ok else "FAIL"
    line = f"[{mark}] {label}"
    return line + (f" -- {detail}" if detail else "")


def _alpaca_leg() -> tuple[bool, str, dict[str, float | str | bool]]:
    s = get_settings()
    client = TradingClient(
        api_key=s.alpaca_api_key,
        secret_key=s.alpaca_secret_key,
        paper=True,
    )
    acct = client.get_account()
    equity = float(acct.equity)
    cash = float(acct.cash)
    buying_power = float(acct.buying_power)
    detail = (
        f"equity=${equity:,.2f} cash=${cash:,.2f} "
        f"buying_power=${buying_power:,.2f}"
    )
    # Paper sanity: the plan specifies ~$10k starting equity. Warn (not fail)
    # if we see something very different so a misconfigured (live!) account
    # doesn't pass silently.
    within_tolerance = abs(equity - 10_000) <= 100
    payload: dict[str, float | str | bool] = {
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
        "status": str(acct.status),
        "account_number": str(acct.account_number),
        "paper_expected_10k": within_tolerance,
    }
    return True, detail, payload


def _fmp_leg() -> tuple[bool, str, list[dict]]:
    s = get_settings()
    headers = {"User-Agent": "jay-trading-smoke/0.1"}
    params = {"apikey": s.fmp_api_key}
    tried: list[str] = []
    last_error = ""
    with httpx.Client(timeout=15.0, headers=headers) as h:
        for url in FMP_SENATE_TRADES_URLS:
            tried.append(url)
            try:
                r = h.get(url, params=params)
            except httpx.HTTPError as e:
                last_error = f"{url}: transport error {e!r}"
                continue
            if r.status_code == 200:
                data = r.json() if r.text else []
                if isinstance(data, dict) and "Error Message" in data:
                    last_error = f"{url}: {data['Error Message']}"
                    continue
                if not isinstance(data, list):
                    last_error = f"{url}: unexpected body shape {type(data).__name__}"
                    continue
                rows = data[:5]
                detail = f"{len(rows)} senate rows from {url.split('?')[0]}"
                return True, detail, rows
            last_error = f"{url}: HTTP {r.status_code} {r.text[:150]!r}"
    return False, f"all FMP endpoints failed; tried {len(tried)}; last={last_error}", []


def _vault_leg(alpaca: dict, fmp_rows: list[dict], alpaca_ok: bool, fmp_ok: bool) -> tuple[bool, str]:
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    fmp_preview = "\n".join(
        f"- {(r.get('firstName','')+' '+r.get('lastName','')).strip() or r.get('representative') or '?'}"
        f" -> {r.get('symbol','?')} ({r.get('type','?')}) on {r.get('transactionDate','?')}"
        for r in fmp_rows
    ) or "_(no rows returned)_"
    body = textwrap.dedent(
        f"""\
        ---
        type: briefing
        subtype: smoke-test
        date: {today}
        generated_at: {now}
        ---
        # Phase 0 smoke test -- {today}

        ## Alpaca paper account
        - Status: {'OK' if alpaca_ok else 'FAIL'}
        - Equity: ${alpaca.get('equity','?')}
        - Cash: ${alpaca.get('cash','?')}
        - Buying power: ${alpaca.get('buying_power','?')}
        - Account #: {alpaca.get('account_number','?')}
        - Expected ~$10k: {alpaca.get('paper_expected_10k','?')}

        ## FMP senate-trades sample
        - Status: {'OK' if fmp_ok else 'FAIL'}

        {fmp_preview}

        ## Vault write
        - Status: OK (this file exists)
        """
    )
    path = write_vault_file(f"briefings/smoke_test_{today}.md", body)
    return True, f"wrote {path}"


def run() -> int:
    """Run the smoke test. Returns a shell-style exit code."""
    results: list[str] = []
    alpaca_ok, alpaca_detail, alpaca_payload = False, "", {}
    fmp_ok, fmp_detail, fmp_rows = False, "", []

    try:
        alpaca_ok, alpaca_detail, alpaca_payload = _alpaca_leg()
    except Exception as e:  # noqa: BLE001 — surface any failure, do not swallow
        alpaca_detail = f"exception: {e!r}"
    results.append(_check("Alpaca paper /v2/account", alpaca_ok, alpaca_detail))

    try:
        fmp_ok, fmp_detail, fmp_rows = _fmp_leg()
    except Exception as e:  # noqa: BLE001
        fmp_detail = f"exception: {e!r}"
    results.append(_check("FMP senate-trades", fmp_ok, fmp_detail))

    vault_ok, vault_detail = False, ""
    try:
        vault_ok, vault_detail = _vault_leg(
            alpaca_payload, fmp_rows, alpaca_ok, fmp_ok
        )
    except Exception as e:  # noqa: BLE001
        vault_detail = f"exception: {e!r}"
    results.append(_check("Obsidian vault write", vault_ok, vault_detail))

    print("\n".join(results))
    all_ok = alpaca_ok and fmp_ok and vault_ok
    print("\nOVERALL:", "PASS" if all_ok else "FAIL")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(run())
