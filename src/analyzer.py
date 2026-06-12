"""Analysis helpers — stats, rankings, history, and cross-snapshot events."""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from . import storage

log = logging.getLogger(__name__)


def village_flag_label(region: str | None, extra_json: str | None) -> str:
    """Human-readable flag / marker from map.sql extras.

    Travian exports often put a TRUE/FALSE in the first extra slot (capital /
    highlighted village) and optional region text in ``region``.
    """
    parts: list[str] = []
    cap = ""
    if extra_json:
        try:
            ex = json.loads(extra_json)
            if isinstance(ex, (list, tuple)) and len(ex) > 0:
                v = ex[0]
                if isinstance(v, str):
                    u = v.upper()
                    if u == "TRUE":
                        cap = "★"
                    elif u == "FALSE":
                        cap = "·"
        except (json.JSONDecodeError, TypeError):
            pass
    if cap:
        parts.append(cap)
    reg = (region or "").strip()
    if reg:
        parts.append(reg)
    return " ".join(parts) if parts else "—"


TRIBE_NAMES = {
    1: "Romans",
    2: "Teutons",
    3: "Gauls",
    4: "Nature",
    5: "Natars",
    6: "Egyptians",
    7: "Huns",
    8: "Spartans",
    9: "Vikings",
}


@dataclass(frozen=True)
class SnapshotStats:
    snapshot_id: int
    server_key: str
    fetched_at: str
    villages: int
    players: int
    alliances: int
    total_population: int
    avg_population: float
    tribe_counts: dict[str, int]
    top_players: list[dict[str, Any]]
    top_alliances: list[dict[str, Any]]


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    cur = conn.execute(sql, params)
    val = cur.fetchone()[0]
    return int(val) if val is not None else 0


def compute_snapshot_stats(
    conn: sqlite3.Connection, snapshot_id: int, *, top_n: int = 10
) -> SnapshotStats:
    snap = conn.execute(
        "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
    ).fetchone()
    if snap is None:
        raise ValueError(f"Snapshot id {snapshot_id} not found")

    villages = _scalar(
        conn, "SELECT COUNT(*) FROM villages WHERE snapshot_id = ?", (snapshot_id,)
    )
    players = _scalar(
        conn,
        "SELECT COUNT(DISTINCT player_id) FROM villages WHERE snapshot_id = ? AND player_id != 0",
        (snapshot_id,),
    )
    alliances = _scalar(
        conn,
        "SELECT COUNT(DISTINCT alliance_id) FROM villages WHERE snapshot_id = ? AND alliance_id != 0",
        (snapshot_id,),
    )
    total_pop = _scalar(
        conn,
        "SELECT COALESCE(SUM(population), 0) FROM villages WHERE snapshot_id = ?",
        (snapshot_id,),
    )

    tribe_counts: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT tribe_id, COUNT(*) AS n
        FROM villages WHERE snapshot_id = ?
        GROUP BY tribe_id ORDER BY n DESC
        """,
        (snapshot_id,),
    ):
        name = TRIBE_NAMES.get(int(row["tribe_id"]), f"tribe_{row['tribe_id']}")
        tribe_counts[name] = int(row["n"])

    top_players = [
        {
            "player_id": int(r["player_id"]),
            "player_name": r["player_name"],
            "alliance_name": r["alliance_name"],
            "villages": int(r["villages"]),
            "population": int(r["population"]),
        }
        for r in conn.execute(
            """
            SELECT player_id,
                   MAX(player_name)   AS player_name,
                   MAX(alliance_name) AS alliance_name,
                   COUNT(*)           AS villages,
                   COALESCE(SUM(population), 0) AS population
            FROM villages
            WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id
            ORDER BY population DESC, villages DESC
            LIMIT ?
            """,
            (snapshot_id, top_n),
        )
    ]

    top_alliances = [
        {
            "alliance_id": int(r["alliance_id"]),
            "alliance_name": r["alliance_name"],
            "members": int(r["members"]),
            "villages": int(r["villages"]),
            "population": int(r["population"]),
        }
        for r in conn.execute(
            """
            SELECT alliance_id,
                   MAX(alliance_name)             AS alliance_name,
                   COUNT(DISTINCT player_id)      AS members,
                   COUNT(*)                       AS villages,
                   COALESCE(SUM(population), 0)   AS population
            FROM villages
            WHERE snapshot_id = ? AND alliance_id != 0
            GROUP BY alliance_id
            ORDER BY population DESC, members DESC
            LIMIT ?
            """,
            (snapshot_id, top_n),
        )
    ]

    avg_pop = float(total_pop) / villages if villages else 0.0

    return SnapshotStats(
        snapshot_id=int(snap["id"]),
        server_key=str(snap["server_key"]),
        fetched_at=str(snap["fetched_at"]),
        villages=villages,
        players=players,
        alliances=alliances,
        total_population=total_pop,
        avg_population=avg_pop,
        tribe_counts=tribe_counts,
        top_players=top_players,
        top_alliances=top_alliances,
    )


@dataclass(frozen=True)
class SnapshotDelta:
    from_id: int
    to_id: int
    new_villages: int
    removed_villages: int
    population_change: int
    new_players: int
    lost_players: int


def compute_delta(
    conn: sqlite3.Connection, prev_id: int, curr_id: int
) -> SnapshotDelta:
    new_villages = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM villages c
        WHERE c.snapshot_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM villages p
            WHERE p.snapshot_id = ? AND p.village_id = c.village_id
          )
        """,
        (curr_id, prev_id),
    )
    removed_villages = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM villages p
        WHERE p.snapshot_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM villages c
            WHERE c.snapshot_id = ? AND c.village_id = p.village_id
          )
        """,
        (prev_id, curr_id),
    )

    pop_curr = _scalar(
        conn,
        "SELECT COALESCE(SUM(population), 0) FROM villages WHERE snapshot_id = ?",
        (curr_id,),
    )
    pop_prev = _scalar(
        conn,
        "SELECT COALESCE(SUM(population), 0) FROM villages WHERE snapshot_id = ?",
        (prev_id,),
    )

    new_players = _scalar(
        conn,
        """
        SELECT COUNT(DISTINCT player_id) FROM villages
        WHERE snapshot_id = ? AND player_id != 0
          AND player_id NOT IN (
            SELECT player_id FROM villages WHERE snapshot_id = ?
          )
        """,
        (curr_id, prev_id),
    )
    lost_players = _scalar(
        conn,
        """
        SELECT COUNT(DISTINCT player_id) FROM villages
        WHERE snapshot_id = ? AND player_id != 0
          AND player_id NOT IN (
            SELECT player_id FROM villages WHERE snapshot_id = ?
          )
        """,
        (prev_id, curr_id),
    )

    return SnapshotDelta(
        from_id=prev_id,
        to_id=curr_id,
        new_villages=new_villages,
        removed_villages=removed_villages,
        population_change=pop_curr - pop_prev,
        new_players=new_players,
        lost_players=lost_players,
    )


def format_stats_report(stats: SnapshotStats, delta: SnapshotDelta | None = None) -> str:
    lines: list[str] = []
    lines.append(f"=== Snapshot #{stats.snapshot_id} — {stats.server_key} @ {stats.fetched_at} ===")
    lines.append(f"Villages:          {stats.villages:,}")
    lines.append(f"Active players:    {stats.players:,}")
    lines.append(f"Alliances:         {stats.alliances:,}")
    lines.append(f"Total population:  {stats.total_population:,}")
    lines.append(f"Avg pop/village:   {stats.avg_population:,.1f}")
    lines.append("Tribe distribution:")
    for tribe, n in stats.tribe_counts.items():
        lines.append(f"  - {tribe:<10} {n:,}")

    lines.append("")
    lines.append(f"Top {len(stats.top_players)} players by population:")
    for i, p in enumerate(stats.top_players, 1):
        lines.append(
            f"  {i:>2}. {p['player_name']:<24} "
            f"[{p['alliance_name'] or '-':<12}] "
            f"villages={p['villages']:<3} pop={p['population']:,}"
        )

    lines.append("")
    lines.append(f"Top {len(stats.top_alliances)} alliances by population:")
    for i, a in enumerate(stats.top_alliances, 1):
        lines.append(
            f"  {i:>2}. {a['alliance_name']:<24} "
            f"members={a['members']:<4} villages={a['villages']:<5} pop={a['population']:,}"
        )

    if delta is not None:
        lines.append("")
        lines.append(f"--- Change since snapshot #{delta.from_id} ---")
        lines.append(f"  New villages:      +{delta.new_villages:,}")
        lines.append(f"  Removed villages:  -{delta.removed_villages:,}")
        lines.append(f"  Population change: {delta.population_change:+,}")
        lines.append(f"  New players:       +{delta.new_players:,}")
        lines.append(f"  Lost players:      -{delta.lost_players:,}")

    return "\n".join(lines)


def report_for_latest(
    conn: sqlite3.Connection, server_key: str, *, top_n: int = 10
) -> str:
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return f"No snapshots stored for server '{server_key}' yet."

    stats = compute_snapshot_stats(conn, int(latest["id"]), top_n=top_n)
    prev = storage.previous_snapshot(conn, server_key, int(latest["id"]))
    delta = (
        compute_delta(conn, int(prev["id"]), int(latest["id"])) if prev else None
    )
    return format_stats_report(stats, delta)


# ---------------------------------------------------------------------------
# Rankings (current snapshot + delta vs the previous snapshot)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerRankRow:
    rank: int
    player_id: int
    player_name: str
    tribe_id: int
    tribe_name: str
    alliance_id: int
    alliance_name: str
    villages: int
    population: int
    pop_delta: int | None        # vs previous snapshot
    villages_delta: int | None
    prev_alliance_name: str | None
    is_new: bool                 # not present in previous snapshot


@dataclass(frozen=True)
class AllianceRankRow:
    rank: int
    alliance_id: int
    alliance_name: str
    members: int
    villages: int
    population: int
    pop_delta: int | None
    members_delta: int | None
    is_new: bool


def players_ranked(
    conn: sqlite3.Connection,
    server_key: str,
    *,
    top_n: int = 25,
    sort: str = "population",
) -> list[PlayerRankRow]:
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])
    prev = storage.previous_snapshot(conn, server_key, curr_id)
    prev_id = int(prev["id"]) if prev else None

    order_col = "population" if sort == "population" else "villages"

    rows = conn.execute(
        f"""
        WITH curr AS (
            SELECT player_id,
                   MAX(player_name)   AS player_name,
                   MAX(tribe_id)      AS tribe_id,
                   MAX(alliance_id)   AS alliance_id,
                   MAX(alliance_name) AS alliance_name,
                   COUNT(*)           AS villages,
                   COALESCE(SUM(population), 0) AS population
            FROM villages
            WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id
        )
        SELECT * FROM curr
        ORDER BY {order_col} DESC, villages DESC
        LIMIT ?
        """,
        (curr_id, top_n),
    ).fetchall()

    prev_map: dict[int, sqlite3.Row] = {}
    if prev_id is not None:
        for r in conn.execute(
            """
            SELECT player_id,
                   MAX(alliance_name) AS alliance_name,
                   COUNT(*)           AS villages,
                   COALESCE(SUM(population), 0) AS population
            FROM villages
            WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id
            """,
            (prev_id,),
        ):
            prev_map[int(r["player_id"])] = r

    out: list[PlayerRankRow] = []
    for i, r in enumerate(rows, 1):
        pid = int(r["player_id"])
        prev_row = prev_map.get(pid)
        tid = int(r["tribe_id"] or 0)
        out.append(
            PlayerRankRow(
                rank=i,
                player_id=pid,
                player_name=str(r["player_name"]),
                tribe_id=tid,
                tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
                alliance_id=int(r["alliance_id"] or 0),
                alliance_name=str(r["alliance_name"] or ""),
                villages=int(r["villages"]),
                population=int(r["population"]),
                pop_delta=(int(r["population"]) - int(prev_row["population"])) if prev_row else None,
                villages_delta=(int(r["villages"]) - int(prev_row["villages"])) if prev_row else None,
                prev_alliance_name=str(prev_row["alliance_name"]) if prev_row else None,
                is_new=(prev_id is not None and prev_row is None),
            )
        )
    return out


def alliances_ranked(
    conn: sqlite3.Connection,
    server_key: str,
    *,
    top_n: int = 25,
    sort: str = "population",
) -> list[AllianceRankRow]:
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])
    prev = storage.previous_snapshot(conn, server_key, curr_id)
    prev_id = int(prev["id"]) if prev else None

    order_col = "population" if sort == "population" else (
        "villages" if sort == "villages" else "members"
    )

    rows = conn.execute(
        f"""
        SELECT alliance_id,
               MAX(alliance_name)             AS alliance_name,
               COUNT(DISTINCT player_id)      AS members,
               COUNT(*)                       AS villages,
               COALESCE(SUM(population), 0)   AS population
        FROM villages
        WHERE snapshot_id = ? AND alliance_id != 0
        GROUP BY alliance_id
        ORDER BY {order_col} DESC, members DESC
        LIMIT ?
        """,
        (curr_id, top_n),
    ).fetchall()

    prev_map: dict[int, sqlite3.Row] = {}
    if prev_id is not None:
        for r in conn.execute(
            """
            SELECT alliance_id,
                   COUNT(DISTINCT player_id)    AS members,
                   COALESCE(SUM(population), 0) AS population
            FROM villages
            WHERE snapshot_id = ? AND alliance_id != 0
            GROUP BY alliance_id
            """,
            (prev_id,),
        ):
            prev_map[int(r["alliance_id"])] = r

    out: list[AllianceRankRow] = []
    for i, r in enumerate(rows, 1):
        aid = int(r["alliance_id"])
        prev_row = prev_map.get(aid)
        out.append(
            AllianceRankRow(
                rank=i,
                alliance_id=aid,
                alliance_name=str(r["alliance_name"]),
                members=int(r["members"]),
                villages=int(r["villages"]),
                population=int(r["population"]),
                pop_delta=(int(r["population"]) - int(prev_row["population"])) if prev_row else None,
                members_delta=(int(r["members"]) - int(prev_row["members"])) if prev_row else None,
                is_new=(prev_id is not None and prev_row is None),
            )
        )
    return out


# ---------------------------------------------------------------------------
# History across all snapshots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryPoint:
    snapshot_id: int
    fetched_at: str
    villages: int
    population: int
    members: int | None          # alliances only
    alliance_id: int | None      # players only — alliance at this point in time
    alliance_name: str | None    # players only


@dataclass(frozen=True)
class PlayerHistory:
    player_id: int
    player_name: str             # most recent name
    tribe_id: int
    tribe_name: str
    points: list[HistoryPoint]


@dataclass(frozen=True)
class AllianceHistory:
    alliance_id: int
    alliance_name: str
    points: list[HistoryPoint]


def find_players(
    conn: sqlite3.Connection, server_key: str, query: str, *, limit: int = 20
) -> list[tuple[int, str, str]]:
    """Find players by partial name (case-insensitive) or exact id, latest snapshot.

    Returns (player_id, player_name, tribe_name) tuples.
    """
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])

    if query.isdigit():
        rows = conn.execute(
            """
            SELECT player_id,
                   MAX(player_name) AS player_name,
                   MAX(tribe_id)    AS tribe_id
            FROM villages
            WHERE snapshot_id = ? AND player_id = ?
            GROUP BY player_id
            """,
            (curr_id, int(query)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT player_id,
                   MAX(player_name) AS player_name,
                   MAX(tribe_id)    AS tribe_id
            FROM villages
            WHERE snapshot_id = ?
              AND player_id != 0
              AND lower(player_name) LIKE ?
            GROUP BY player_id
            ORDER BY MAX(population) DESC
            LIMIT ?
            """,
            (curr_id, f"%{query.lower()}%", limit),
        ).fetchall()
    return [
        (
            int(r["player_id"]),
            str(r["player_name"]),
            TRIBE_NAMES.get(int(r["tribe_id"] or 0), f"tribe_{r['tribe_id'] or 0}"),
        )
        for r in rows
    ]


def find_alliances(
    conn: sqlite3.Connection, server_key: str, query: str, *, limit: int = 20
) -> list[tuple[int, str]]:
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])

    if query.isdigit():
        rows = conn.execute(
            """
            SELECT DISTINCT alliance_id, alliance_name
            FROM villages
            WHERE snapshot_id = ? AND alliance_id = ?
            """,
            (curr_id, int(query)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT alliance_id, MAX(alliance_name) AS alliance_name
            FROM villages
            WHERE snapshot_id = ?
              AND alliance_id != 0
              AND lower(alliance_name) LIKE ?
            GROUP BY alliance_id
            ORDER BY SUM(population) DESC
            LIMIT ?
            """,
            (curr_id, f"%{query.lower()}%", limit),
        ).fetchall()
    return [(int(r["alliance_id"]), str(r["alliance_name"])) for r in rows]


def player_history(
    conn: sqlite3.Connection, server_key: str, player_id: int
) -> PlayerHistory | None:
    rows = conn.execute(
        """
        SELECT s.id           AS snapshot_id,
               s.fetched_at   AS fetched_at,
               COUNT(*)       AS villages,
               COALESCE(SUM(v.population), 0) AS population,
               MAX(v.alliance_id)   AS alliance_id,
               MAX(v.alliance_name) AS alliance_name,
               MAX(v.player_name)   AS player_name,
               MAX(v.tribe_id)      AS tribe_id
        FROM snapshots s
        JOIN villages  v ON v.snapshot_id = s.id
        WHERE s.server_key = ? AND v.player_id = ?
        GROUP BY s.id
        ORDER BY s.fetched_at ASC, s.id ASC
        """,
        (server_key, player_id),
    ).fetchall()

    if not rows:
        return None

    points = [
        HistoryPoint(
            snapshot_id=int(r["snapshot_id"]),
            fetched_at=str(r["fetched_at"]),
            villages=int(r["villages"]),
            population=int(r["population"]),
            members=None,
            alliance_id=int(r["alliance_id"] or 0),
            alliance_name=str(r["alliance_name"] or ""),
        )
        for r in rows
    ]
    tid = int(rows[-1]["tribe_id"] or 0)
    return PlayerHistory(
        player_id=player_id,
        player_name=str(rows[-1]["player_name"]),
        tribe_id=tid,
        tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
        points=points,
    )


def alliance_history(
    conn: sqlite3.Connection, server_key: str, alliance_id: int
) -> AllianceHistory | None:
    rows = conn.execute(
        """
        SELECT s.id         AS snapshot_id,
               s.fetched_at AS fetched_at,
               COUNT(*)     AS villages,
               COUNT(DISTINCT v.player_id) AS members,
               COALESCE(SUM(v.population), 0) AS population,
               MAX(v.alliance_name) AS alliance_name
        FROM snapshots s
        JOIN villages v ON v.snapshot_id = s.id
        WHERE s.server_key = ? AND v.alliance_id = ?
        GROUP BY s.id
        ORDER BY s.fetched_at ASC, s.id ASC
        """,
        (server_key, alliance_id),
    ).fetchall()

    if not rows:
        return None

    points = [
        HistoryPoint(
            snapshot_id=int(r["snapshot_id"]),
            fetched_at=str(r["fetched_at"]),
            villages=int(r["villages"]),
            population=int(r["population"]),
            members=int(r["members"]),
            alliance_id=None,
            alliance_name=None,
        )
        for r in rows
    ]
    return AllianceHistory(
        alliance_id=alliance_id,
        alliance_name=str(rows[-1]["alliance_name"]),
        points=points,
    )


@dataclass(frozen=True)
class AllianceMemberRow:
    """One player (member) in an alliance at a single snapshot."""

    player_id: int
    player_name: str
    tribe_id: int
    tribe_name: str
    villages: int
    population: int


def alliance_members_at_snapshot(
    conn: sqlite3.Connection, snapshot_id: int, alliance_id: int
) -> list[AllianceMemberRow]:
    """Players with at least one village tagged to this alliance in ``snapshot_id``."""
    if alliance_id <= 0:
        return []
    rows = conn.execute(
        """
        SELECT player_id,
               MAX(player_name) AS player_name,
               MAX(tribe_id) AS tribe_id,
               COUNT(*) AS villages,
               COALESCE(SUM(population), 0) AS population
        FROM villages
        WHERE snapshot_id = ? AND alliance_id = ? AND player_id != 0
        GROUP BY player_id
        ORDER BY population DESC, villages DESC, player_id ASC
        """,
        (snapshot_id, alliance_id),
    ).fetchall()
    out: list[AllianceMemberRow] = []
    for r in rows:
        tid = int(r["tribe_id"] or 0)
        out.append(
            AllianceMemberRow(
                player_id=int(r["player_id"]),
                player_name=str(r["player_name"]),
                tribe_id=tid,
                tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
                villages=int(r["villages"]),
                population=int(r["population"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Events between two snapshots
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VillageEvent:
    village_id: int
    village_name: str
    x: int
    y: int
    population: int | None
    player_id: int
    player_name: str
    alliance_name: str
    # Only set for "chiefed":
    prev_player_id: int | None = None
    prev_player_name: str | None = None
    prev_alliance_name: str | None = None
    pop_change: int | None = None


@dataclass(frozen=True)
class AllianceMove:
    player_id: int
    player_name: str
    from_alliance_id: int
    from_alliance_name: str
    to_alliance_id: int
    to_alliance_name: str
    population: int


def resolve_event_pair(
    conn: sqlite3.Connection,
    server_key: str,
    *,
    from_id: int | None = None,
    to_id: int | None = None,
) -> tuple[int, int] | None:
    """Pick (prev_id, curr_id) defaulting to the latest two snapshots for a server."""
    if to_id is None:
        latest = storage.latest_snapshot(conn, server_key)
        if latest is None:
            return None
        to_id = int(latest["id"])
    if from_id is None:
        prev = storage.previous_snapshot(conn, server_key, to_id)
        if prev is None:
            return None
        from_id = int(prev["id"])
    return from_id, to_id


def new_villages(
    conn: sqlite3.Connection, prev_id: int, curr_id: int, *, limit: int | None = None
) -> list[VillageEvent]:
    sql = """
        SELECT c.village_id, c.village_name, c.x, c.y,
               c.population, c.player_id, c.player_name, c.alliance_name
        FROM villages c
        WHERE c.snapshot_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM villages p
            WHERE p.snapshot_id = ? AND p.village_id = c.village_id
          )
        ORDER BY c.population DESC, c.village_id ASC
    """
    params: tuple = (curr_id, prev_id)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)

    return [
        VillageEvent(
            village_id=int(r["village_id"]),
            village_name=str(r["village_name"]),
            x=int(r["x"]),
            y=int(r["y"]),
            population=None if r["population"] is None else int(r["population"]),
            player_id=int(r["player_id"]),
            player_name=str(r["player_name"]),
            alliance_name=str(r["alliance_name"]),
        )
        for r in conn.execute(sql, params)
    ]


def removed_villages(
    conn: sqlite3.Connection, prev_id: int, curr_id: int, *, limit: int | None = None
) -> list[VillageEvent]:
    sql = """
        SELECT p.village_id, p.village_name, p.x, p.y,
               p.population, p.player_id, p.player_name, p.alliance_name
        FROM villages p
        WHERE p.snapshot_id = ?
          AND NOT EXISTS (
            SELECT 1 FROM villages c
            WHERE c.snapshot_id = ? AND c.village_id = p.village_id
          )
        ORDER BY p.population DESC, p.village_id ASC
    """
    params: tuple = (prev_id, curr_id)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)

    return [
        VillageEvent(
            village_id=int(r["village_id"]),
            village_name=str(r["village_name"]),
            x=int(r["x"]),
            y=int(r["y"]),
            population=None if r["population"] is None else int(r["population"]),
            player_id=int(r["player_id"]),
            player_name=str(r["player_name"]),
            alliance_name=str(r["alliance_name"]),
        )
        for r in conn.execute(sql, params)
    ]


def chiefed_villages(
    conn: sqlite3.Connection, prev_id: int, curr_id: int, *, limit: int | None = None
) -> list[VillageEvent]:
    """Villages whose owner (player_id) changed between prev and curr."""
    sql = """
        SELECT c.village_id, c.village_name, c.x, c.y,
               c.population        AS curr_pop,
               p.population        AS prev_pop,
               c.player_id         AS curr_pid,
               c.player_name       AS curr_pname,
               c.alliance_name     AS curr_aname,
               p.player_id         AS prev_pid,
               p.player_name       AS prev_pname,
               p.alliance_name     AS prev_aname
        FROM villages c
        JOIN villages p
          ON p.village_id  = c.village_id
         AND p.snapshot_id = ?
        WHERE c.snapshot_id = ?
          AND c.player_id != p.player_id
        ORDER BY c.population DESC, c.village_id ASC
    """
    params: tuple = (prev_id, curr_id)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)

    out: list[VillageEvent] = []
    for r in conn.execute(sql, params):
        curr_pop = None if r["curr_pop"] is None else int(r["curr_pop"])
        prev_pop = None if r["prev_pop"] is None else int(r["prev_pop"])
        out.append(
            VillageEvent(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=curr_pop,
                player_id=int(r["curr_pid"]),
                player_name=str(r["curr_pname"]),
                alliance_name=str(r["curr_aname"]),
                prev_player_id=int(r["prev_pid"]),
                prev_player_name=str(r["prev_pname"]),
                prev_alliance_name=str(r["prev_aname"]),
                pop_change=(
                    None
                    if curr_pop is None or prev_pop is None
                    else curr_pop - prev_pop
                ),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Per-village views: history, current ranking, top movers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VillageHistoryPoint:
    snapshot_id: int
    fetched_at: str
    population: int | None
    player_id: int
    player_name: str
    alliance_name: str


@dataclass(frozen=True)
class VillageHistory:
    village_id: int
    village_name: str
    x: int
    y: int
    points: list[VillageHistoryPoint]


@dataclass(frozen=True)
class VillageRankRow:
    rank: int
    village_id: int
    village_name: str
    x: int
    y: int
    tribe_id: int
    tribe_name: str
    population: int
    pop_delta: int | None
    player_id: int
    player_name: str
    alliance_id: int
    alliance_name: str
    is_new: bool                    # not in previous snapshot
    owner_changed: bool             # village existed in prev with a different player_id
    flag_label: str = ""            # capital marker + region (from map.sql)


@dataclass(frozen=True)
class VillageMover:
    village_id: int
    village_name: str
    x: int
    y: int
    prev_population: int
    curr_population: int
    delta: int
    player_name: str
    alliance_name: str


def find_villages(
    conn: sqlite3.Connection, server_key: str, query: str, *, limit: int = 25
) -> list[tuple[int, str, str, int]]:
    """Find villages by partial name (case-insensitive) or exact id.

    Returns (village_id, village_name, player_name, population) tuples.
    """
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])

    if query.isdigit():
        rows = conn.execute(
            """
            SELECT village_id, village_name, player_name, population
            FROM villages
            WHERE snapshot_id = ? AND village_id = ?
            """,
            (curr_id, int(query)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT village_id, village_name, player_name,
                   COALESCE(population, 0) AS population
            FROM villages
            WHERE snapshot_id = ?
              AND lower(village_name) LIKE ?
            ORDER BY population DESC
            LIMIT ?
            """,
            (curr_id, f"%{query.lower()}%", limit),
        ).fetchall()
    return [
        (
            int(r["village_id"]),
            str(r["village_name"]),
            str(r["player_name"]),
            int(r["population"] or 0),
        )
        for r in rows
    ]


def village_history(
    conn: sqlite3.Connection, server_key: str, village_id: int
) -> VillageHistory | None:
    rows = conn.execute(
        """
        SELECT s.id           AS snapshot_id,
               s.fetched_at   AS fetched_at,
               v.population, v.player_id, v.player_name,
               v.alliance_name, v.village_name, v.x, v.y
        FROM snapshots s
        JOIN villages  v ON v.snapshot_id = s.id
        WHERE s.server_key = ? AND v.village_id = ?
        ORDER BY s.fetched_at ASC, s.id ASC
        """,
        (server_key, village_id),
    ).fetchall()

    if not rows:
        return None

    latest = rows[-1]
    points = [
        VillageHistoryPoint(
            snapshot_id=int(r["snapshot_id"]),
            fetched_at=str(r["fetched_at"]),
            population=None if r["population"] is None else int(r["population"]),
            player_id=int(r["player_id"]),
            player_name=str(r["player_name"]),
            alliance_name=str(r["alliance_name"] or ""),
        )
        for r in rows
    ]
    return VillageHistory(
        village_id=village_id,
        village_name=str(latest["village_name"]),
        x=int(latest["x"]),
        y=int(latest["y"]),
        points=points,
    )


def villages_ranked(
    conn: sqlite3.Connection,
    server_key: str,
    *,
    top_n: int = 25,
    player_id: int | None = None,
    sort: str = "population",
) -> list[VillageRankRow]:
    """Rank villages in the latest snapshot.

    sort='population' -> largest villages first
    sort='growth'     -> biggest gainers vs previous snapshot first
    sort='loss'       -> biggest losers vs previous snapshot first
    Optional player_id restricts to one player's villages.
    """
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    curr_id = int(latest["id"])
    prev = storage.previous_snapshot(conn, server_key, curr_id)
    prev_id = int(prev["id"]) if prev else None

    where_extra = "AND c.player_id = :pid" if player_id is not None else ""
    params: dict[str, Any] = {
        "curr": curr_id,
        "prev": prev_id if prev_id is not None else -1,
        "limit": top_n,
    }
    if player_id is not None:
        params["pid"] = player_id

    if sort == "growth":
        order_clause = "ORDER BY (COALESCE(c.population, 0) - COALESCE(p.population, 0)) DESC"
    elif sort == "loss":
        order_clause = "ORDER BY (COALESCE(c.population, 0) - COALESCE(p.population, 0)) ASC"
    else:
        order_clause = "ORDER BY c.population DESC, c.village_id ASC"

    rows = conn.execute(
        f"""
        SELECT c.village_id, c.village_name, c.x, c.y, c.tribe_id,
               COALESCE(c.population, 0) AS curr_pop,
               c.player_id, c.player_name, c.alliance_id, c.alliance_name,
               c.region, c.extra_json,
               p.population AS prev_pop,
               p.player_id  AS prev_player_id
        FROM villages c
        LEFT JOIN villages p
          ON p.village_id = c.village_id AND p.snapshot_id = :prev
        WHERE c.snapshot_id = :curr {where_extra}
        {order_clause}
        LIMIT :limit
        """,
        params,
    ).fetchall()

    out: list[VillageRankRow] = []
    has_prev = prev_id is not None
    for i, r in enumerate(rows, 1):
        curr_pop = int(r["curr_pop"])
        prev_pop = r["prev_pop"]
        delta: int | None = None
        is_new = False
        if has_prev:
            if prev_pop is None:
                is_new = True
            else:
                delta = curr_pop - int(prev_pop)
        owner_changed = bool(
            has_prev
            and r["prev_player_id"] is not None
            and int(r["prev_player_id"]) != int(r["player_id"])
        )
        tid = int(r["tribe_id"] or 0)
        fl = village_flag_label(
            None if r["region"] is None else str(r["region"]),
            r["extra_json"] if isinstance(r["extra_json"], str) else None,
        )
        out.append(
            VillageRankRow(
                rank=i,
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                tribe_id=tid,
                tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
                population=curr_pop,
                pop_delta=delta,
                player_id=int(r["player_id"]),
                player_name=str(r["player_name"]),
                alliance_id=int(r["alliance_id"] or 0),
                alliance_name=str(r["alliance_name"] or ""),
                is_new=is_new,
                owner_changed=owner_changed,
                flag_label=fl,
            )
        )
    return out


def village_movers(
    conn: sqlite3.Connection,
    prev_id: int,
    curr_id: int,
    *,
    direction: str = "grew",
    limit: int = 25,
    same_owner: bool = True,
) -> list[VillageMover]:
    """Top villages by population change between two snapshots.

    direction='grew'  -> biggest gainers
    direction='shrunk'-> biggest losers
    same_owner=True   -> exclude chiefed villages (player_id changed)
    """
    if direction not in ("grew", "shrunk"):
        raise ValueError(f"direction must be 'grew' or 'shrunk', got {direction!r}")

    order = "DESC" if direction == "grew" else "ASC"
    delta_filter = "AND (c.population - p.population) > 0" if direction == "grew" \
        else "AND (c.population - p.population) < 0"
    owner_filter = "AND c.player_id = p.player_id" if same_owner else ""

    rows = conn.execute(
        f"""
        SELECT c.village_id, c.village_name, c.x, c.y,
               COALESCE(p.population, 0) AS prev_pop,
               COALESCE(c.population, 0) AS curr_pop,
               (COALESCE(c.population, 0) - COALESCE(p.population, 0)) AS delta,
               c.player_name, c.alliance_name
        FROM villages c
        JOIN villages p
          ON p.village_id  = c.village_id
         AND p.snapshot_id = ?
        WHERE c.snapshot_id = ?
          {owner_filter}
          {delta_filter}
        ORDER BY delta {order}, curr_pop DESC
        LIMIT ?
        """,
        (prev_id, curr_id, limit),
    ).fetchall()

    return [
        VillageMover(
            village_id=int(r["village_id"]),
            village_name=str(r["village_name"]),
            x=int(r["x"]),
            y=int(r["y"]),
            prev_population=int(r["prev_pop"]),
            curr_population=int(r["curr_pop"]),
            delta=int(r["delta"]),
            player_name=str(r["player_name"]),
            alliance_name=str(r["alliance_name"] or ""),
        )
        for r in rows
    ]


def alliance_moves(
    conn: sqlite3.Connection, prev_id: int, curr_id: int, *, limit: int | None = None
) -> list[AllianceMove]:
    """Players whose alliance_id changed between prev and curr."""
    sql = """
        WITH curr AS (
            SELECT player_id,
                   MAX(player_name)   AS player_name,
                   MAX(alliance_id)   AS alliance_id,
                   MAX(alliance_name) AS alliance_name,
                   COALESCE(SUM(population), 0) AS population
            FROM villages
            WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id
        ),
        prev AS (
            SELECT player_id,
                   MAX(alliance_id)   AS alliance_id,
                   MAX(alliance_name) AS alliance_name
            FROM villages
            WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id
        )
        SELECT c.player_id, c.player_name, c.population,
               p.alliance_id   AS from_id,
               p.alliance_name AS from_name,
               c.alliance_id   AS to_id,
               c.alliance_name AS to_name
        FROM curr c
        JOIN prev p ON p.player_id = c.player_id
        WHERE c.alliance_id != p.alliance_id
        ORDER BY c.population DESC
    """
    params: tuple = (curr_id, prev_id)
    if limit is not None:
        sql += " LIMIT ?"
        params = (*params, limit)

    return [
        AllianceMove(
            player_id=int(r["player_id"]),
            player_name=str(r["player_name"]),
            from_alliance_id=int(r["from_id"] or 0),
            from_alliance_name=str(r["from_name"] or ""),
            to_alliance_id=int(r["to_id"] or 0),
            to_alliance_name=str(r["to_name"] or ""),
            population=int(r["population"]),
        )
        for r in conn.execute(sql, params)
    ]


# ---------------------------------------------------------------------------
# Per-player village ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerVillageAcquisition:
    """One row per village currently owned by a player.

    Reconstructs how / when they got the village from the snapshot history.

    Possible `status` values:
      - "settled"      village was first seen in `acquired_at` and the player
                       owned it from the start (i.e. they founded it).
      - "conquered"    in the snapshot before `acquired_at` the village
                       existed under a different owner — we record the
                       previous owner's name.
      - "pre-existing" the village existed in our very first snapshot for
                       this server already owned by this player; we have no
                       earlier observation to know how they got it.
    """

    village_id: int
    village_name: str
    x: int
    y: int
    population: int
    status: str
    from_player_id: int | None
    from_player_name: str | None
    from_alliance_name: str | None
    acquired_at: str | None  # ISO timestamp; None for pre-existing


def player_villages_with_history(
    conn: sqlite3.Connection,
    server_key: str,
    player_id: int,
) -> list[PlayerVillageAcquisition]:
    """For each village currently owned by `player_id` on `server_key`,
    reconstruct from the snapshot history whether it was settled or
    conquered (and from whom), plus the date it was acquired.
    """
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    latest_id = int(latest["id"])

    server_first_row = conn.execute(
        "SELECT MIN(fetched_at) AS f FROM snapshots WHERE server_key = ?",
        (server_key,),
    ).fetchone()
    server_first_fetched_at: str | None = (
        server_first_row["f"] if server_first_row else None
    )

    rows = conn.execute(
        """
        WITH server_snaps AS (
            SELECT id, fetched_at FROM snapshots WHERE server_key = :sk
        ),
        owned_now AS (
            SELECT village_id, village_name, x, y,
                   COALESCE(population, 0) AS population
            FROM villages
            WHERE snapshot_id = :latest AND player_id = :pid
        ),
        history AS (
            SELECT v.village_id, ss.fetched_at,
                   v.player_id, v.player_name, v.alliance_name
            FROM villages v
            JOIN server_snaps ss ON ss.id = v.snapshot_id
            WHERE v.village_id IN (SELECT village_id FROM owned_now)
        ),
        first_owned AS (
            SELECT village_id, MIN(fetched_at) AS first_fetched_at
            FROM history
            WHERE player_id = :pid
            GROUP BY village_id
        )
        SELECT
            o.village_id, o.village_name, o.x, o.y, o.population,
            fo.first_fetched_at AS acquired_at,
            (SELECT MIN(h.fetched_at) FROM history h
              WHERE h.village_id = o.village_id)                  AS first_seen_at,
            (SELECT h2.player_id     FROM history h2
              WHERE h2.village_id = o.village_id
                AND h2.fetched_at < fo.first_fetched_at
              ORDER BY h2.fetched_at DESC LIMIT 1)                AS prev_player_id,
            (SELECT h3.player_name   FROM history h3
              WHERE h3.village_id = o.village_id
                AND h3.fetched_at < fo.first_fetched_at
              ORDER BY h3.fetched_at DESC LIMIT 1)                AS prev_player_name,
            (SELECT h4.alliance_name FROM history h4
              WHERE h4.village_id = o.village_id
                AND h4.fetched_at < fo.first_fetched_at
              ORDER BY h4.fetched_at DESC LIMIT 1)                AS prev_alliance_name
        FROM owned_now o
        JOIN first_owned fo ON fo.village_id = o.village_id
        ORDER BY fo.first_fetched_at DESC, o.village_id ASC
        """,
        {"sk": server_key, "latest": latest_id, "pid": player_id},
    ).fetchall()

    out: list[PlayerVillageAcquisition] = []
    for r in rows:
        prev_pid = r["prev_player_id"]
        acquired = r["acquired_at"]

        if prev_pid is not None:
            status = "conquered"
            from_pid: int | None = int(prev_pid)
            from_pname: str | None = str(r["prev_player_name"] or "") or None
            from_aname: str | None = str(r["prev_alliance_name"] or "") or None
            acquired_out: str | None = acquired
        else:
            # No prior ownership row exists. Decide: settled vs pre-existing.
            if (
                server_first_fetched_at is not None
                and acquired is not None
                and acquired <= server_first_fetched_at
            ):
                status = "pre-existing"
                acquired_out = None
            else:
                status = "settled"
                acquired_out = acquired
            from_pid = None
            from_pname = None
            from_aname = None

        out.append(
            PlayerVillageAcquisition(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"]),
                status=status,
                from_player_id=from_pid,
                from_player_name=from_pname,
                from_alliance_name=from_aname,
                acquired_at=acquired_out,
            )
        )
    return out


@dataclass(frozen=True)
class PlayerVillageLoss:
    """A village that existed in snapshots under this player and is **not**
    theirs in the latest snapshot — i.e. they lost it (chiefed etc.) since we
    last saw them owning it (possibly after reconquering and losing again).
    """

    village_id: int
    village_name: str
    x: int
    y: int
    population: int  # village pop in latest snapshot
    to_player_id: int
    to_player_name: str | None
    to_alliance_name: str | None
    lost_at: str | None  # ISO fetched_at UTC of earliest post-ownership loss


def player_villages_lost(
    conn: sqlite3.Connection,
    server_key: str,
    player_id: int,
) -> list[PlayerVillageLoss]:
    """Villages still on the map in the latest snapshot that the player no
    longer owns but did own in at least one stored snapshot."""
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    latest_id = int(latest["id"])

    rows = conn.execute(
        """
        WITH server_snaps AS (
            SELECT id, fetched_at FROM snapshots WHERE server_key = :sk
        ),
        owned_ever AS (
            SELECT DISTINCT v.village_id
            FROM villages v
            JOIN snapshots s ON s.id = v.snapshot_id
            WHERE s.server_key = :sk AND v.player_id = :pid
        ),
        curr AS (
            SELECT *
              FROM villages
             WHERE snapshot_id = :latest
        ),
        lost_v AS (
            SELECT c.*
              FROM curr c
              JOIN owned_ever oe ON oe.village_id = c.village_id
             WHERE c.player_id <> :pid
        ),
        last_owned AS (
            SELECT v.village_id, MAX(ss.fetched_at) AS last_owned_at
              FROM villages v
              JOIN server_snaps ss ON ss.id = v.snapshot_id
             WHERE v.player_id = :pid
             GROUP BY v.village_id
        )
        SELECT
            lv.village_id,
            lv.village_name,
            lv.x,
            lv.y,
            COALESCE(lv.population, 0) AS population,
            lv.player_id AS to_player_id,
            lv.player_name AS to_player_name,
            lv.alliance_name AS to_alliance_name,
            lo.last_owned_at,
            (
                SELECT MIN(ss2.fetched_at)
                  FROM villages v2
                  JOIN server_snaps ss2 ON ss2.id = v2.snapshot_id
                 WHERE v2.village_id = lv.village_id
                   AND ss2.fetched_at > lo.last_owned_at
                   AND v2.player_id <> :pid
            ) AS lost_at
          FROM lost_v lv
          JOIN last_owned lo ON lo.village_id = lv.village_id
        ORDER BY lost_at DESC, lv.village_id ASC
        """,
        {"sk": server_key, "latest": latest_id, "pid": player_id},
    ).fetchall()

    out: list[PlayerVillageLoss] = []
    for r in rows:
        lost_raw = r["lost_at"]
        if lost_raw is None:
            continue
        to_pname_raw = r["to_player_name"]
        to_aname_raw = r["to_alliance_name"]
        out.append(
            PlayerVillageLoss(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"]),
                to_player_id=int(r["to_player_id"] or 0),
                to_player_name=(
                    None
                    if to_pname_raw is None or not str(to_pname_raw).strip()
                    else str(to_pname_raw).strip()
                ),
                to_alliance_name=(
                    None
                    if to_aname_raw is None or not str(to_aname_raw).strip()
                    else str(to_aname_raw).strip()
                ),
                lost_at=str(lost_raw),
            )
        )
    return out


@dataclass(frozen=True)
class PlayerVillageDestroyed:
    """A village the player once owned whose ``village_id`` no longer exists in the
    latest snapshot (razed/abandoned/removed row), with last-known map coordinates.
    """

    village_id: int
    village_name: str
    x: int
    y: int
    population: int  # village pop in last observation before disappearance
    last_seen_at: str | None


def player_villages_destroyed(
    conn: sqlite3.Connection,
    server_key: str,
    player_id: int,
) -> list[PlayerVillageDestroyed]:
    """Villages absent from the **latest** map snapshot but owned by ``player_id`` in some prior snapshot."""
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    latest_id = int(latest["id"])

    rows = conn.execute(
        """
        WITH owned_ever AS (
            SELECT DISTINCT v.village_id
            FROM villages v
            INNER JOIN snapshots s ON s.id = v.snapshot_id
            WHERE s.server_key = :sk AND v.player_id = :pid
        ),
        gone AS (
            SELECT oe.village_id
            FROM owned_ever oe
            WHERE NOT EXISTS (
                SELECT 1 FROM villages v2
                WHERE v2.snapshot_id = :latest
                  AND v2.village_id = oe.village_id
            )
        ),
        last_sid AS (
            SELECT v.village_id, MAX(v.snapshot_id) AS snap_max
              FROM villages v
              INNER JOIN snapshots s ON s.id = v.snapshot_id
             WHERE s.server_key = :sk
               AND v.village_id IN (SELECT village_id FROM gone)
             GROUP BY v.village_id
        )
        SELECT
            vf.village_id,
            vf.village_name,
            vf.x,
            vf.y,
            COALESCE(vf.population, 0) AS population,
            s.fetched_at AS last_seen
          FROM villages vf
          INNER JOIN last_sid ls ON ls.village_id = vf.village_id
               AND vf.snapshot_id = ls.snap_max
          INNER JOIN snapshots s ON s.id = vf.snapshot_id
         ORDER BY vf.village_id ASC
        """,
        {"sk": server_key, "latest": latest_id, "pid": player_id},
    ).fetchall()

    out: list[PlayerVillageDestroyed] = []
    for r in rows:
        raw_ts = r["last_seen"]
        out.append(
            PlayerVillageDestroyed(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"]),
                last_seen_at=None if raw_ts is None else str(raw_ts),
            )
        )
    return out


@dataclass(frozen=True)
class AllianceVillageLoss:
    """A village that was in this alliance in some snapshot but in the **latest**
    snapshot no longer has that ``alliance_id`` (still on the map).

    ``chiefed_loss``: the last snapshot where the village was still tagged this
    alliance had a **different** owner than the village's current holder — typically
    a chief/conquest rather than only the owner's alliance tag sliding off.
    """

    village_id: int
    village_name: str
    x: int
    y: int
    population: int
    to_player_id: int
    to_player_name: str | None
    to_alliance_id: int
    to_alliance_name: str | None
    lost_at: str | None
    chiefed_loss: bool = False


def alliance_villages_lost(
    conn: sqlite3.Connection,
    server_key: str,
    alliance_id: int,
) -> list[AllianceVillageLoss]:
    """Villages still on the map in the latest snapshot that are no longer in this alliance."""
    if int(alliance_id) <= 0:
        return []
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    latest_id = int(latest["id"])
    aid = int(alliance_id)

    rows = conn.execute(
        """
        WITH server_snaps AS (
            SELECT id, fetched_at FROM snapshots WHERE server_key = :sk
        ),
        allied_ever AS (
            SELECT DISTINCT v.village_id
            FROM villages v
            JOIN snapshots s ON s.id = v.snapshot_id
            WHERE s.server_key = :sk AND v.alliance_id = :aid
        ),
        curr AS (
            SELECT *
              FROM villages
             WHERE snapshot_id = :latest
        ),
        lost_v AS (
            SELECT c.*
              FROM curr c
              JOIN allied_ever ae ON ae.village_id = c.village_id
             WHERE c.alliance_id <> :aid
        ),
        last_allied AS (
            SELECT v.village_id, MAX(ss.fetched_at) AS last_allied_at
              FROM villages v
              JOIN server_snaps ss ON ss.id = v.snapshot_id
             WHERE v.alliance_id = :aid
             GROUP BY v.village_id
        )
        SELECT
            lv.village_id,
            lv.village_name,
            lv.x,
            lv.y,
            COALESCE(lv.population, 0) AS population,
            lv.player_id AS to_player_id,
            lv.player_name AS to_player_name,
            COALESCE(lv.alliance_id, 0) AS to_alliance_id,
            lv.alliance_name AS to_alliance_name,
            la.last_allied_at,
            (
                SELECT MIN(ss2.fetched_at)
                  FROM villages v2
                  JOIN server_snaps ss2 ON ss2.id = v2.snapshot_id
                 WHERE v2.village_id = lv.village_id
                   AND ss2.fetched_at > la.last_allied_at
                   AND v2.alliance_id <> :aid
            ) AS lost_at,
            (
                SELECT v3.player_id
                  FROM villages v3
                  JOIN server_snaps ss3 ON ss3.id = v3.snapshot_id
                 WHERE v3.village_id = lv.village_id
                   AND v3.alliance_id = :aid
                 ORDER BY ss3.fetched_at DESC
                 LIMIT 1
            ) AS last_allied_owner_id
          FROM lost_v lv
          JOIN last_allied la ON la.village_id = lv.village_id
        ORDER BY lost_at DESC, lv.village_id ASC
        """,
        {"sk": server_key, "latest": latest_id, "aid": aid},
    ).fetchall()

    out: list[AllianceVillageLoss] = []
    for r in rows:
        lost_raw = r["lost_at"]
        if lost_raw is None:
            continue
        to_pname_raw = r["to_player_name"]
        to_aname_raw = r["to_alliance_name"]
        to_pid = int(r["to_player_id"] or 0)
        prev_raw = r["last_allied_owner_id"]
        prev_pid = None if prev_raw is None else int(prev_raw)
        chiefed = prev_pid is not None and prev_pid != to_pid
        out.append(
            AllianceVillageLoss(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"]),
                to_player_id=to_pid,
                to_player_name=(
                    None
                    if to_pname_raw is None or not str(to_pname_raw).strip()
                    else str(to_pname_raw).strip()
                ),
                to_alliance_id=int(r["to_alliance_id"] or 0),
                to_alliance_name=(
                    None
                    if to_aname_raw is None or not str(to_aname_raw).strip()
                    else str(to_aname_raw).strip()
                ),
                lost_at=str(lost_raw),
                chiefed_loss=chiefed,
            )
        )
    return out


def alliance_villages_destroyed(
    conn: sqlite3.Connection,
    server_key: str,
    alliance_id: int,
) -> list[PlayerVillageDestroyed]:
    """Villages ever tagged with this ``alliance_id`` but absent from the latest snapshot."""
    if int(alliance_id) <= 0:
        return []
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    latest_id = int(latest["id"])
    aid = int(alliance_id)

    rows = conn.execute(
        """
        WITH allied_ever AS (
            SELECT DISTINCT v.village_id
            FROM villages v
            INNER JOIN snapshots s ON s.id = v.snapshot_id
            WHERE s.server_key = :sk AND v.alliance_id = :aid
        ),
        gone AS (
            SELECT ae.village_id
            FROM allied_ever ae
            WHERE NOT EXISTS (
                SELECT 1 FROM villages v2
                WHERE v2.snapshot_id = :latest
                  AND v2.village_id = ae.village_id
            )
        ),
        last_sid AS (
            SELECT v.village_id, MAX(v.snapshot_id) AS snap_max
              FROM villages v
              INNER JOIN snapshots s ON s.id = v.snapshot_id
             WHERE s.server_key = :sk
               AND v.village_id IN (SELECT village_id FROM gone)
             GROUP BY v.village_id
        )
        SELECT
            vf.village_id,
            vf.village_name,
            vf.x,
            vf.y,
            COALESCE(vf.population, 0) AS population,
            s.fetched_at AS last_seen
          FROM villages vf
          INNER JOIN last_sid ls ON ls.village_id = vf.village_id
               AND vf.snapshot_id = ls.snap_max
          INNER JOIN snapshots s ON s.id = vf.snapshot_id
         ORDER BY vf.village_id ASC
        """,
        {"sk": server_key, "latest": latest_id, "aid": aid},
    ).fetchall()

    out: list[PlayerVillageDestroyed] = []
    for r in rows:
        raw_ts = r["last_seen"]
        out.append(
            PlayerVillageDestroyed(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"]),
                last_seen_at=None if raw_ts is None else str(raw_ts),
            )
        )
    return out


@dataclass(frozen=True)
class InactiveNearRow:
    """Village in the latest snapshot: flat population, inside radius."""

    village_id: int
    village_name: str
    x: int
    y: int
    population: int
    player_id: int
    player_name: str
    alliance_id: int
    alliance_name: str
    tribe_name: str
    snapshots_seen: int
    distance_tiles: float
    player_total_pop: int = 0


def inactive_villages_near(
    conn: sqlite3.Connection,
    server_key: str,
    center_x: int,
    center_y: int,
    *,
    radius_min: int = 0,
    radius_max: int = 30,
    min_snapshots: int = 2,
    exclude_npc: bool = True,
    limit: int | None = None,
    player_total_pop_min: int = 0,
    player_total_pop_max: int = 0,
    flat_mode: str = "latest_pair",
) -> list[InactiveNearRow]:
    """Villages that (1) exist in the latest snapshot, (2) lie within the
    Euclidean tile ring ``radius_min`` … ``radius_max`` of ``(center_x, center_y)``
    (inclusive), and (3) match an inactive population rule:

    - ``latest_pair`` (default): population unchanged between the **latest two**
      snapshots and village present in both (works well with daily fetches).
    - ``all_history``: population never changed across **all** stored snapshots
      (needs at least ``min_snapshots`` observations).

    ``player_total_pop_min`` / ``player_total_pop_max`` (``<= 0`` disables that bound)
    filter by the owner's **total** population in the latest snapshot.

    This is a practical proxy for “inactive” accounts — not login activity.
    """
    radius_min = max(0, int(radius_min))
    radius_max = int(radius_max)
    if radius_max <= 0 or radius_min > radius_max:
        return []
    if min_snapshots < 2:
        min_snapshots = 2

    mode = str(flat_mode or "latest_pair").strip().lower()
    if mode not in ("latest_pair", "all_history"):
        raise ValueError(f"flat_mode must be 'latest_pair' or 'all_history', got {flat_mode!r}")

    latest = storage.latest_snapshot(conn, server_key)
    if latest is None:
        return []
    if mode == "latest_pair":
        prev = storage.previous_snapshot(conn, server_key, int(latest["id"]))
        if prev is None:
            return []

    min_rsq = radius_min * radius_min
    max_rsq = radius_max * radius_max
    npc_sql = ""
    if exclude_npc:
        npc_sql = "AND v.player_id != 0 AND v.tribe_id NOT IN (4, 5)"

    if mode == "latest_pair":
        flat_join = """
        INNER JOIN (
            SELECT l.village_id
            FROM villages l
            INNER JOIN latest lat ON l.snapshot_id = lat.sid
            INNER JOIN prev_snap ps ON 1 = 1
            INNER JOIN villages prv
                ON prv.village_id = l.village_id AND prv.snapshot_id = ps.sid
            WHERE l.population = prv.population
        ) flat ON flat.village_id = v.village_id
        INNER JOIN (
            SELECT v2.village_id,
                   COUNT(DISTINCT v2.snapshot_id) AS n_obs
            FROM villages v2
            INNER JOIN snapshots s2 ON s2.id = v2.snapshot_id AND s2.server_key = :sk
            GROUP BY v2.village_id
        ) obs ON obs.village_id = v.village_id AND obs.n_obs >= :min_snaps
        """
        obs_col = "obs.n_obs"
    else:
        flat_join = """
        INNER JOIN (
            SELECT v.village_id,
                   COUNT(DISTINCT v.snapshot_id) AS n_obs,
                   MIN(COALESCE(v.population, 0)) AS pmin,
                   MAX(COALESCE(v.population, 0)) AS pmax
            FROM villages v
            INNER JOIN snapshots s ON s.id = v.snapshot_id AND s.server_key = :sk
            GROUP BY v.village_id
            HAVING n_obs >= :min_snaps AND pmin = pmax
        ) ps ON ps.village_id = v.village_id
        """
        obs_col = "ps.n_obs"

    sql = f"""
        WITH latest AS (
            SELECT id AS sid FROM snapshots
            WHERE server_key = :sk
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
        ),
        prev_snap AS (
            SELECT id AS sid FROM snapshots
            WHERE server_key = :sk
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1 OFFSET 1
        ),
        player_totals AS (
            SELECT vq.player_id AS pid, SUM(COALESCE(vq.population, 0)) AS ptot
            FROM villages vq
            INNER JOIN latest lq ON vq.snapshot_id = lq.sid
            GROUP BY vq.player_id
        )
        SELECT v.village_id, v.village_name, v.x, v.y, v.population,
               v.player_id, v.player_name, v.alliance_id, v.alliance_name, v.tribe_id,
               {obs_col} AS snapshots_seen,
               COALESCE(pt.ptot, 0) AS player_total_pop,
               (v.x - :cx) * (v.x - :cx) + (v.y - :cy) * (v.y - :cy) AS dist_sq
        FROM villages v
        CROSS JOIN latest l
        {flat_join}
        LEFT JOIN player_totals pt ON pt.pid = v.player_id
        WHERE v.snapshot_id = l.sid
          AND (v.x - :cx2) * (v.x - :cx2) + (v.y - :cy2) * (v.y - :cy2) >= :min_rsq
          AND (v.x - :cx2) * (v.x - :cx2) + (v.y - :cy2) * (v.y - :cy2) <= :max_rsq
          {npc_sql}
          AND (:ppp_min <= 0 OR COALESCE(pt.ptot, 0) >= :ppp_min)
          AND (:ppp_max <= 0 OR COALESCE(pt.ptot, 0) <= :ppp_max)
        ORDER BY dist_sq ASC, v.village_id ASC
    """
    params: dict[str, Any] = {
        "sk": server_key,
        "min_snaps": min_snapshots,
        "cx": center_x,
        "cy": center_y,
        "cx2": center_x,
        "cy2": center_y,
        "min_rsq": min_rsq,
        "max_rsq": max_rsq,
        "ppp_min": int(player_total_pop_min),
        "ppp_max": int(player_total_pop_max),
    }
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    if limit is not None and limit > 0:
        rows = rows[:limit]

    out: list[InactiveNearRow] = []
    for r in rows:
        tid = int(r["tribe_id"])
        dist_sq = float(r["dist_sq"])
        out.append(
            InactiveNearRow(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"] or 0),
                player_id=int(r["player_id"]),
                player_name=str(r["player_name"]),
                alliance_id=int(r["alliance_id"] or 0),
                alliance_name=str(r["alliance_name"] or ""),
                tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
                snapshots_seen=int(r["snapshots_seen"]),
                distance_tiles=math.sqrt(dist_sq),
                player_total_pop=int(r["player_total_pop"] or 0),
            )
        )
    return out


@dataclass(frozen=True)
class NpcNearRow:
    """One village row for **Natars** or **Nature** tribe searches (latest snapshot)."""

    village_id: int
    village_name: str
    x: int
    y: int
    population: int
    tribe_id: int
    tribe_name: str
    player_id: int
    player_name: str
    alliance_id: int
    alliance_name: str
    distance_tiles: float


def tribe_village_counts_latest(
    conn: sqlite3.Connection,
    server_key: str,
) -> dict[int, int]:
    """Villages per ``tribe_id`` in the server's latest snapshot only."""
    cur = conn.execute(
        """
        WITH latest AS (
            SELECT id AS sid FROM snapshots
            WHERE server_key = ?
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
        )
        SELECT v.tribe_id AS tid, COUNT(*) AS n
        FROM villages v
        INNER JOIN latest l ON v.snapshot_id = l.sid
        GROUP BY v.tribe_id
        """,
        (server_key,),
    )
    return {int(r["tid"]): int(r["n"]) for r in cur.fetchall()}


def npc_targets_near(
    conn: sqlite3.Connection,
    server_key: str,
    center_x: int,
    center_y: int,
    *,
    radius: int,
    whole_world: bool = False,
    tribe_ids: list[int],
    village_pop_min: int = -1,
    village_pop_max: int = -1,
    limit: int | None = None,
) -> list[NpcNearRow]:
    """Tiles in ``tribe_ids`` for the latest snapshot (optional spatial radius).

    When ``whole_world`` is False, tiles must lie within Euclidean ``radius`` of
    ``(center_x, center_y)``. When True, **all** matching tribes on the map are
    returned and ``radius`` is ignored for filtering.

    ``distance_tiles`` in each row is always the Euclidean distance from
    ``(center_x, center_y)``.

    Travian Legends ``map.sql`` stores **Nature (tribe 4)** oasis rows only when the export includes them,
    while **Natars (tribe 5)** NPC villages normally **are** present. The dashboard exposes each tribe in
    its own tab (**Nature** vs **Natars**) but this query merely filters ``tribe_id IN (...)``.

    Tribe **4 Nature** rows are **normally not exported** for many servers — Nature tab may legitimately stay empty.

    Tribe **5 Natars** and any extra ``tribe_id`` lists you pass (if ever needed) apply the same filtering.
    """
    use_radius = not whole_world
    if use_radius and radius <= 0:
        return []
    uniq = sorted({int(t) for t in tribe_ids if int(t) >= 0})
    if not uniq:
        return []

    ks = ",".join(f":t{i}" for i in range(len(uniq)))
    params: dict[str, Any] = {
        "sk": server_key,
        "cx": center_x,
        "cy": center_y,
        "vp_lo": int(village_pop_min),
        "vp_hi": int(village_pop_max),
    }
    if use_radius:
        params["cx2"] = center_x
        params["cy2"] = center_y
        params["rsq"] = radius * radius

    spatial = ""
    if use_radius:
        spatial = """
          AND (v.x - :cx2) * (v.x - :cx2) + (v.y - :cy2) * (v.y - :cy2) <= :rsq"""
    order_by = (
        "dist_sq ASC, v.village_id ASC"
        if use_radius
        else "v.tribe_id ASC, v.y ASC, v.x ASC, v.village_id ASC"
    )
    for i, ti in enumerate(uniq):
        params[f"t{i}"] = ti

    sql = f"""
        WITH latest AS (
            SELECT id AS sid FROM snapshots
            WHERE server_key = :sk
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
        )
        SELECT v.village_id, v.village_name, v.x, v.y, COALESCE(v.population, 0) AS population,
               v.player_id, v.player_name, v.alliance_id, v.alliance_name, v.tribe_id,
               (v.x - :cx) * (v.x - :cx) + (v.y - :cy) * (v.y - :cy) AS dist_sq
        FROM villages v
        INNER JOIN latest l ON v.snapshot_id = l.sid
        WHERE v.tribe_id IN ({ks}){spatial}
          AND (:vp_lo < 0 OR COALESCE(v.population, 0) >= :vp_lo)
          AND (:vp_hi < 0 OR COALESCE(v.population, 0) <= :vp_hi)
        ORDER BY {order_by}
    """
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    if limit is not None and limit > 0:
        rows = rows[:limit]

    out: list[NpcNearRow] = []
    for r in rows:
        tid = int(r["tribe_id"])
        dist_sq = float(r["dist_sq"])
        out.append(
            NpcNearRow(
                village_id=int(r["village_id"]),
                village_name=str(r["village_name"]),
                x=int(r["x"]),
                y=int(r["y"]),
                population=int(r["population"] or 0),
                tribe_id=tid,
                tribe_name=TRIBE_NAMES.get(tid, f"tribe_{tid}"),
                player_id=int(r["player_id"]),
                player_name=str(r["player_name"]),
                alliance_id=int(r["alliance_id"] or 0),
                alliance_name=str(r["alliance_name"] or ""),
                distance_tiles=math.sqrt(dist_sq),
            )
        )
    return out
