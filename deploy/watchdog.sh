#!/usr/bin/env bash
# Watchdog: restart the scheduler if it is dead, missing, OR hung.
# Invoked by Windows Task Scheduler every 5 minutes.
#
# "Hung" = PID alive but data/heartbeat.txt older than $MAX_HEARTBEAT_AGE_S.
# The in-process heartbeat job writes every 5 min, so 15 min of silence means
# the APScheduler event loop is wedged — kill and respawn. (The 2026-05-13 →
# 07-05 outage happened because the old watchdog was never installed and only
# probed the PID; see development/audit-2026-07-05.md.)
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

PIDFILE="./data/scheduler.pid"
HEARTBEAT="./data/heartbeat.txt"
LOG_DIR="./logs"
MAX_HEARTBEAT_AGE_S=900
mkdir -p "$LOG_DIR"

wlog() {
    echo "$(date -Iseconds) $1" >> "$LOG_DIR/watchdog.log"
}

pid_alive() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

heartbeat_age() {
    # Seconds since the last heartbeat write; huge number if file missing.
    if [ ! -f "$HEARTBEAT" ]; then
        echo 999999
        return
    fi
    hb_epoch=$(date -d "$(cat "$HEARTBEAT")" +%s 2>/dev/null || echo 0)
    if [ "$hb_epoch" -eq 0 ]; then
        echo 999999
        return
    fi
    echo $(( $(date +%s) - hb_epoch ))
}

restart() {
    rm -f "$PIDFILE"
    nohup bash ./deploy/start_scheduler.sh >/dev/null 2>&1 &
    disown || true
    # uv run can take ~20s to boot the venv; poll instead of a fixed sleep.
    for _ in $(seq 1 12); do
        sleep 5
        if pid_alive; then
            wlog "watchdog restarted scheduler OK (pid=$(cat $PIDFILE))"
            return
        fi
    done
    wlog "watchdog FAILED to restart scheduler (no live pid after 60s)"
}

if pid_alive; then
    age=$(heartbeat_age)
    if [ "$age" -gt "$MAX_HEARTBEAT_AGE_S" ]; then
        pid=$(cat "$PIDFILE")
        wlog "scheduler HUNG (pid=$pid, heartbeat ${age}s old) -- killing and restarting"
        kill "$pid" 2>/dev/null || true
        sleep 2
        kill -9 "$pid" 2>/dev/null || true
        restart
    fi
    # Healthy: stay quiet (no log spam every 5 min).
    exit 0
fi

wlog "scheduler DEAD or missing -- starting"
restart
