"""Terminal menu: fetch, settings, quit (keyboard shortcuts)."""


from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.config import load_config
from src.fetch_ingest import fetch_all_enabled_servers
from src.ui_settings import (
    MAP_PALETTES,
    cycle_map_palette,
    load_ui_settings,
    save_ui_settings,
)

console = Console()


def _menu_use_quick_keys(*, cli_line: bool, cli_quick: bool) -> bool:
    """False = type command + Enter (works in Cursor/VS Code terminals). True = one key.

    Override with ``T_STATS_MENU_RAW=1`` to default to immediate keys without a flag.
    """
    if cli_line:
        return False
    if cli_quick:
        return True
    raw = os.environ.get("T_STATS_MENU_RAW", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return False


def _read_key_immediate() -> str:
    """Single keypress, lowercase. Windows: msvcrt; Unix: tty raw mode."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getch()
        if ch in (b"\x03",):  # Ctrl+C
            raise KeyboardInterrupt
        if ch in (b"\r", b"\n"):
            return "\r"
        try:
            return ch.decode("utf-8", errors="replace").lower()
        except Exception:
            return "?"
    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch.lower()


def _parse_main_choice(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in ("fetch", "map", "download"):
        return "f"
    if s in ("settings", "setting", "config", "palette", "colour", "color"):
        return "s"
    if s in ("refresh", "restart", "reload"):
        return "r"
    if s in ("quit", "exit", "bye", "logout", "logoff"):
        return "q"
    return s[0]


def _read_main_choice(*, quick_keys: bool) -> str:
    if quick_keys:
        return _parse_main_choice(_read_key_immediate())
    try:
        line = input(
            "\n► Type command + Enter "
            "(f fetch · s settings · r refresh · q quit, or words like fetch/settings): ",
        )
    except EOFError:
        return "q"
    return _parse_main_choice(line)


def _parse_settings_choice(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if s in ("back", "b", "cancel"):
        return "b"
    if s in ("quit", "exit", "q"):
        return "q"
    if s in ("toggle", "swap", "next"):
        return "t"
    return s[:1]


def _read_settings_choice(*, quick_keys: bool) -> str:
    if quick_keys:
        return _read_key_immediate().lower()
    try:
        line = input(
            "► Type + Enter "
            "(t toggle · 1-9 row · b back · q quit): ",
        )
    except EOFError:
        return "q"
    pc = _parse_settings_choice(line)
    if pc in ("\x1b",) or line.strip().lower() in ("esc", "escape"):
        return "b"
    return pc


def _settings_loop(ui_path: Path, *, quick_keys: bool) -> None:
    while True:
        s = load_ui_settings(ui_path)
        pal = next(p for p in MAP_PALETTES if p.key == s.map_palette)

        table = Table(title="Map palette (dashboard world map)", box=box.ROUNDED)
        table.add_column("#", style="dim", justify="right")
        table.add_column("Key", style="cyan", no_wrap=True)
        table.add_column("Description")
        for i, p in enumerate(MAP_PALETTES):
            mark = "→ " if p.key == s.map_palette else "  "
            table.add_row(str(i + 1), mark + p.key, p.title)

        console.print(table)
        hint = "[dim](single keystroke)[/dim] " if quick_keys else "[dim](type letter + Enter)[/dim] "
        console.print(
            f"\n[bold]Current:[/bold] [green]{pal.key}[/green] — {pal.title}\n"
            f"[T] Toggle palette   "
            "[1-9] Row number for a palette key   "
            "[B] Back to main menu   "
            "[Q] Quit program\n"
            f"{hint}"
        )
        k = _read_settings_choice(quick_keys=quick_keys)
        if k in ("b", "\x1b"):  # b or Esc
            return
        if k == "q":
            raise SystemExit(0)
        if k == "t":
            s.map_palette = cycle_map_palette(s.map_palette)
            save_ui_settings(s, ui_path)
            console.print(f"[dim]Saved → {s.map_palette}[/dim]\n")
            continue
        if k.isdigit():
            i = int(k) - 1
            if 0 <= i < len(MAP_PALETTES):
                s.map_palette = MAP_PALETTES[i].key
                save_ui_settings(s, ui_path)
                console.print(f"[dim]Saved → {s.map_palette}[/dim]\n")
        console.print()


def _run_fetch_loop(*, config_path: Path, db_path: Path) -> None:
    """Download + ingest for every enabled server (same as ``main.py fetch``)."""
    cfg = load_config(config_path)
    console.print("\n[bold cyan]Fetch — all enabled servers[/bold cyan]\n")
    try:
        fetch_all_enabled_servers(cfg, db_path)
        console.print("[green]Done.[/green]")
    except Exception as e:
        logging.getLogger(__name__).exception("Fetch failed")
        console.print(f"[red]Fetch aborted: {e}[/red]")
    console.print()


def _restart_menu(
    *,
    config_path: Path,
    db_path: Path,
    ui_path: Path,
    line_input_explicit: bool,
    quick_keys_explicit: bool,
) -> None:
    """Start a fresh `main.py menu` with the same options and exit this process."""
    main_py = (Path(__file__).resolve().parent.parent / "main.py").resolve()
    cwd = str(main_py.parent)
    argv = [
        sys.executable,
        str(main_py),
        "--config",
        str(config_path),
        "--db",
        str(db_path),
        "menu",
        "--ui",
        str(ui_path),
    ]
    if line_input_explicit:
        argv.append("--line-input")
    if quick_keys_explicit:
        argv.append("--quick-keys")
    console.print("[dim yellow]Refreshing — restarting this menu session…[/dim yellow]\n")
    subprocess.Popen(argv, cwd=cwd)
    sys.exit(0)


def run_terminal_menu(
    *,
    ui_path: Path,
    config_path: Path,
    db_path: Path,
    line_input: bool,
    quick_keys: bool,
) -> int:
    quick = _menu_use_quick_keys(cli_line=line_input, cli_quick=quick_keys)

    exe = Path(sys.executable).name
    main_rel = "main.py"
    cfg_s = str(config_path).replace("\\", "/")
    db_s = str(db_path).replace("\\", "/")

    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    while True:
        ref = Table(
            title="CLI equivalents (same repo)",
            box=box.SIMPLE_HEAVY,
            show_header=True,
            header_style="bold dim",
        )
        ref.add_column("Key", style="cyan bold", no_wrap=True)
        ref.add_column("Action", style="bold")
        ref.add_column("Like", style="dim")
        ref.add_row(
            "F",
            "Fetch map.sql → database",
            f"{exe} {main_rel} fetch --config {cfg_s} --db {db_s}",
        )
        ref.add_row(
            "S",
            "Settings (map palette UI)",
            f"(writes {ui_path.as_posix()})",
        )
        ref.add_row(
            "R",
            "Refresh — restart this menu",
            f"{exe} {main_rel} menu --ui … (--config/--db unchanged)",
        )
        ref.add_row("Q", "Quit this menu", "—")

        inp_hint = (
            "[yellow]Line input (default):[/yellow] type [cyan]f[/cyan]/[cyan]s[/cyan]/"
            "[cyan]r[/cyan]/[cyan]q[/cyan] or a word, then [bold]Enter[/bold].\n"
            "[dim]Single-key (no Enter):[/dim] [cyan]--quick-keys[/cyan] or "
            "[cyan]T_STATS_MENU_RAW=1[/cyan]\n\n"
            if not quick
            else "[dim]Single-key mode — press a letter with no Enter[/dim]\n\n"
        )

        console.print(
            Panel.fit(
                inp_hint
                + "[bold]t.statistics.stas.bot[/bold] — keyboard menu\n\n"
                "[F] [bold]Fetch[/bold] — all enabled servers ([cyan]"
                + exe
                + "[/cyan] … [cyan]"
                + main_rel
                + " fetch[/cyan])\n[S] [bold]Settings[/bold] — dashboard map colors ([cyan]"
                + ui_path.as_posix()
                + "[/cyan])\n[R] [bold]Refresh[/bold] — quit this session & open menu again\n"
                "[Q] [bold]Quit[/bold]",
                title="Main menu",
                border_style="blue",
            )
        )
        console.print(ref)
        console.print(
            "[dim]More commands (project root): "
            "`python main.py run` · `python main.py analyze` · `python main.py players` · "
            "`python main.py --help`\n[/dim]",
        )
        k = _read_main_choice(quick_keys=quick)
        if k == "q":
            console.print("[dim]Goodbye.[/dim]")
            return 0
        elif k == "f":
            console.print()
            try:
                _run_fetch_loop(config_path=config_path, db_path=db_path)
            except KeyboardInterrupt:
                console.print("\n[yellow]Fetch interrupted.[/yellow]\n")
            continue
        elif k == "r":
            _restart_menu(
                config_path=config_path,
                db_path=db_path,
                ui_path=ui_path,
                line_input_explicit=line_input,
                quick_keys_explicit=quick_keys,
            )
        elif k == "s":
            console.print()
            try:
                _settings_loop(ui_path, quick_keys=quick)
            except SystemExit as e:
                return int(e.code) if e.code is not None else 0
            console.print()
        else:
            console.print("[dim]Unknown command — use f, s, r, or q.[/dim]\n")