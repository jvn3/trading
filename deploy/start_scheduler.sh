#!/usr/bin/env bash
# Start the APScheduler service inside WSL. Idempotent -- the service's own
# PID check exits cleanly if an instance is already running.
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
LOG_DIR="./logs"
mkdir -p "$LOG_DIR"
exec uv run python -m jay_trading.schedule.service >> "$LOG_DIR/scheduler.log" 2>&1
