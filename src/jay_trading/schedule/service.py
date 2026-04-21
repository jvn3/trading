"""Long-running APScheduler service.

Jobs fire in America/New_York time, matching the implementation plan's
schedule table. Uses ``BlockingScheduler`` so the process stays attached to
logs; run under ``deploy/start_scheduler.sh`` or Task Scheduler.

Safety:
- PID lockfile at ``data/scheduler.pid`` prevents two instances stomping each
  other — the Windows Task Scheduler watchdog uses this to decide whether to
  respawn.
- ``coalesce=True, max_instances=1`` per job so a slow ingest doesn't queue
  behind a trader execute at 09:35.
- ``misfire_grace_time=5 min`` so jobs that fire while the host was asleep
  still run on wake.
"""
from __future__ import annotations

import atexit
import logging
import os
import signal as signal_mod
import sys
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from jay_trading.config import get_settings
from jay_trading.schedule import jobs

log = logging.getLogger(__name__)

TZ = "America/New_York"


def _pid_path() -> Path:
    p = Path(get_settings().data_dir) / "scheduler.pid"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _heartbeat_path() -> Path:
    return Path(get_settings().data_dir) / "heartbeat.txt"


def _is_running() -> int | None:
    p = _pid_path()
    if not p.exists():
        return None
    try:
        pid = int(p.read_text().strip())
    except ValueError:
        return None
    # Probe the PID.
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def _write_pid() -> None:
    _pid_path().write_text(str(os.getpid()))


def _clear_pid() -> None:
    try:
        _pid_path().unlink()
    except OSError:
        pass


def _heartbeat() -> None:
    from datetime import datetime, timezone

    try:
        _heartbeat_path().write_text(datetime.now(timezone.utc).isoformat())
    except OSError as e:
        log.warning("heartbeat write failed: %s", e)


def _wrapped(fn: Callable[[], dict]) -> Callable[[], None]:
    """Run a job, log outcome, never propagate — we must never kill the scheduler."""

    def runner() -> None:
        _heartbeat()
        try:
            result = fn()
            log.info("job %s ok: %s", fn.__name__, result)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed: %s", fn.__name__, e)
        finally:
            _heartbeat()

    runner.__name__ = f"run_{fn.__name__}"
    return runner


def build_scheduler() -> BlockingScheduler:
    sched = BlockingScheduler(
        timezone=TZ,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
    )

    # Morning: ingest → generate signals → (markets open at 09:30 ET) → execute
    sched.add_job(_wrapped(jobs.ingest_disclosures), CronTrigger(hour=8, minute=30, day_of_week="mon-fri"))
    sched.add_job(_wrapped(jobs.generate_signals), CronTrigger(hour=8, minute=40, day_of_week="mon-fri"))
    sched.add_job(_wrapped(jobs.execute_strategies), CronTrigger(hour=9, minute=35, day_of_week="mon-fri"))

    # Intraday stop management
    sched.add_job(_wrapped(jobs.manage_stops), CronTrigger(hour="10-15", minute="*/15", day_of_week="mon-fri"))

    # Reconcile + EOD summary
    sched.add_job(_wrapped(jobs.reconcile_now), CronTrigger(hour=15, minute=55, day_of_week="mon-fri"))
    sched.add_job(_wrapped(jobs.write_eod_summary), CronTrigger(hour=16, minute=10, day_of_week="mon-fri"))

    # Heartbeat every 5 min so the watchdog can detect a stuck process.
    sched.add_job(_heartbeat, CronTrigger(minute="*/5"))

    return sched


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, get_settings().log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    existing = _is_running()
    if existing:
        log.error("another scheduler is already running (pid=%s). exiting.", existing)
        return 1
    _write_pid()
    atexit.register(_clear_pid)

    sched = build_scheduler()

    def _shutdown(signum: int, _frame: object) -> None:
        log.info("received signal %d, shutting scheduler down gracefully", signum)
        sched.shutdown(wait=False)

    for sig in (signal_mod.SIGINT, signal_mod.SIGTERM):
        try:
            signal_mod.signal(sig, _shutdown)
        except (AttributeError, ValueError):
            pass  # Some environments restrict signal handling

    log.info("scheduler starting (pid=%d tz=%s)", os.getpid(), TZ)
    _heartbeat()
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        pass
    log.info("scheduler stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
