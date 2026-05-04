"""Smoke-test the per-player village ledger by cloning the latest real snapshot
into a synthetic future snapshot, mutating it (new village + chiefed village),
and rendering the ledger for both involved players. Cleans up at the end.

Run from the project root:

    python scripts/smoke_ledger.py
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Allow `python scripts/smoke_ledger.py` from project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import analyzer, storage, view  # noqa: E402

DB = Path("statistics.db")


def main() -> int:
    with storage.open_db(DB) as conn:
        latest = conn.execute(
            """
            SELECT id, server_key, fetched_at, source_url, byte_size, sha256, row_count
            FROM snapshots ORDER BY fetched_at DESC, id DESC LIMIT 1
            """
        ).fetchone()
        if latest is None:
            print("No snapshots stored. Run `python main.py fetch` first.")
            return 1

        server_key = latest["server_key"]
        prev_id = int(latest["id"])
        synthetic_dt = datetime.now(timezone.utc) + timedelta(days=1)
        synthetic_iso = synthetic_dt.isoformat()

        print(f"Cloning snapshot #{prev_id} as a synthetic future snapshot...")
        cur = conn.execute(
            """
            INSERT INTO snapshots
                (server_key, fetched_at, source_url, raw_path,
                 byte_size, sha256, row_count)
            VALUES (?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                server_key,
                synthetic_iso,
                str(latest["source_url"]),
                int(latest["byte_size"]),
                "smoke_ledger_" + synthetic_iso,
                int(latest["row_count"]),
            ),
        )
        new_id = int(cur.lastrowid)

        conn.execute(
            """
            INSERT INTO villages (
                snapshot_id, village_id, x, y, tribe_id, vid, village_name,
                player_id, player_name, alliance_id, alliance_name,
                population, region, extra_json
            )
            SELECT ?, village_id, x, y, tribe_id, vid, village_name,
                   player_id, player_name, alliance_id, alliance_name,
                   population, region, extra_json
            FROM villages WHERE snapshot_id = ?
            """,
            (new_id, prev_id),
        )

        # ------------------------------------------------------------------
        # Pick two real players: a "settler" and a "conqueror"
        # ------------------------------------------------------------------
        settler = conn.execute(
            """
            SELECT player_id, MAX(player_name) AS player_name,
                   MAX(tribe_id) AS tribe_id, MAX(alliance_id) AS alliance_id,
                   MAX(alliance_name) AS alliance_name
            FROM villages WHERE snapshot_id = ? AND player_id != 0
            GROUP BY player_id ORDER BY MAX(population) DESC LIMIT 1 OFFSET 0
            """,
            (new_id,),
        ).fetchone()

        # Pick a different player to play "conqueror"
        conqueror = conn.execute(
            """
            SELECT player_id, MAX(player_name) AS player_name,
                   MAX(tribe_id) AS tribe_id, MAX(alliance_id) AS alliance_id,
                   MAX(alliance_name) AS alliance_name
            FROM villages WHERE snapshot_id = ? AND player_id != 0
              AND player_id != ?
            GROUP BY player_id ORDER BY MAX(population) DESC LIMIT 1 OFFSET 1
            """,
            (new_id, int(settler["player_id"])),
        ).fetchone()

        # Pick a victim — a real existing village owned by someone OTHER than
        # the conqueror. Avoid synthetic ids (>= 99000000).
        victim = conn.execute(
            """
            SELECT village_id, village_name, x, y, player_id, player_name
            FROM villages WHERE snapshot_id = ?
              AND player_id NOT IN (?, 0)
              AND village_id < 99000000
            ORDER BY population DESC LIMIT 1 OFFSET 5
            """,
            (new_id, int(conqueror["player_id"])),
        ).fetchone()

        synthetic_vid = 99_900_001
        print(
            f"  settler:   {settler['player_name']} (id={settler['player_id']})"
        )
        print(
            f"  conqueror: {conqueror['player_name']} (id={conqueror['player_id']})"
        )
        print(
            f"  victim village: {victim['village_name']} "
            f"(id={victim['village_id']}) — owned by {victim['player_name']}"
        )

        # 1) Settled: brand new village owned by `settler`
        conn.execute(
            """
            INSERT INTO villages (
                snapshot_id, village_id, x, y, tribe_id, vid, village_name,
                player_id, player_name, alliance_id, alliance_name,
                population, region, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                new_id,
                synthetic_vid,
                500, 500,
                int(settler["tribe_id"] or 1),
                synthetic_vid,
                "[smoke] Brand New Capital",
                int(settler["player_id"]),
                str(settler["player_name"]),
                int(settler["alliance_id"] or 0),
                str(settler["alliance_name"] or ""),
                123,
            ),
        )

        # 2) Conquered: re-assign `victim` village to `conqueror` in the
        # synthetic snapshot
        conn.execute(
            """
            UPDATE villages
               SET player_id     = ?,
                   player_name   = ?,
                   alliance_id   = ?,
                   alliance_name = ?
             WHERE snapshot_id = ? AND village_id = ?
            """,
            (
                int(conqueror["player_id"]),
                str(conqueror["player_name"]),
                int(conqueror["alliance_id"] or 0),
                str(conqueror["alliance_name"] or ""),
                new_id,
                int(victim["village_id"]),
            ),
        )

        conn.commit()

        try:
            print()
            print("=== ledger for the SETTLER (expect 1 settled, rest pre-existing) ===")
            ledger_s = analyzer.player_villages_with_history(
                conn, server_key, int(settler["player_id"])
            )
            view.render_player_village_ledger(
                ledger_s,
                player_name=str(settler["player_name"]),
                server_key=server_key,
            )

            print()
            print("=== ledger for the CONQUEROR (expect 1 conquered, rest pre-existing) ===")
            ledger_c = analyzer.player_villages_with_history(
                conn, server_key, int(conqueror["player_id"])
            )
            view.render_player_village_ledger(
                ledger_c,
                player_name=str(conqueror["player_name"]),
                server_key=server_key,
            )
        finally:
            print()
            print("Cleaning up synthetic snapshot...")
            conn.execute("DELETE FROM villages  WHERE snapshot_id = ?", (new_id,))
            conn.execute("DELETE FROM snapshots WHERE id          = ?", (new_id,))
            conn.commit()
            print("done.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
