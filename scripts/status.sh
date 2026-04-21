#!/usr/bin/env bash
# One-shot scheduler health + Alpaca status. Safe to invoke from PowerShell:
#   wsl.exe -- bash -lc 'bash /mnt/k/trading/scripts/status.sh'
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

PIDFILE="./data/scheduler.pid"
HEARTBEAT="./data/heartbeat.txt"

echo "=== Scheduler ==="
if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "  alive (pid=$pid)"
    else
        echo "  DEAD (stale pid=$pid in $PIDFILE)"
    fi
else
    echo "  NOT RUNNING (no pid file)"
fi

echo
echo "=== Heartbeat ==="
if [ -f "$HEARTBEAT" ]; then
    beat=$(cat "$HEARTBEAT")
    now=$(date -u -Iseconds)
    echo "  last:  $beat"
    echo "  now:   $now"
else
    echo "  (no heartbeat file)"
fi

echo
echo "=== Recent log lines ==="
if [ -f "logs/scheduler.log" ]; then
    tail -8 logs/scheduler.log
else
    echo "  (no log yet)"
fi

echo
echo "=== Alpaca ==="
uv run python scripts/status.py
