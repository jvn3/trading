#!/usr/bin/env bash
# Watchdog: restart the scheduler if the PID file shows it dead or missing.
# Invoked by Windows Task Scheduler every 5 minutes.
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

PIDFILE="./data/scheduler.pid"
LOG_DIR="./logs"
mkdir -p "$LOG_DIR"

is_alive() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

if is_alive; then
    echo "$(date -Iseconds) scheduler alive (pid=$(cat $PIDFILE))" >> "$LOG_DIR/watchdog.log"
    exit 0
fi

echo "$(date -Iseconds) scheduler DEAD or missing -- starting" >> "$LOG_DIR/watchdog.log"
# Clean stale pid, then relaunch detached.
rm -f "$PIDFILE"
nohup bash ./deploy/start_scheduler.sh >/dev/null 2>&1 &
disown || true
sleep 2
if is_alive; then
    echo "$(date -Iseconds) watchdog restarted scheduler OK (pid=$(cat $PIDFILE))" >> "$LOG_DIR/watchdog.log"
else
    echo "$(date -Iseconds) watchdog FAILED to restart scheduler" >> "$LOG_DIR/watchdog.log"
fi
