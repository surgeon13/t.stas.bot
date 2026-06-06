"""Rich-based pretty rendering for the CLI output."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analyzer import (
    AllianceHistory,
    AllianceMove,
    AllianceRankRow,
    InactiveNearRow,
    PlayerHistory,
    PlayerRankRow,
    PlayerVillageAcquisition,
    PlayerVillageLoss,
    SnapshotDelta,
    SnapshotStats,
    TRIBE_NAMES,
    VillageEvent,
    VillageHistory,
    VillageMover,
    VillageRankRow,
)  # noqa: F401  (re-export)

console = Console(highlight=False)


# ---------- helpers ----------------------------------------------------------

_TRIBE_STYLES = {
    "Romans":    "bold red",
    "Teutons":   "bold yellow",
    "Gauls":     "bold green",
    "Egyptians": "bold cyan",
    "Huns":      "bold magenta",
    "Spartans":  "bold blue",
    "Vikings":   "bold blue",
    "Natars":    "bold white",
    "Nature":    "dim",
}


def _fmt_int(n: int | float | None) -> str:
    if n is None:
        return "-"
    return f"{int(n):,}"


def _fmt_signed(n: int | float | None) -> Text:
    if n is None:
        return Text("-")
    val = int(n)
    if val > 0:
        return Text(f"+{val:,}", style="bold green")
    if val < 0:
        return Text(f"{val:,}", style="bold red")
    return Text("0", style="dim")


def _fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def _fmt_size(num_bytes: int) -> str:
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{num_bytes} B"


# ---------- views ------------------------------------------------------------

def render_servers(servers: Sequence[Any], schedule: str) -> None:
    table = Table(
        title=f"Configured servers  -  schedule: {schedule}",
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("key", style="bold", no_wrap=True)
    table.add_column("name")
    table.add_column("base url", style="blue", no_wrap=True)
    table.add_column("enabled", justify="center")
    table.add_column("tags", style="magenta")

    for s in servers:
        enabled = Text("on", style="bold green") if s.enabled else Text("off", style="bold red")
        tags = ", ".join(s.tags) if s.tags else "-"
        table.add_row(s.key, s.name, s.base_url, enabled, tags)

    console.print(table)


def render_snapshots(rows: Iterable[Any]) -> None:
    table = Table(
        title="Stored snapshots",
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("id", justify="right", style="bold")
    table.add_column("server")
    table.add_column("fetched at", no_wrap=True)
    table.add_column("villages", justify="right")
    table.add_column("size", justify="right", no_wrap=True)
    table.add_column("sha256", style="dim", no_wrap=True)

    rows = list(rows)
    if not rows:
        console.print("[dim]No snapshots stored yet.[/dim]")
        return

    for r in rows:
        table.add_row(
            str(r["id"]),
            r["server_key"],
            _fmt_dt(r["fetched_at"]),
            _fmt_int(r["row_count"]),
            _fmt_size(int(r["byte_size"])),
            r["sha256"][:12],
        )
    console.print(table)


def render_inactives_near(
    rows: Sequence[InactiveNearRow],
    *,
    server_name: str,
    server_key: str,
    center_x: int,
    center_y: int,
    radius_min: int,
    radius_max: int,
    min_snapshots: int,
) -> None:
    ring = (
        f"radius {radius_max} tiles"
        if radius_min <= 0
        else f"radius {radius_min}–{radius_max} tiles"
    )
    title = (
        f"Inactive candidates near ({center_x:+d}|{center_y:+d}) "
        f"— {ring} · {server_name} ({server_key})"
    )
    subtitle = (
        f"Flat population in all observations (≥{min_snapshots} snapshots). "
        "Euclidean distance; not login-based."
    )
    table = Table(
        title=title,
        caption=subtitle,
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("village", style="bold")
    table.add_column("coords", no_wrap=True)
    table.add_column("dist", justify="right")
    table.add_column("pop", justify="right")
    table.add_column("player")
    table.add_column("alliance", style="magenta")
    table.add_column("tribe", style="cyan")
    table.add_column("snaps", justify="right", style="dim")

    if not rows:
        console.print(Panel("[dim]No matching villages. Widen radius or lower min_snapshots.[/dim]", title=title))
        return

    for i, r in enumerate(rows, start=1):
        table.add_row(
            str(i),
            f"{r.village_name} [{r.village_id}]",
            f"({r.x:+d}|{r.y:+d})",
            f"{r.distance_tiles:.1f}",
            _fmt_int(r.population),
            r.player_name or "-",
            r.alliance_name or "-",
            r.tribe_name,
            str(r.snapshots_seen),
        )
    console.print(table)


def _render_summary(stats: SnapshotStats) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold")
    t.add_column()
    t.add_row("Snapshot",        f"#{stats.snapshot_id}")
    t.add_row("Server",          stats.server_key)
    t.add_row("Fetched at",      _fmt_dt(stats.fetched_at))
    t.add_row("Villages",        _fmt_int(stats.villages))
    t.add_row("Active players",  _fmt_int(stats.players))
    t.add_row("Alliances",       _fmt_int(stats.alliances))
    t.add_row("Total population", _fmt_int(stats.total_population))
    t.add_row("Avg pop/village", f"{stats.avg_population:,.1f}")
    return t


def _render_tribe_table(stats: SnapshotStats) -> Table:
    table = Table(title="Tribe distribution", header_style="bold cyan")
    table.add_column("tribe", style="bold")
    table.add_column("villages", justify="right")
    table.add_column("share",    justify="right")

    total = stats.villages or 1
    for tribe, n in stats.tribe_counts.items():
        style = _TRIBE_STYLES.get(tribe, "")
        share = n / total * 100
        table.add_row(
            Text(tribe, style=style),
            _fmt_int(n),
            f"{share:5.1f}%",
        )
    return table


def _render_top_players(stats: SnapshotStats) -> Table:
    table = Table(
        title=f"Top {len(stats.top_players)} players by population",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("player", style="bold")
    table.add_column("alliance", style="magenta")
    table.add_column("villages", justify="right")
    table.add_column("population", justify="right", style="green")

    for i, p in enumerate(stats.top_players, 1):
        table.add_row(
            str(i),
            p["player_name"] or "-",
            p["alliance_name"] or "-",
            _fmt_int(p["villages"]),
            _fmt_int(p["population"]),
        )
    return table


def _render_top_alliances(stats: SnapshotStats) -> Table:
    table = Table(
        title=f"Top {len(stats.top_alliances)} alliances by population",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("alliance", style="bold magenta")
    table.add_column("members",    justify="right")
    table.add_column("villages",   justify="right")
    table.add_column("population", justify="right", style="green")

    for i, a in enumerate(stats.top_alliances, 1):
        table.add_row(
            str(i),
            a["alliance_name"] or "-",
            _fmt_int(a["members"]),
            _fmt_int(a["villages"]),
            _fmt_int(a["population"]),
        )
    return table


def _render_delta(delta: SnapshotDelta) -> Table:
    table = Table(
        title=f"Change vs snapshot #{delta.from_id}",
        header_style="bold cyan",
        show_header=True,
    )
    table.add_column("metric", style="bold")
    table.add_column("change", justify="right")

    table.add_row("New villages",      _fmt_signed(delta.new_villages))
    table.add_row("Removed villages",  _fmt_signed(-delta.removed_villages))
    table.add_row("Population change", _fmt_signed(delta.population_change))
    table.add_row("New players",       _fmt_signed(delta.new_players))
    table.add_row("Lost players",      _fmt_signed(-delta.lost_players))
    return table


def render_report(stats: SnapshotStats, delta: SnapshotDelta | None) -> None:
    summary = Panel(
        _render_summary(stats),
        title=f"[bold]Snapshot #{stats.snapshot_id}  |  {stats.server_key}[/bold]",
        border_style="cyan",
    )
    console.print(summary)
    console.print(_render_tribe_table(stats))
    console.print(_render_top_players(stats))
    console.print(_render_top_alliances(stats))
    if delta is not None:
        console.print(_render_delta(delta))


def render_message(msg: str, style: str = "") -> None:
    console.print(Text(msg, style=style))


# ---------- sparkline --------------------------------------------------------

_SPARK_BARS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[int]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return "─"
    lo, hi = min(values), max(values)
    if hi == lo:
        return "─" * len(values)
    span = hi - lo
    return "".join(
        _SPARK_BARS[min(len(_SPARK_BARS) - 1, int((v - lo) / span * (len(_SPARK_BARS) - 1)))]
        for v in values
    )


# ---------- rankings ---------------------------------------------------------

def render_player_ranking(
    rows: list[PlayerRankRow], *, server_key: str, has_delta: bool
) -> None:
    title = f"Player population ranking — {server_key}"
    table = Table(
        title=title,
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("player", style="bold", no_wrap=True)
    table.add_column("tribe", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    table.add_column("villages", justify="right")
    table.add_column("population", justify="right", style="green")
    if has_delta:
        table.add_column("Δ pop", justify="right")
        table.add_column("Δ vil", justify="right")
        table.add_column("note", style="yellow", no_wrap=True)

    if not rows:
        console.print(f"[dim]No data for {server_key} yet.[/dim]")
        return

    for r in rows:
        cells: list[Any] = [
            str(r.rank),
            r.player_name or "-",
            Text(r.tribe_name, style=_TRIBE_STYLES.get(r.tribe_name, "")),
            r.alliance_name or "-",
            _fmt_int(r.villages),
            _fmt_int(r.population),
        ]
        if has_delta:
            cells.extend([
                _fmt_signed(r.pop_delta),
                _fmt_signed(r.villages_delta),
                Text("NEW", style="bold yellow") if r.is_new else Text(""),
            ])
        table.add_row(*cells)

    console.print(table)


def render_alliance_ranking(
    rows: list[AllianceRankRow], *, server_key: str, has_delta: bool
) -> None:
    table = Table(
        title=f"Alliance population ranking — {server_key}",
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("alliance", style="bold magenta", no_wrap=True)
    table.add_column("members", justify="right")
    table.add_column("villages", justify="right")
    table.add_column("population", justify="right", style="green")
    if has_delta:
        table.add_column("Δ pop", justify="right")
        table.add_column("Δ mem", justify="right")
        table.add_column("note", style="yellow", no_wrap=True)

    if not rows:
        console.print(f"[dim]No data for {server_key} yet.[/dim]")
        return

    for r in rows:
        cells: list[Any] = [
            str(r.rank),
            r.alliance_name or "-",
            _fmt_int(r.members),
            _fmt_int(r.villages),
            _fmt_int(r.population),
        ]
        if has_delta:
            cells.extend([
                _fmt_signed(r.pop_delta),
                _fmt_signed(r.members_delta),
                Text("NEW", style="bold yellow") if r.is_new else Text(""),
            ])
        table.add_row(*cells)

    console.print(table)


# ---------- history ----------------------------------------------------------

def render_player_history(history: PlayerHistory, *, server_key: str) -> None:
    pops = [p.population for p in history.points]
    spark = _sparkline(pops)

    title_text = (
        f"Player history — {history.player_name} (id={history.player_id}, "
        f"{history.tribe_name}) on {server_key}"
    )

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Snapshots", str(len(history.points)))
    summary.add_row(
        "Tribe",
        Text(history.tribe_name, style=_TRIBE_STYLES.get(history.tribe_name, "")),
    )
    if history.points:
        first = history.points[0]
        last = history.points[-1]
        summary.add_row("First seen",   _fmt_dt(first.fetched_at))
        summary.add_row("Latest",       _fmt_dt(last.fetched_at))
        summary.add_row("Latest pop",   _fmt_int(last.population))
        summary.add_row("Latest villages", _fmt_int(last.villages))
        summary.add_row("Current alliance", last.alliance_name or "-")
        summary.add_row("Population trend", Text(spark, style="bold cyan"))
        if len(history.points) >= 2:
            change = last.population - first.population
            summary.add_row("Total change", _fmt_signed(change))

    console.print(Panel(summary, title=title_text, border_style="cyan"))

    table = Table(header_style="bold cyan", row_styles=["", "dim"])
    table.add_column("snap", justify="right", style="dim")
    table.add_column("fetched at", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    table.add_column("villages", justify="right")
    table.add_column("population", justify="right", style="green")
    table.add_column("Δ pop", justify="right")
    table.add_column("Δ vil", justify="right")

    prev_pop: int | None = None
    prev_vil: int | None = None
    for p in history.points:
        d_pop = None if prev_pop is None else p.population - prev_pop
        d_vil = None if prev_vil is None else p.villages - prev_vil
        table.add_row(
            str(p.snapshot_id),
            _fmt_dt(p.fetched_at),
            p.alliance_name or "-",
            _fmt_int(p.villages),
            _fmt_int(p.population),
            _fmt_signed(d_pop) if d_pop is not None else Text("-", style="dim"),
            _fmt_signed(d_vil) if d_vil is not None else Text("-", style="dim"),
        )
        prev_pop, prev_vil = p.population, p.villages

    console.print(table)


_STATUS_STYLES: dict[str, str] = {
    "settled":      "bold green",
    "conquered":    "bold red",
    "pre-existing": "dim",
}


def render_player_village_ledger(
    rows: list[PlayerVillageAcquisition],
    *,
    player_name: str,
    server_key: str,
    game_base_url: str | None = None,
) -> None:
    """Per-village ledger: how each currently-owned village was acquired."""
    settled = sum(1 for r in rows if r.status == "settled")
    conquered = sum(1 for r in rows if r.status == "conquered")
    pre = sum(1 for r in rows if r.status == "pre-existing")

    title = (
        f"Village ledger — {player_name} on {server_key}    "
        f"[green]settled[/]: {settled}    "
        f"[red]conquered[/]: {conquered}    "
        f"[dim]pre-existing[/]: {pre}    "
        f"total: {len(rows)}"
    )

    if not rows:
        console.print(f"[dim]No villages held by this player on {server_key}.[/dim]")
        return

    table = Table(
        title=title,
        title_justify="left",
        header_style="bold cyan",
        row_styles=("", "on grey11"),
    )
    table.add_column("village",   style="bold", no_wrap=True)
    table.add_column("coords",    style="cyan", no_wrap=True, justify="right")
    table.add_column("pop",       justify="right", style="green")
    table.add_column("status",    no_wrap=True)
    table.add_column("from",      no_wrap=True)
    table.add_column("alliance",  style="magenta", no_wrap=True)
    table.add_column("at (UTC)",  no_wrap=True)

    for r in rows:
        status_text = Text(r.status, style=_STATUS_STYLES.get(r.status, ""))
        if r.status == "conquered":
            from_text: Any = r.from_player_name or "-"
        elif r.status == "settled":
            from_text = Text("(founded)", style="dim")
        else:
            from_text = Text("(unknown)", style="dim")

    for r in rows:
        status_text = Text(r.status, style=_STATUS_STYLES.get(r.status, ""))
        if r.status == "conquered":
            from_text: Any = r.from_player_name or "-"
        elif r.status == "settled":
            from_text = Text("(founded)", style="dim")
        else:
            from_text = Text("(unknown)", style="dim")

        when = _fmt_dt(r.acquired_at) if r.acquired_at else Text("-", style="dim")
        coords_cell: Text | str
        if game_base_url:
            u = (
                f'{game_base_url.rstrip("/")}/position_details.php?'
                f'x={int(r.x)}&y={int(r.y)}'
            )
            coords_cell = Text(_coords(r.x, r.y), style=f"link {u}")
        else:
            coords_cell = _coords(r.x, r.y)

        table.add_row(
            r.village_name or "-",
            coords_cell,
            _fmt_int(r.population),
            status_text,
            from_text,
            (r.from_alliance_name or "-") if r.status == "conquered" else "-",
            when,
        )

    console.print(table)


def render_player_villages_lost(
    rows: list[PlayerVillageLoss],
    *,
    player_name: str,
    server_key: str,
    game_base_url: str | None = None,
) -> None:
    """Villages the player owned in past snapshots but not in latest (still on map)."""
    print()
    title = (
        f"Villages lost to others — {player_name} on {server_key}    "
        f"[yellow]lost (on map)[/]: {len(rows)}"
    )
    if not rows:
        console.print(f"[dim]{title}\n(No matching tiles.)[/dim]")
        return

    console.print(Text(title, justify="left"))
    table = Table(
        header_style="bold cyan",
        row_styles=("", "on grey11"),
    )
    table.add_column("village", style="bold", no_wrap=True)
    table.add_column("coords", style="cyan", no_wrap=True, justify="right")
    table.add_column("pop", justify="right", style="green")
    table.add_column("now owned by", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    table.add_column("lost (UTC)", no_wrap=True)

    for r in rows:
        if game_base_url:
            u = (
                f'{game_base_url.rstrip("/")}/position_details.php?'
                f'x={int(r.x)}&y={int(r.y)}'
            )
            coords_cell: Any = Text(_coords(r.x, r.y), style=f"link {u}")
        else:
            coords_cell = _coords(r.x, r.y)
        ally_s = (
            r.to_alliance_name if r.to_alliance_name else "—"
        )
        lost_txt = _fmt_dt(r.lost_at) if r.lost_at else "—"
        table.add_row(
            r.village_name or "-",
            coords_cell,
            _fmt_int(r.population),
            Text(r.to_player_name or "—", style="yellow"),
            ally_s,
            lost_txt,
        )

    console.print(table)


def render_alliance_history(history: AllianceHistory, *, server_key: str) -> None:
    pops = [p.population for p in history.points]
    spark = _sparkline(pops)

    title_text = (
        f"Alliance history — {history.alliance_name} (id={history.alliance_id}) on {server_key}"
    )

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Snapshots", str(len(history.points)))
    if history.points:
        first = history.points[0]
        last = history.points[-1]
        summary.add_row("First seen",   _fmt_dt(first.fetched_at))
        summary.add_row("Latest",       _fmt_dt(last.fetched_at))
        summary.add_row("Latest pop",   _fmt_int(last.population))
        summary.add_row("Latest members", _fmt_int(last.members))
        summary.add_row("Latest villages", _fmt_int(last.villages))
        summary.add_row("Population trend", Text(spark, style="bold cyan"))
        if len(history.points) >= 2:
            summary.add_row("Total change", _fmt_signed(last.population - first.population))

    console.print(Panel(summary, title=title_text, border_style="cyan"))

    table = Table(header_style="bold cyan", row_styles=["", "dim"])
    table.add_column("snap", justify="right", style="dim")
    table.add_column("fetched at", no_wrap=True)
    table.add_column("members",    justify="right")
    table.add_column("villages",   justify="right")
    table.add_column("population", justify="right", style="green")
    table.add_column("Δ pop",      justify="right")
    table.add_column("Δ mem",      justify="right")

    prev_pop: int | None = None
    prev_mem: int | None = None
    for p in history.points:
        d_pop = None if prev_pop is None else p.population - prev_pop
        d_mem = None if prev_mem is None else (p.members or 0) - prev_mem
        table.add_row(
            str(p.snapshot_id),
            _fmt_dt(p.fetched_at),
            _fmt_int(p.members),
            _fmt_int(p.villages),
            _fmt_int(p.population),
            _fmt_signed(d_pop) if d_pop is not None else Text("-", style="dim"),
            _fmt_signed(d_mem) if d_mem is not None else Text("-", style="dim"),
        )
        prev_pop, prev_mem = p.population, (p.members or 0)

    console.print(table)


# ---------- events -----------------------------------------------------------

def _coords(x: int, y: int) -> str:
    return f"({x:+d}|{y:+d})"


def render_event_period(
    *, server_key: str, prev_id: int | None, curr_id: int | None
) -> None:
    if prev_id is None or curr_id is None:
        console.print(
            f"[yellow]Need at least 2 snapshots for {server_key} to compute events. "
            "Run `python main.py fetch --server " + server_key + "` again later.[/yellow]"
        )
        return
    console.print(
        f"[bold]Events on {server_key}[/bold]  "
        f"(snapshot [bold]#{prev_id}[/bold] -> [bold]#{curr_id}[/bold])"
    )


def render_new_villages(rows: list[VillageEvent]) -> None:
    table = Table(
        title=f"New villages ({len(rows)})",
        title_style="bold green",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("village", style="bold", no_wrap=True)
    table.add_column("coords", justify="right", style="cyan", no_wrap=True)
    table.add_column("pop", justify="right", style="green")
    table.add_column("player", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    if not rows:
        console.print("[dim]No new villages.[/dim]")
        return
    for r in rows:
        table.add_row(
            r.village_name or "-",
            _coords(r.x, r.y),
            _fmt_int(r.population),
            r.player_name or "-",
            r.alliance_name or "-",
        )
    console.print(table)


def render_removed_villages(rows: list[VillageEvent]) -> None:
    table = Table(
        title=f"Removed villages ({len(rows)})",
        title_style="bold red",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("village", style="bold", no_wrap=True)
    table.add_column("coords", justify="right", style="cyan", no_wrap=True)
    table.add_column("pop", justify="right")
    table.add_column("former owner", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    if not rows:
        console.print("[dim]No villages removed.[/dim]")
        return
    for r in rows:
        table.add_row(
            r.village_name or "-",
            _coords(r.x, r.y),
            _fmt_int(r.population),
            r.player_name or "-",
            r.alliance_name or "-",
        )
    console.print(table)


def render_chiefed_villages(rows: list[VillageEvent]) -> None:
    table = Table(
        title=f"Chiefed villages — owner changed ({len(rows)})",
        title_style="bold yellow",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("village",  style="bold", no_wrap=True)
    table.add_column("coords",   justify="right", style="cyan", no_wrap=True)
    table.add_column("pop now",  justify="right", style="green")
    table.add_column("Δ pop",    justify="right")
    table.add_column("from",     style="red", no_wrap=True)
    table.add_column("to",       style="green", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    if not rows:
        console.print("[dim]No villages changed owner.[/dim]")
        return
    for r in rows:
        table.add_row(
            r.village_name or "-",
            _coords(r.x, r.y),
            _fmt_int(r.population),
            _fmt_signed(r.pop_change),
            r.prev_player_name or "-",
            r.player_name or "-",
            r.alliance_name or "-",
        )
    console.print(table)


def render_alliance_moves(rows: list[AllianceMove]) -> None:
    table = Table(
        title=f"Players changed alliance ({len(rows)})",
        title_style="bold blue",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("player",     style="bold", no_wrap=True)
    table.add_column("from",       style="red", no_wrap=True)
    table.add_column("to",         style="green", no_wrap=True)
    table.add_column("population", justify="right")
    if not rows:
        console.print("[dim]No players changed alliance.[/dim]")
        return
    for r in rows:
        table.add_row(
            r.player_name or "-",
            r.from_alliance_name or "(none)",
            r.to_alliance_name or "(none)",
            _fmt_int(r.population),
        )
    console.print(table)


def render_villages_ranking(
    rows: list[VillageRankRow],
    *,
    server_key: str,
    has_delta: bool,
    title: str | None = None,
) -> None:
    table = Table(
        title=title or f"Villages — {server_key}",
        title_style="bold",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("village", style="bold", no_wrap=True)
    table.add_column("coords", justify="right", style="cyan", no_wrap=True)
    table.add_column("tribe", no_wrap=True)
    table.add_column("flag", no_wrap=True, style="yellow")
    table.add_column("pop", justify="right", style="green")
    if has_delta:
        table.add_column("Δ pop", justify="right")
    table.add_column("player", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    if has_delta:
        table.add_column("note", style="yellow", no_wrap=True)

    if not rows:
        console.print(f"[dim]No villages to show for {server_key}.[/dim]")
        return

    for r in rows:
        cells: list[Any] = [
            str(r.rank),
            r.village_name or "-",
            _coords(r.x, r.y),
            Text(r.tribe_name, style=_TRIBE_STYLES.get(r.tribe_name, "")),
            r.flag_label or "—",
            _fmt_int(r.population),
        ]
        if has_delta:
            cells.append(_fmt_signed(r.pop_delta) if r.pop_delta is not None else Text("-", style="dim"))
        cells.extend([
            r.player_name or "-",
            r.alliance_name or "-",
        ])
        if has_delta:
            note = ""
            style = "yellow"
            if r.is_new:
                note = "NEW"
            elif r.owner_changed:
                note = "chiefed"
                style = "bold yellow"
            cells.append(Text(note, style=style))
        table.add_row(*cells)

    console.print(table)


def render_village_history(history: VillageHistory, *, server_key: str) -> None:
    pops = [p.population if p.population is not None else 0 for p in history.points]
    spark = _sparkline(pops)

    title_text = (
        f"Village history — {history.village_name} (id={history.village_id}) "
        f"{_coords(history.x, history.y)} on {server_key}"
    )

    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()
    summary.add_row("Snapshots", str(len(history.points)))

    if history.points:
        first, last = history.points[0], history.points[-1]
        summary.add_row("First seen",     _fmt_dt(first.fetched_at))
        summary.add_row("Latest",         _fmt_dt(last.fetched_at))
        summary.add_row("Latest pop",     _fmt_int(last.population))
        summary.add_row("Current owner",  last.player_name or "-")
        summary.add_row("Current alliance", last.alliance_name or "-")
        summary.add_row("Population trend", Text(spark, style="bold cyan"))
        if len(history.points) >= 2:
            change = (last.population or 0) - (first.population or 0)
            summary.add_row("Total change", _fmt_signed(change))
        owners = sorted({p.player_id for p in history.points})
        if len(owners) > 1:
            summary.add_row("Distinct owners", str(len(owners)))

    console.print(Panel(summary, title=title_text, border_style="cyan"))

    table = Table(header_style="bold cyan", row_styles=["", "dim"])
    table.add_column("snap", justify="right", style="dim")
    table.add_column("fetched at", no_wrap=True)
    table.add_column("owner", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)
    table.add_column("pop", justify="right", style="green")
    table.add_column("Δ pop", justify="right")
    table.add_column("event", style="yellow", no_wrap=True)

    prev_pop: int | None = None
    prev_pid: int | None = None
    for p in history.points:
        d_pop = (
            None
            if prev_pop is None or p.population is None
            else (p.population or 0) - prev_pop
        )
        event = ""
        if prev_pid is not None and p.player_id != prev_pid:
            event = "chiefed"
        elif prev_pid is None:
            event = "first seen"
        table.add_row(
            str(p.snapshot_id),
            _fmt_dt(p.fetched_at),
            p.player_name or "-",
            p.alliance_name or "-",
            _fmt_int(p.population),
            _fmt_signed(d_pop) if d_pop is not None else Text("-", style="dim"),
            event,
        )
        prev_pop = p.population if p.population is not None else prev_pop
        prev_pid = p.player_id

    console.print(table)


def render_village_movers(rows: list[VillageMover], *, direction: str) -> None:
    if direction == "grew":
        title_style = "bold green"
        title = f"Top village population gainers ({len(rows)})"
    else:
        title_style = "bold red"
        title = f"Top village population losers ({len(rows)})"

    table = Table(
        title=title,
        title_style=title_style,
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("village", style="bold", no_wrap=True)
    table.add_column("coords", justify="right", style="cyan", no_wrap=True)
    table.add_column("prev", justify="right", style="dim")
    table.add_column("now", justify="right", style="green")
    table.add_column("Δ pop", justify="right")
    table.add_column("player", no_wrap=True)
    table.add_column("alliance", style="magenta", no_wrap=True)

    if not rows:
        console.print("[dim]No villages to report.[/dim]")
        return

    for r in rows:
        table.add_row(
            r.village_name or "-",
            _coords(r.x, r.y),
            _fmt_int(r.prev_population),
            _fmt_int(r.curr_population),
            _fmt_signed(r.delta),
            r.player_name or "-",
            r.alliance_name or "-",
        )
    console.print(table)


def render_village_search_results(
    matches: list[tuple[int, str, str, int]], query: str
) -> None:
    if not matches:
        console.print(f"[yellow]No villages match '{query}'.[/yellow]")
        return
    console.print(
        f"[yellow]Multiple villages match '{query}'. Use --id to pick exactly one:[/yellow]"
    )
    table = Table(header_style="bold cyan")
    table.add_column("village_id", justify="right")
    table.add_column("village_name", style="bold")
    table.add_column("owner")
    table.add_column("population", justify="right")
    for vid, name, owner, pop in matches:
        table.add_row(str(vid), name, owner, _fmt_int(pop))
    console.print(table)


def render_player_search_results(
    matches: list[tuple[int, str, str]], query: str
) -> None:
    if not matches:
        console.print(f"[yellow]No players match '{query}'.[/yellow]")
        return
    console.print(
        f"[yellow]Multiple players match '{query}'. Use --id to pick exactly one:[/yellow]"
    )
    table = Table(header_style="bold cyan")
    table.add_column("player_id", justify="right")
    table.add_column("player_name", style="bold")
    table.add_column("tribe")
    for pid, name, tribe in matches:
        table.add_row(
            str(pid), name, Text(tribe, style=_TRIBE_STYLES.get(tribe, ""))
        )
    console.print(table)


def render_alliance_search_results(matches: list[tuple[int, str]], query: str) -> None:
    if not matches:
        console.print(f"[yellow]No alliances match '{query}'.[/yellow]")
        return
    console.print(
        f"[yellow]Multiple alliances match '{query}'. Use --id to pick exactly one:[/yellow]"
    )
    table = Table(header_style="bold cyan")
    table.add_column("alliance_id", justify="right")
    table.add_column("alliance_name", style="bold")
    for aid, name in matches:
        table.add_row(str(aid), name)
    console.print(table)
