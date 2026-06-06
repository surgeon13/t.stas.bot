"""CLI entry point.

Examples:

    python main.py list-servers
    python main.py fetch                       # fetch all enabled servers once
    python main.py fetch --server europe31x3   # fetch a specific server
    python main.py analyze --server europe31x3 # show latest stats + delta
    python main.py                               # same as: run --no-schedule-stdin (unattended loop)
    python main.py run                         # scheduled loop + optional stdin commands
    python main.py menu              # interactive: [F]etch [R]efresh [S]ettings [Q]uit
    python main.py inactives --server europe31x3 --x 10 --y -20
    python main.py add-server --key myspeed --name "My x3" --base-url https://ts.example.com --tag europe --tag x3

Full CLI and dashboard docs: docs/USAGE.md
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    from src import analyzer, fetch_ingest, scheduler, storage, view
    from src.config import AppConfig, ServerConfig, append_server, load_config
    from src.terminal_menu import run_terminal_menu
except ModuleNotFoundError as e:
    missing = getattr(e, "name", None)
    print(
        "error: missing Python dependency. Install requirements with:\n"
        "  python -m pip install -r requirements.txt",
        file=sys.stderr,
    )
    if missing:
        print(f"missing module: {missing}", file=sys.stderr)
    raise SystemExit(1) from e


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _select_servers(cfg: AppConfig, key: str | None) -> list[ServerConfig]:
    if key:
        s = cfg.get_server(key)
        if s is None:
            raise SystemExit(f"Unknown server key '{key}'. Try `list-servers`.")
        if not s.enabled:
            print(f"warning: server '{key}' is disabled in config", file=sys.stderr)
        return [s]
    enabled = list(cfg.enabled_servers())
    if not enabled:
        raise SystemExit("No enabled servers in config.")
    return enabled


def _select_one_server(cfg: AppConfig, key: str | None) -> ServerConfig:
    """For commands that target exactly one server."""
    if key:
        return _select_servers(cfg, key)[0]
    enabled = list(cfg.enabled_servers())
    if len(enabled) == 1:
        return enabled[0]
    keys = ", ".join(s.key for s in enabled) or "(none)"
    raise SystemExit(
        f"Multiple enabled servers; please pass --server. Available: {keys}"
    )


def cmd_menu(args: argparse.Namespace) -> int:
    return run_terminal_menu(
        ui_path=Path(args.ui),
        config_path=Path(args.config),
        db_path=Path(args.db),
        line_input=args.menu_line_input,
        quick_keys=args.menu_quick_keys,
    )


def cmd_list_servers(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    view.render_servers(cfg.servers, cfg.settings.schedule)
    return 0


def cmd_add_server(args: argparse.Namespace) -> int:
    path_written, body = append_server(
        config_path=Path(args.config),
        key=args.key,
        name=args.name,
        base_url=args.base_url,
        tags=args.tags or [],
        enabled=not args.disable,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(body, end="")
        print(f"# dry-run: would write {path_written}")
    else:
        print(f"Appended server {args.key!r} to {path_written}")
        try:
            load_config(args.config)
        except Exception as e:
            print(
                "error: file updated but config does not parse or validate — "
                f"please fix YAML/JSON manually: {e}",
                file=sys.stderr,
            )
            return 1
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    servers = _select_servers(cfg, args.server)

    rc = 0
    for s in servers:
        try:
            fetch_ingest.fetch_one_server(cfg, s, db_path)
        except Exception as e:
            logging.exception("Failed to fetch %s: %s", s.key, e)
            rc = 1
    return rc


def cmd_analyze(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    servers = _select_servers(cfg, args.server)

    with storage.open_db(db_path) as conn:
        for s in servers:
            latest = storage.latest_snapshot(conn, s.key)
            if latest is None:
                view.render_message(
                    f"No snapshots stored for server '{s.key}' yet.", style="yellow"
                )
                continue

            stats = analyzer.compute_snapshot_stats(
                conn, int(latest["id"]), top_n=args.top
            )
            prev = storage.previous_snapshot(conn, s.key, int(latest["id"]))
            delta = (
                analyzer.compute_delta(conn, int(prev["id"]), int(latest["id"]))
                if prev
                else None
            )
            view.render_report(stats, delta)
            print()
    return 0


def cmd_players(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    servers = _select_servers(cfg, args.server)

    with storage.open_db(db_path) as conn:
        for s in servers:
            latest = storage.latest_snapshot(conn, s.key)
            if latest is None:
                view.render_message(f"No snapshots for '{s.key}' yet.", style="yellow")
                continue
            prev = storage.previous_snapshot(conn, s.key, int(latest["id"]))
            rows = analyzer.players_ranked(conn, s.key, top_n=args.top, sort=args.sort)
            view.render_player_ranking(rows, server_key=s.key, has_delta=prev is not None)
            print()
    return 0


def cmd_player(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    server = _select_one_server(cfg, args.server)

    if args.id is None and not args.name:
        raise SystemExit("Pass either --id <int> or --name <text>.")

    with storage.open_db(db_path) as conn:
        if args.id is not None:
            player_id = args.id
        else:
            matches = analyzer.find_players(conn, server.key, args.name or "")
            if len(matches) == 0:
                view.render_player_search_results([], args.name or "")
                return 1
            if len(matches) > 1:
                view.render_player_search_results(matches, args.name or "")
                return 0
            player_id = matches[0][0]

        history = analyzer.player_history(conn, server.key, player_id)
        if history is None:
            view.render_message(
                f"No history for player_id={player_id} on {server.key}.", style="yellow"
            )
            return 1
        view.render_player_history(history, server_key=server.key)

        if not getattr(args, "no_villages", False):
            print()
            ledger = analyzer.player_villages_with_history(
                conn, server.key, player_id
            )
            view.render_player_village_ledger(
                ledger,
                player_name=history.player_name,
                server_key=server.key,
                game_base_url=server.base_url,
            )
            lost = analyzer.player_villages_lost(conn, server.key, player_id)
            view.render_player_villages_lost(
                lost,
                player_name=history.player_name,
                server_key=server.key,
                game_base_url=server.base_url,
            )
    return 0


def cmd_alliances(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    servers = _select_servers(cfg, args.server)

    with storage.open_db(db_path) as conn:
        for s in servers:
            latest = storage.latest_snapshot(conn, s.key)
            if latest is None:
                view.render_message(f"No snapshots for '{s.key}' yet.", style="yellow")
                continue
            prev = storage.previous_snapshot(conn, s.key, int(latest["id"]))
            rows = analyzer.alliances_ranked(conn, s.key, top_n=args.top, sort=args.sort)
            view.render_alliance_ranking(rows, server_key=s.key, has_delta=prev is not None)
            print()
    return 0


def cmd_alliance(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    server = _select_one_server(cfg, args.server)

    if args.id is None and not args.name:
        raise SystemExit("Pass either --id <int> or --name <text>.")

    with storage.open_db(db_path) as conn:
        if args.id is not None:
            alliance_id = args.id
        else:
            matches = analyzer.find_alliances(conn, server.key, args.name or "")
            if len(matches) == 0:
                view.render_alliance_search_results([], args.name or "")
                return 1
            if len(matches) > 1:
                view.render_alliance_search_results(matches, args.name or "")
                return 0
            alliance_id = matches[0][0]

        history = analyzer.alliance_history(conn, server.key, alliance_id)
        if history is None:
            view.render_message(
                f"No history for alliance_id={alliance_id} on {server.key}.", style="yellow"
            )
            return 1
        view.render_alliance_history(history, server_key=server.key)
    return 0


def cmd_villages(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    server = _select_one_server(cfg, args.server)

    with storage.open_db(db_path) as conn:
        latest = storage.latest_snapshot(conn, server.key)
        if latest is None:
            view.render_message(f"No snapshots for '{server.key}' yet.", style="yellow")
            return 1
        prev = storage.previous_snapshot(conn, server.key, int(latest["id"]))

        # Optional --player resolves to a player_id (numeric or name lookup).
        player_id: int | None = None
        if args.player is not None:
            if args.player.isdigit():
                player_id = int(args.player)
            else:
                matches = analyzer.find_players(conn, server.key, args.player)
                if not matches:
                    view.render_player_search_results([], args.player)
                    return 1
                if len(matches) > 1:
                    view.render_player_search_results(matches, args.player)
                    return 0
                player_id = matches[0][0]

        rows = analyzer.villages_ranked(
            conn, server.key, top_n=args.top, player_id=player_id, sort=args.sort
        )

        title_bits = [f"Villages — {server.key}"]
        if player_id is not None:
            title_bits.append(f"player_id={player_id}")
        if args.sort != "population":
            title_bits.append(f"sort={args.sort}")
        title = " | ".join(title_bits)

        view.render_villages_ranking(
            rows, server_key=server.key, has_delta=prev is not None, title=title
        )
    return 0


def cmd_village(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    server = _select_one_server(cfg, args.server)

    if args.id is None and not args.name:
        raise SystemExit("Pass either --id <int> or --name <text>.")

    with storage.open_db(db_path) as conn:
        if args.id is not None:
            village_id = args.id
        else:
            matches = analyzer.find_villages(conn, server.key, args.name or "")
            if not matches:
                view.render_village_search_results([], args.name or "")
                return 1
            if len(matches) > 1:
                view.render_village_search_results(matches, args.name or "")
                return 0
            village_id = matches[0][0]

        history = analyzer.village_history(conn, server.key, village_id)
        if history is None:
            view.render_message(
                f"No history for village_id={village_id} on {server.key}.", style="yellow"
            )
            return 1
        view.render_village_history(history, server_key=server.key)
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    db_path = Path(args.db)
    server = _select_one_server(cfg, args.server)

    with storage.open_db(db_path) as conn:
        pair = analyzer.resolve_event_pair(
            conn, server.key, from_id=args.from_id, to_id=args.to_id
        )
        if pair is None:
            view.render_event_period(server_key=server.key, prev_id=None, curr_id=None)
            return 0
        prev_id, curr_id = pair
        view.render_event_period(server_key=server.key, prev_id=prev_id, curr_id=curr_id)

        kinds = (
            {args.kind} if args.kind != "all"
            else {"new", "removed", "chiefed", "ally-move", "grew", "shrunk"}
        )

        if "new" in kinds:
            view.render_new_villages(
                analyzer.new_villages(conn, prev_id, curr_id, limit=args.limit)
            )
        if "removed" in kinds:
            view.render_removed_villages(
                analyzer.removed_villages(conn, prev_id, curr_id, limit=args.limit)
            )
        if "chiefed" in kinds:
            view.render_chiefed_villages(
                analyzer.chiefed_villages(conn, prev_id, curr_id, limit=args.limit)
            )
        if "ally-move" in kinds:
            view.render_alliance_moves(
                analyzer.alliance_moves(conn, prev_id, curr_id, limit=args.limit)
            )
        if "grew" in kinds:
            view.render_village_movers(
                analyzer.village_movers(
                    conn, prev_id, curr_id, direction="grew", limit=args.limit
                ),
                direction="grew",
            )
        if "shrunk" in kinds:
            view.render_village_movers(
                analyzer.village_movers(
                    conn, prev_id, curr_id, direction="shrunk", limit=args.limit
                ),
                direction="shrunk",
            )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    db_path = Path(args.db)
    cfg = load_config(cfg_path)

    def job() -> None:
        live = load_config(cfg_path)
        fetch_ingest.fetch_all_enabled_servers(live, db_path)

    scheduler.run_loop(
        cfg.settings.schedule,
        job,
        stdin_commands=False if args.no_schedule_stdin else None,
    )
    return 0


def cmd_snapshots(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    with storage.open_db(db_path) as conn:
        rows = storage.list_snapshots(conn, args.server, limit=args.limit)
    view.render_snapshots(rows)
    return 0


def cmd_inactives(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    server = _select_one_server(cfg, args.server)
    db_path = Path(args.db)
    app_settings = cfg.settings
    radius_max = args.radius if args.radius is not None else app_settings.inactive_search_radius
    radius_min = int(getattr(args, "radius_min", 0) or 0)
    min_snaps = (
        args.min_snapshots
        if args.min_snapshots is not None
        else app_settings.inactive_min_snapshots
    )
    exclude_npc = app_settings.inactive_exclude_npc and not args.include_npc

    with storage.open_db(db_path) as conn:
        snap_n = len(storage.list_snapshots(conn, server.key, limit=9999))
        if snap_n < min_snaps:
            print(
                f"Note: only {snap_n} snapshot(s) stored; inactive search needs "
                f"at least {min_snaps} so every match has enough history. "
                "Run `python main.py fetch` again after villages may have changed.\n",
                file=sys.stderr,
            )
        rows = analyzer.inactive_villages_near(
            conn,
            server.key,
            args.x,
            args.y,
            radius_min=radius_min,
            radius_max=radius_max,
            min_snapshots=min_snaps,
            exclude_npc=exclude_npc,
            limit=args.limit,
            player_total_pop_min=int(args.player_pop_min),
            player_total_pop_max=int(args.player_pop_max),
        )
    view.render_inactives_near(
        rows,
        server_name=server.name,
        server_key=server.key,
        center_x=args.x,
        center_y=args.y,
        radius_min=radius_min,
        radius_max=radius_max,
        min_snapshots=min_snaps,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="t.statistics.stas.bot",
        description="Download Travian map.sql snapshots and analyze them over time.",
    )
    p.add_argument(
        "--config",
        default="config/servers.json",
        help="app config JSON: servers[] + settings (see config/servers.json.example)",
    )
    p.add_argument("--db", default="statistics.db", help="path to SQLite database file")
    p.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")

    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser(
        "menu",
        help=(
            "interactive menu — default: type f/s/r/q + Enter "
            "(Cursor/IDE); use --quick-keys for single-character mode"
        ),
    )
    sp.add_argument(
        "--ui",
        default="config/ui.yaml",
        help="path to UI settings (map palette); same file the dashboard reads",
    )
    _mux_menu = sp.add_mutually_exclusive_group()
    _mux_menu.add_argument(
        "--line-input",
        action="store_true",
        dest="menu_line_input",
        help="force buffered line prompts (same as default; use if you exported T_STATS_MENU_RAW)",
    )
    _mux_menu.add_argument(
        "--quick-keys",
        action="store_true",
        dest="menu_quick_keys",
        help="immediate single-character keys without Enter",
    )
    sp.set_defaults(func=cmd_menu, menu_line_input=False, menu_quick_keys=False)

    sp = sub.add_parser("list-servers", help="show servers from config")
    sp.set_defaults(func=cmd_list_servers)

    sp = sub.add_parser(
        "add-server",
        help="append a server entry to the JSON file from global --config (default config/servers.json)",
    )
    sp.add_argument("--key", required=True, help="unique server id (DB + --server value)")
    sp.add_argument("--name", required=True, help="display name")
    sp.add_argument("--base-url", required=True, help="https://… server root (map.sql is fetched from here)")
    sp.add_argument("--tag", action="append", dest="tags", default=None,
                    help="repeat for each tag, e.g. --tag europe --tag x3")
    sp.add_argument(
        "--disable",
        action="store_true",
        help="write enabled: false",
    )
    sp.add_argument("--dry-run", action="store_true", help="print JSON body; do not write")
    sp.set_defaults(func=cmd_add_server)

    sp = sub.add_parser("fetch", help="download map.sql once and store it")
    sp.add_argument("--server", help="server key (default: all enabled)")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("analyze", help="print stats for the latest snapshot")
    sp.add_argument("--server", help="server key (default: all enabled)")
    sp.add_argument("--top", type=int, default=10, help="top N players/alliances to list")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("snapshots", help="list stored snapshots")
    sp.add_argument("--server", help="filter by server key")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_snapshots)

    sp = sub.add_parser(
        "inactives",
        help="find villages with flat population near (x|y); radius & rules from config unless overridden",
    )
    sp.add_argument("--server", help="server key (required if more than one enabled)")
    sp.add_argument("--x", type=int, required=True, help="center map x")
    sp.add_argument("--y", type=int, required=True, help="center map y")
    sp.add_argument(
        "--radius",
        type=int,
        default=None,
        help="maximum Euclidean tile radius (default: settings.inactive_search_radius)",
    )
    sp.add_argument(
        "--radius-min",
        type=int,
        default=0,
        dest="radius_min",
        help="minimum Euclidean tile radius (0 = include center tile)",
    )
    sp.add_argument(
        "--min-snapshots",
        type=int,
        default=None,
        dest="min_snapshots",
        help="min stored observations per village (default: settings.inactive_min_snapshots)",
    )
    sp.add_argument(
        "--include-npc",
        action="store_true",
        help="include Nature/Natars and unowned villages (overrides settings.inactive_exclude_npc)",
    )
    sp.add_argument("--limit", type=int, default=500, help="max rows to print")
    sp.add_argument(
        "--player-pop-min",
        type=int,
        default=0,
        metavar="N",
        help="min total population of owning player in latest snapshot (0 = no filter)",
    )
    sp.add_argument(
        "--player-pop-max",
        type=int,
        default=0,
        metavar="N",
        help="max total population of owning player in latest snapshot (0 = no filter)",
    )
    sp.set_defaults(func=cmd_inactives)

    sp = sub.add_parser("players", help="rank players by population (with delta vs previous snapshot)")
    sp.add_argument("--server", help="server key (default: all enabled)")
    sp.add_argument("--top", type=int, default=25, help="how many players to show")
    sp.add_argument("--sort", choices=["population", "villages"], default="population")
    sp.set_defaults(func=cmd_players)

    sp = sub.add_parser("player", help="show one player's history + village ledger")
    sp.add_argument("--server", help="server key (required if more than one)")
    sp.add_argument("--name", help="partial player name (case-insensitive)")
    sp.add_argument("--id", type=int, help="exact player_id")
    sp.add_argument(
        "--no-villages",
        action="store_true",
        help="skip the per-village settled/conquered ledger",
    )
    sp.set_defaults(func=cmd_player)

    sp = sub.add_parser("alliances", help="rank alliances by population (with delta vs previous snapshot)")
    sp.add_argument("--server", help="server key (default: all enabled)")
    sp.add_argument("--top", type=int, default=25, help="how many alliances to show")
    sp.add_argument("--sort", choices=["population", "members", "villages"], default="population")
    sp.set_defaults(func=cmd_alliances)

    sp = sub.add_parser("alliance", help="show one alliance's history across snapshots")
    sp.add_argument("--server", help="server key (required if more than one)")
    sp.add_argument("--name", help="partial alliance name (case-insensitive)")
    sp.add_argument("--id", type=int, help="exact alliance_id")
    sp.set_defaults(func=cmd_alliance)

    sp = sub.add_parser(
        "villages",
        help="rank villages in the latest snapshot (current pop and per-village delta)",
    )
    sp.add_argument("--server", help="server key (required if more than one)")
    sp.add_argument("--top", type=int, default=25, help="how many villages to show")
    sp.add_argument(
        "--sort",
        choices=["population", "growth", "loss"],
        default="population",
        help="population (largest first), growth (biggest gainers), loss (biggest losers)",
    )
    sp.add_argument(
        "--player",
        help="restrict to one player's villages (numeric player_id or partial name)",
    )
    sp.set_defaults(func=cmd_villages)

    sp = sub.add_parser("village", help="show one village's history across snapshots")
    sp.add_argument("--server", help="server key (required if more than one)")
    sp.add_argument("--name", help="partial village name (case-insensitive)")
    sp.add_argument("--id", type=int, help="exact village_id")
    sp.set_defaults(func=cmd_village)

    sp = sub.add_parser(
        "events",
        help="show events between two snapshots (default: latest two): new villages, "
             "chiefed villages, alliance moves, top movers",
    )
    sp.add_argument("--server", help="server key (required if more than one)")
    sp.add_argument(
        "--kind",
        choices=["all", "new", "removed", "chiefed", "ally-move", "grew", "shrunk"],
        default="all",
        help="which kind of event to show",
    )
    sp.add_argument("--from-id", dest="from_id", type=int,
                    help="snapshot id to compare from (defaults to second-latest)")
    sp.add_argument("--to-id", dest="to_id", type=int,
                    help="snapshot id to compare to (defaults to latest)")
    sp.add_argument("--limit", type=int, default=50, help="cap rows per event kind")
    sp.set_defaults(func=cmd_events)

    sp = sub.add_parser(
        "run",
        help=(
            "run the scheduled daily loop (foreground); type stdin commands for ad hoc schedules "
            "(see --no-schedule-stdin)"
        ),
    )
    sp.add_argument(
        "--no-schedule-stdin",
        action="store_true",
        help="do not read ad hoc schedule commands from stdin (fetch, every N m, daily HH:MM, …)",
    )
    sp.set_defaults(func=cmd_run)

    return p


_SUBCOMMANDS = frozenset(
    {
        "menu",
        "list-servers",
        "add-server",
        "fetch",
        "analyze",
        "snapshots",
        "inactives",
        "players",
        "player",
        "alliances",
        "alliance",
        "villages",
        "village",
        "events",
        "run",
    }
)


def _argv_with_default_run(argv: list[str]) -> list[str]:
    """Unattended default: ``python main.py`` → ``run --no-schedule-stdin``."""
    if not argv:
        return ["run", "--no-schedule-stdin"]
    if argv[0] in ("-h", "--help"):
        return argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            return argv
        if a.startswith("-"):
            if a in ("--config", "--db") and i + 1 < len(argv):
                i += 2
                continue
            i += 1
            continue
        if a in _SUBCOMMANDS:
            return argv
        return argv
    return [*argv, "run", "--no-schedule-stdin"]


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    args = build_parser().parse_args(_argv_with_default_run(argv))
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
