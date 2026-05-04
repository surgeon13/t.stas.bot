"""Start the daily fetch loop in a daemon thread (e.g. alongside Streamlit)."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from .config import load_config
from . import scheduler
from .fetch_ingest import fetch_all_enabled_servers

log = logging.getLogger(__name__)

_lock = threading.Lock()
_started = False


def embedded_scheduler_enabled() -> bool:
    """Embedded daily fetch defaults **on** for Streamlit; set env to ``0``/``false`` to disable."""
    v = os.environ.get("T_STATS_EMBED_SCHEDULER", "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _embed_sched_stdin_commands() -> bool:
    """Opt-in stdin ad hoc schedules while Streamlit owns the terminal."""
    raw = os.environ.get("T_STATS_EMBED_SCHED_STDIN", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def start_embedded_fetch_scheduler(
    *, config_path: str | Path, db_path: Path
) -> bool:
    """Unless ``T_STATS_EMBED_SCHEDULER`` is explicitly **disabled** (`0`/``false``),
    starts one background thread that runs ``scheduler.run_loop`` (same timing as
    ``python main.py run``). Embedded fetch is **enabled by default**.

    Optional: set ``T_STATS_EMBED_SCHED_STDIN=1`` to enable the same stdin ad hoc
    schedule commands while the dashboard process owns the terminal (the reader
    thread shares stdin with Streamlit).

    Safe to call on every Streamlit rerun: only the first call starts the thread.
    Returns whether the scheduler was started (including “already running”).
    """
    global _started
    if not embedded_scheduler_enabled():
        return False

    cfg_path = Path(config_path)

    with _lock:
        if _started:
            return True
        _started = True

    cfg = load_config(cfg_path)

    def job() -> None:
        fetch_all_enabled_servers(cfg, db_path)

    def runner() -> None:
        log.warning(
            "Embedded fetch scheduler active (%s → %s). "
            "Do not run `python main.py run` separately or you will duplicate fetches.",
            cfg.settings.schedule,
            db_path.resolve(),
        )
        try:
            scheduler.run_loop(
                cfg.settings.schedule,
                job,
                stdin_commands=_embed_sched_stdin_commands(),
            )
        except Exception:
            log.exception("Embedded scheduler exited with error")

    t = threading.Thread(
        target=runner,
        name="t-stats-fetch-scheduler",
        daemon=True,
    )
    t.start()
    return True
