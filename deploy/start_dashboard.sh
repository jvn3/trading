#!/usr/bin/env bash
# Start the read-only operator dashboard on http://127.0.0.1:8787.
# Idempotent via a PID file in data/dashboard.pid.
# Uses setsid+nohup so the process survives the invoking bash session exit.
set -e
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

HOST="${JAY_DASH_HOST:-127.0.0.1}"
PORT="${JAY_DASH_PORT:-8787}"
PIDFILE="./data/dashboard.pid"
LOG_DIR="./logs"
mkdir -p "$LOG_DIR" "$(dirname "$PIDFILE")"

if [ -f "$PIDFILE" ]; then
    pid=$(cat "$PIDFILE" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "dashboard already running (pid=$pid) at http://$HOST:$PORT"
        exit 0
    fi
    rm -f "$PIDFILE"
fi

echo "starting dashboard on http://$HOST:$PORT"

# setsid gives the process its own session so SIGHUP from the parent shell
# doesn't reach it. nohup explicitly ignores SIGHUP as a belt.
setsid nohup uv run uvicorn jay_trading.dashboard.app:app \
    --host "$HOST" --port "$PORT" \
    --log-level warning \
    < /dev/null >> "$LOG_DIR/dashboard.log" 2>&1 &
pid=$!
echo "$pid" > "$PIDFILE"
disown 2>/dev/null || true

# Poll up to 10s for the port to come up.
for i in 1 2 3 4 5 6 7 8 9 10; do
    if kill -0 "$pid" 2>/dev/null; then
        if (command -v ss >/dev/null 2>&1 && ss -lnt 2>/dev/null | grep -q ":$PORT ") \
           || (command -v netstat >/dev/null 2>&1 && netstat -lnt 2>/dev/null | grep -q ":$PORT "); then
            echo "dashboard up (pid=$pid) at http://$HOST:$PORT"
            exit 0
        fi
    else
        echo "dashboard DIED early -- see $LOG_DIR/dashboard.log"
        exit 1
    fi
    sleep 1
done

if kill -0 "$pid" 2>/dev/null; then
    echo "dashboard running (pid=$pid) but port $PORT not listening after 10s -- check log"
    exit 0
fi
echo "dashboard FAILED to start -- see $LOG_DIR/dashboard.log"
exit 1
