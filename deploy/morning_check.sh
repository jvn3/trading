#!/usr/bin/env bash
# Run the unattended morning verification. Invoked by the Windows Task
# Scheduler task JayTrading-MorningCheck (weekdays 10:15 ET). Read-only
# against the paper account; writes a dated report to the vault.
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
mkdir -p logs
exec uv run python scripts/morning_check.py >> logs/morning_check.log 2>&1
