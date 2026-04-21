# Deployment

Paper trading, Windows host, scheduler runs in WSL2.

## One-time setup

1. Make the shell scripts executable (from WSL):
   ```bash
   chmod +x /mnt/k/trading/deploy/start_scheduler.sh /mnt/k/trading/deploy/watchdog.sh
   ```

2. Register the Windows Task Scheduler tasks (from an **elevated** PowerShell):
   ```powershell
   cd K:\trading
   powershell -ExecutionPolicy Bypass -File .\deploy\install_windows_tasks.ps1
   ```

This creates two tasks:

- **JayTrading-Launcher** — fires once at logon; launches the APScheduler
  process in WSL.
- **JayTrading-Watchdog** — fires every 5 minutes, Mon-Fri 08:00–17:00 local.
  If `data/scheduler.pid` is missing or dead, the scheduler is respawned.

## Manual controls

```bash
# Start right now (without logging out):
wsl.exe -- bash -lc 'cd /mnt/k/trading && bash deploy/start_scheduler.sh &'

# Stop:
wsl.exe -- bash -lc 'kill "$(cat /mnt/k/trading/data/scheduler.pid)"'

# Check health:
wsl.exe -- bash -lc 'cat /mnt/k/trading/data/heartbeat.txt; ps -p "$(cat /mnt/k/trading/data/scheduler.pid)"'

# Run a single job manually (any of: ingest signals execute stops reconcile eod):
wsl.exe -- bash -lc 'cd /mnt/k/trading && uv run python -m jay_trading.schedule.jobs execute'

# Tail logs:
wsl.exe -- bash -lc 'tail -f /mnt/k/trading/logs/scheduler.log'
```

## Uninstall

```powershell
cd K:\trading
powershell -ExecutionPolicy Bypass -File .\deploy\install_windows_tasks.ps1 -Uninstall
```

## Kill-switch

To halt all trading without tearing down the scheduler, edit
`src/jay_trading/schedule/jobs.py` and set `STRATEGIES = []`. The scheduler
will keep running ingest/signal generation; it just won't submit orders.
Alternatively, set `SmartCopyStrategy.enabled = False`.

## Job schedule (America/New_York)

| Time | Days | Job | What |
|---|---|---|---|
| 08:30 | Mon–Fri | `ingest_disclosures` | Pull FMP, upsert, write data briefing |
| 08:40 | Mon–Fri | `generate_signals` | Cluster detection → Signal rows |
| 09:35 | Mon–Fri | `execute_strategies` | Convert signals → orders (5 min after open) |
| 10:00–15:45 every 15 min | Mon–Fri | `manage_stops` | Hard stop, trail stop, signal reversal |
| 15:55 | Mon–Fri | `reconcile_now` | Pull Alpaca fills & positions into our DB |
| 16:10 | Mon–Fri | `write_eod_summary` | Daily markdown summary |
| every 5 min | daily | `_heartbeat` | Update `data/heartbeat.txt` |
