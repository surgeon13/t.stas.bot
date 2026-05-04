"""One-shot smoke test for event queries.

Creates a synthetic snapshot derived from snapshot 1 with deliberate mutations:
- 2 removed villages (top-population ones from snap 1)
- 2 new villages (synthetic high-pop entries)
- 1 chiefed village (owner changed to another existing player)
- 1 alliance move (a player's alliance_id swapped to a different one)
- 3 grown villages (population +N, same owner)
- 3 shrunk villages (population -N, same owner)

Run from project root:

    python scripts/smoke_events.py europe31x3

Cleans up the synthetic snapshot after printing the events report.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import analyzer, storage, view  # noqa: E402

SERVER_KEY = sys.argv[1] if len(sys.argv) > 1 else "europe31x3"


def main() -> int:
    db_path = Path("statistics.db")
    if not db_path.exists():
        print("statistics.db missing; run a fetch first.")
        return 1

    with storage.open_db(db_path) as conn:
        latest = storage.latest_snapshot(conn, SERVER_KEY)
        if latest is None:
            print(f"No snapshots for {SERVER_KEY}.")
            return 1

        prev_id = int(latest["id"])

        cur = conn.execute(
            """
            INSERT INTO snapshots (server_key, fetched_at, source_url, raw_path,
                                   byte_size, sha256, row_count)
            VALUES (?, ?, '(synthetic)', NULL, 0, ?, 0)
            """,
            (
                SERVER_KEY,
                datetime.now(timezone.utc).isoformat(),
                f"synthetic-{prev_id}-{datetime.now(timezone.utc).timestamp()}",
            ),
        )
        new_id = int(cur.lastrowid)

        conn.execute(
            """
            INSERT INTO villages (snapshot_id, village_id, x, y, tribe_id, vid,
                                  village_name, player_id, player_name,
                                  alliance_id, alliance_name, population, region, extra_json)
            SELECT ?, village_id, x, y, tribe_id, vid, village_name, player_id,
                   player_name, alliance_id, alliance_name, population, region, extra_json
            FROM villages WHERE snapshot_id = ?
            """,
            (new_id, prev_id),
        )

        # 1) Drop 2 villages (will appear as "removed" 1->2)
        conn.execute(
            """
            DELETE FROM villages
            WHERE snapshot_id = ?
              AND village_id IN (
                SELECT village_id FROM villages
                WHERE snapshot_id = ?
                ORDER BY population DESC LIMIT 2
              )
            """,
            (new_id, new_id),
        )

        # 2) Insert 2 brand-new villages
        donor = conn.execute(
            "SELECT player_id, player_name, alliance_id, alliance_name, tribe_id "
            "FROM villages WHERE snapshot_id = ? AND alliance_id != 0 "
            "ORDER BY population DESC LIMIT 1",
            (new_id,),
        ).fetchone()
        if donor:
            for off, name in enumerate(("Synth-A", "Synth-B")):
                fake_vid = 99_000_000 + off
                conn.execute(
                    """
                    INSERT INTO villages (snapshot_id, village_id, x, y, tribe_id, vid,
                                          village_name, player_id, player_name,
                                          alliance_id, alliance_name, population)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id, fake_vid, 50 + off, -50 - off,
                        donor["tribe_id"], fake_vid, name,
                        donor["player_id"], donor["player_name"],
                        donor["alliance_id"], donor["alliance_name"],
                        500 + off * 50,
                    ),
                )

        # 3) Chief 1 village: pick a village and re-assign to a different existing player
        target = conn.execute(
            """
            SELECT village_id, population FROM villages
            WHERE snapshot_id = ? AND population > 100 AND alliance_id != 0
              AND village_id < 99000000   -- exclude synthetic new villages
            ORDER BY population ASC LIMIT 1 OFFSET 5
            """,
            (new_id,),
        ).fetchone()
        replacement = conn.execute(
            """
            SELECT player_id, player_name, alliance_id, alliance_name
            FROM villages WHERE snapshot_id = ? AND alliance_id != 0
            ORDER BY population DESC LIMIT 1
            """,
            (new_id,),
        ).fetchone()
        if target and replacement:
            conn.execute(
                """
                UPDATE villages
                SET player_id = ?, player_name = ?, alliance_id = ?, alliance_name = ?,
                    population = ?
                WHERE snapshot_id = ? AND village_id = ?
                """,
                (
                    replacement["player_id"], replacement["player_name"],
                    replacement["alliance_id"], replacement["alliance_name"],
                    int(target["population"]) - 50,
                    new_id, target["village_id"],
                ),
            )

        # 4) Alliance move: pick one player; switch all their villages to a different alliance
        mover = conn.execute(
            """
            SELECT player_id, player_name, alliance_id FROM villages
            WHERE snapshot_id = ? AND alliance_id != 0
            GROUP BY player_id
            ORDER BY SUM(population) DESC
            LIMIT 1 OFFSET 5
            """,
            (new_id,),
        ).fetchone()
        new_ally = conn.execute(
            """
            SELECT alliance_id, MAX(alliance_name) AS alliance_name
            FROM villages WHERE snapshot_id = ? AND alliance_id != ?
            GROUP BY alliance_id
            ORDER BY SUM(population) DESC LIMIT 1
            """,
            (new_id, mover["alliance_id"] if mover else 0),
        ).fetchone()
        if mover and new_ally:
            conn.execute(
                """
                UPDATE villages SET alliance_id = ?, alliance_name = ?
                WHERE snapshot_id = ? AND player_id = ?
                """,
                (
                    new_ally["alliance_id"], new_ally["alliance_name"],
                    new_id, mover["player_id"],
                ),
            )

        # 5) Grow 3 villages by +200/300/400 (same owner)
        for offset, bonus in enumerate((200, 300, 400)):
            conn.execute(
                """
                UPDATE villages SET population = COALESCE(population, 0) + ?
                WHERE snapshot_id = ?
                  AND village_id = (
                    SELECT village_id FROM villages
                    WHERE snapshot_id = ? AND population BETWEEN 200 AND 800
                      AND alliance_id != 0 AND village_id < 99000000
                    ORDER BY village_id LIMIT 1 OFFSET ?
                  )
                """,
                (bonus, new_id, new_id, offset),
            )

        # 6) Shrink 3 villages by 200/300/400
        for offset, loss in enumerate((200, 300, 400)):
            conn.execute(
                """
                UPDATE villages
                SET population = MAX(0, COALESCE(population, 0) - ?)
                WHERE snapshot_id = ?
                  AND village_id = (
                    SELECT village_id FROM villages
                    WHERE snapshot_id = ? AND population BETWEEN 200 AND 800
                      AND alliance_id != 0 AND village_id < 99000000
                    ORDER BY village_id DESC LIMIT 1 OFFSET ?
                  )
                """,
                (loss, new_id, new_id, offset),
            )

        conn.commit()

        try:
            view.render_event_period(server_key=SERVER_KEY, prev_id=prev_id, curr_id=new_id)
            view.render_new_villages(analyzer.new_villages(conn, prev_id, new_id))
            view.render_removed_villages(analyzer.removed_villages(conn, prev_id, new_id))
            view.render_chiefed_villages(analyzer.chiefed_villages(conn, prev_id, new_id))
            view.render_alliance_moves(analyzer.alliance_moves(conn, prev_id, new_id))
            view.render_village_movers(
                analyzer.village_movers(conn, prev_id, new_id, direction="grew", limit=10),
                direction="grew",
            )
            view.render_village_movers(
                analyzer.village_movers(conn, prev_id, new_id, direction="shrunk", limit=10),
                direction="shrunk",
            )
        finally:
            conn.execute("DELETE FROM villages WHERE snapshot_id = ?", (new_id,))
            conn.execute("DELETE FROM snapshots WHERE id = ?", (new_id,))
            conn.commit()
            print(f"\n[clean] removed synthetic snapshot id={new_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
