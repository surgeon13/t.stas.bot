"""Colored terminal banners for scheduled fetches (Rich: purple schedule, green new data)."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.text import Text

_console = Console(highlight=False)

# Strong “purple” read in most terminals
_STYLE_TIME = "bold bright_magenta"
_STYLE_FRESH_OK = "bold bright_green"


def print_daily_schedule_banner(*, spec: str, hh_mm: str) -> None:
    line = Text()
    line.append("● ", style=_STYLE_TIME)
    line.append("Scheduled map fetch  ", style="dim")
    line.append(spec, style=_STYLE_TIME)
    line.append("  → fires daily at ", style="dim")
    line.append(hh_mm, style=_STYLE_TIME)
    line.append("  (this machine’s local clock)", style="dim")
    _console.print(line)


def print_next_automated_fetch(next_run: datetime | None) -> None:
    if next_run is None:
        return
    line = Text()
    line.append("● ", style=_STYLE_TIME)
    line.append("Next automated fetch  ", style="dim")
    line.append(next_run.strftime("%Y-%m-%d %H:%M:%S"), style=_STYLE_TIME)
    _console.print(line)


def print_stdin_schedule_hint() -> None:
    """One-line notice that stdin can add/adjust ad hoc scheduled fetches."""
    line = Text()
    line.append("● ", style=_STYLE_TIME)
    line.append("Stdin: ", style="dim")
    line.append("fetch", style=_STYLE_TIME)
    line.append(" · ", style="dim")
    line.append("every N m|h", style=_STYLE_TIME)
    line.append(" · ", style="dim")
    line.append("daily HH:MM", style=_STYLE_TIME)
    line.append(" · ", style="dim")
    line.append("list", style=_STYLE_TIME)
    line.append(" · ", style="dim")
    line.append("clear", style=_STYLE_TIME)
    line.append(" · ", style="dim")
    line.append("help", style=_STYLE_TIME)
    _console.print(line)


def print_adhoc_schedule_message(msg: str) -> None:
    line = Text()
    line.append("● ", style=_STYLE_TIME)
    line.append(msg, style="dim")
    _console.print(line)


def print_new_snapshot_success(
    *,
    server_key: str,
    snapshot_id: int,
    village_rows: int,
    byte_size: int,
    when_iso: str,
) -> None:
    """Bold green banner when newly ingested snapshot rows landed (not a sha256 dup)."""
    try:
        when = datetime.fromisoformat(str(when_iso).replace("Z", "+00:00"))
        ts = when.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        ts = str(when_iso)
    line = Text()
    line.append("✓ ", style=_STYLE_FRESH_OK)
    line.append(f"[{server_key}] ", style="bold green")
    line.append("new map snapshot stored ", style=_STYLE_FRESH_OK)
    line.append(
        f"— id={snapshot_id} · {village_rows:,} villages · {byte_size:,} bytes · {ts}",
        style="dim",
    )
    _console.print(line)
