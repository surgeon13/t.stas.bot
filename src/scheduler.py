"""Scheduled execution loop — runs the fetch+ingest pipeline daily."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from collections.abc import Callable
from queue import Empty, Queue
from typing import Final

import schedule

from . import sched_terminal

log = logging.getLogger(__name__)

TAG_ADHOC: Final = "adhoc_schedule"
TAG_CONFIG_DAILY: Final = "config_daily"

_FETCH_LOCK = threading.Lock()

_DAILY_RE = re.compile(r"^daily@(\d{1,2}):(\d{2})$", re.IGNORECASE)
_RE_EVERY_INTERVAL = re.compile(
    r"^every\s*(\d+)\s*(minute|minutes|mins|min|m|hours|hour|hrs|hr|h)\s*$",
    re.IGNORECASE,
)
_RE_STDIN_DAILY = re.compile(r"^daily\s+(?:at\s+)?(\d{1,2}):(\d{2})\s*$", re.IGNORECASE)


def _parse_schedule(spec: str) -> tuple[str, str]:
    """Return ('daily', 'HH:MM') or raise ValueError."""
    m = _DAILY_RE.match(spec.strip())
    if not m:
        raise ValueError(
            f"Unsupported schedule spec '{spec}'. Use 'daily@HH:MM' (e.g. 'daily@00:01')."
        )
    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time in schedule '{spec}'")
    return "daily", f"{hour:02d}:{minute:02d}"


def _unit_is_hours(token: str) -> bool:
    t = token.lower()
    return t in ("h", "hr", "hrs", "hour", "hours")


def _stdin_print_help() -> None:
    sched_terminal.print_adhoc_schedule_message(
        "Commands: fetch | now  ·  every N m|min  ·  every N h|hours  ·  "
        "daily HH:MM  ·  list  ·  clear  ·  help"
    )


def _stdin_jobs_summary() -> str:
    rows = schedule.get_jobs()
    if not rows:
        return "(no scheduled jobs)"
    return "\n".join(f"  {j}" for j in rows)


def _stdin_handle(line: str, *, guarded_fetch: Callable[[], None]) -> None:
    raw = line.strip()
    if not raw:
        return

    norm = raw.lower()
    tokens = tuple(norm.split())

    if norm in ("help", "?"):
        _stdin_print_help()
        return
    if tokens[0] in ("fetch", "now"):
        log.info("stdin: immediate fetch")
        guarded_fetch()
        return
    if tokens and tokens[0] in ("jobs", "list", "ls"):
        sched_terminal.print_adhoc_schedule_message(_stdin_jobs_summary())
        return
    if norm in ("clear", "clear-adhoc"):
        tagged = schedule.get_jobs(TAG_ADHOC)
        schedule.clear(TAG_ADHOC)
        sched_terminal.print_adhoc_schedule_message(f"Cleared {len(tagged)} ad hoc job(s).")
        log.info("stdin: cleared %s ad hoc job(s)", len(tagged))
        return

    dm = _RE_STDIN_DAILY.match(norm)
    if dm:
        h, mn = int(dm.group(1)), int(dm.group(2))
        if not (0 <= h <= 23 and 0 <= mn <= 59):
            sched_terminal.print_adhoc_schedule_message("Invalid clock time (hour 0–23, mm 00–59).")
            return
        at_mm = f"{h:02d}:{mn:02d}"

        def _daily_extra() -> None:
            guarded_fetch()

        schedule.every().day.at(at_mm).do(_daily_extra).tag(TAG_ADHOC)
        sched_terminal.print_adhoc_schedule_message(f"Registered extra daily fetch at {at_mm} local time.")
        log.info("stdin: extra daily at %s", at_mm)
        return

    em = _RE_EVERY_INTERVAL.match(norm)
    if em:
        n = int(em.group(1))
        if n < 1:
            sched_terminal.print_adhoc_schedule_message("Interval must be at least 1.")
            return
        token = em.group(2)
        hours = _unit_is_hours(token)

        def _interval_ping() -> None:
            guarded_fetch()

        if hours:
            if n > 24 * 56:
                sched_terminal.print_adhoc_schedule_message("Interval too large; pick a smaller hour repeat.")
                return
            schedule.every(n).hours.do(_interval_ping).tag(TAG_ADHOC)
            human = f"every {n} hour(s)"
        else:
            if n > 7 * 24 * 60:
                sched_terminal.print_adhoc_schedule_message("Interval too large.")
                return
            schedule.every(n).minutes.do(_interval_ping).tag(TAG_ADHOC)
            human = f"every {n} minute(s)"

        sched_terminal.print_adhoc_schedule_message(f"Registered ad hoc fetch: {human}.")
        log.info("stdin: interval %s", human)
        return

    sched_terminal.print_adhoc_schedule_message(
        f"Unknown command: {raw!r}. Type help for a summary."
    )


def run_loop(
    spec: str,
    job: Callable[[], None],
    *,
    stdin_commands: bool | None = None,
) -> None:
    """Block forever, running `job` according to `spec` (``daily@HH:MM``).

    When ``stdin_commands`` is true (default: ``sys.stdin.isatty()``), stdin is read
    in a background thread; lines are drained on the main thread so registering
    new ``schedule`` jobs stays thread-safe. Ad hoc registrations use tag
    ``TAG_ADHOC`` — ``clear`` removes only those, not the YAML daily job.
    """
    if stdin_commands is None:
        stdin_commands = sys.stdin.isatty()

    def guarded_fetch() -> None:
        with _FETCH_LOCK:
            job()

    kind, at = _parse_schedule(spec)
    if kind == "daily":

        def _config_pass() -> None:
            try:
                guarded_fetch()
            finally:
                sched_terminal.print_next_automated_fetch(schedule.next_run())

        schedule.every().day.at(at).do(_config_pass).tag(TAG_CONFIG_DAILY)
    else:
        raise ValueError(f"Unhandled schedule kind: {kind}")

    cmd_q: Queue[str] | None = Queue() if stdin_commands else None

    if stdin_commands and cmd_q is not None:

        def _stdin_reader() -> None:
            try:
                for raw in iter(sys.stdin.readline, ""):
                    cmd_q.put(raw)
            except Exception:
                log.exception("stdin reader stopped")

        threading.Thread(
            target=_stdin_reader,
            name="t-stats-sched-stdin",
            daemon=True,
        ).start()

    log.info("Scheduler started; next run target = %s (%s).", at, spec)
    sched_terminal.print_daily_schedule_banner(spec=spec, hh_mm=at)
    if stdin_commands:
        sched_terminal.print_stdin_schedule_hint()

    # Optional: also run once at startup so users see immediate output the first
    # time. Kept opt-out via env var if needed; here we just always run once.
    try:
        log.info("Running initial job at startup ...")
        _config_pass()
    except Exception:
        log.exception("Initial job failed; continuing to scheduled runs.")

    sleep_interval = 1.0 if stdin_commands else 30.0

    while True:
        if cmd_q is not None:
            try:
                while True:
                    _stdin_handle(cmd_q.get_nowait(), guarded_fetch=guarded_fetch)
            except Empty:
                pass
        schedule.run_pending()
        time.sleep(sleep_interval)
