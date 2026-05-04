"""SQLite-backed persistent storage for snapshots + village rows."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .parser import VillageRow

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("statistics.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    server_key   TEXT    NOT NULL,
    fetched_at   TEXT    NOT NULL,           -- ISO 8601 UTC
    source_url   TEXT    NOT NULL,
    raw_path     TEXT,
    byte_size    INTEGER NOT NULL,
    sha256       TEXT    NOT NULL,
    row_count    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (server_key, sha256)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_server_time
    ON snapshots (server_key, fetched_at DESC);

CREATE TABLE IF NOT EXISTS villages (
    snapshot_id    INTEGER NOT NULL,
    village_id     INTEGER NOT NULL,
    x              INTEGER NOT NULL,
    y              INTEGER NOT NULL,
    tribe_id       INTEGER NOT NULL,
    vid            INTEGER NOT NULL,
    village_name   TEXT    NOT NULL,
    player_id      INTEGER NOT NULL,
    player_name    TEXT    NOT NULL,
    alliance_id    INTEGER NOT NULL,
    alliance_name  TEXT    NOT NULL,
    population     INTEGER,
    region         TEXT,
    extra_json     TEXT,
    PRIMARY KEY (snapshot_id, village_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_villages_player
    ON villages (snapshot_id, player_id);

CREATE INDEX IF NOT EXISTS idx_villages_alliance
    ON villages (snapshot_id, alliance_id);

CREATE INDEX IF NOT EXISTS idx_villages_coords
    ON villages (snapshot_id, x, y);

CREATE INDEX IF NOT EXISTS idx_villages_tribe
    ON villages (snapshot_id, tribe_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    log.debug("Initialized database at %s", db_path)


@contextmanager
def open_db(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    init_db(db_path)
    conn = _connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def find_snapshot_by_hash(
    conn: sqlite3.Connection, server_key: str, sha256: str
) -> sqlite3.Row | None:
    cur = conn.execute(
        "SELECT * FROM snapshots WHERE server_key = ? AND sha256 = ?",
        (server_key, sha256),
    )
    return cur.fetchone()


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    server_key: str,
    fetched_at: datetime,
    source_url: str,
    raw_path: Path | None,
    byte_size: int,
    sha256: str,
    rows: Iterable[VillageRow],
) -> tuple[int, int]:
    """Insert a snapshot + its village rows. Returns (snapshot_id, row_count).

    If an identical snapshot (same sha256) already exists for this server,
    returns its id with row_count=0 to indicate "no new work done".
    """
    existing = find_snapshot_by_hash(conn, server_key, sha256)
    if existing is not None:
        log.info(
            "Snapshot already stored (id=%s, %s); skipping insert",
            existing["id"],
            existing["fetched_at"],
        )
        return int(existing["id"]), 0

    rows_list = list(rows)

    cur = conn.execute(
        """
        INSERT INTO snapshots (server_key, fetched_at, source_url, raw_path, byte_size, sha256, row_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            server_key,
            fetched_at.isoformat(),
            source_url,
            str(raw_path) if raw_path else None,
            byte_size,
            sha256,
            len(rows_list),
        ),
    )
    snapshot_id = int(cur.lastrowid)

    conn.executemany(
        """
        INSERT OR REPLACE INTO villages (
            snapshot_id, village_id, x, y, tribe_id, vid, village_name,
            player_id, player_name, alliance_id, alliance_name,
            population, region, extra_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (
                snapshot_id,
                r.village_id,
                r.x,
                r.y,
                r.tribe_id,
                r.vid,
                r.village_name,
                r.player_id,
                r.player_name,
                r.alliance_id,
                r.alliance_name,
                r.population,
                r.region,
                json.dumps(r.extra, ensure_ascii=False) if r.extra else None,
            )
            for r in rows_list
        ),
    )

    conn.commit()
    log.info(
        "Stored snapshot %s for %s (%d rows)", snapshot_id, server_key, len(rows_list)
    )
    return snapshot_id, len(rows_list)


def latest_snapshot(
    conn: sqlite3.Connection, server_key: str
) -> sqlite3.Row | None:
    cur = conn.execute(
        """
        SELECT * FROM snapshots
        WHERE server_key = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT 1
        """,
        (server_key,),
    )
    return cur.fetchone()


def previous_snapshot(
    conn: sqlite3.Connection, server_key: str, before_id: int
) -> sqlite3.Row | None:
    cur = conn.execute(
        """
        SELECT * FROM snapshots
        WHERE server_key = ? AND id < ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (server_key, before_id),
    )
    return cur.fetchone()


def list_snapshots(
    conn: sqlite3.Connection, server_key: str | None = None, limit: int = 20
) -> list[sqlite3.Row]:
    if server_key:
        cur = conn.execute(
            """
            SELECT * FROM snapshots WHERE server_key = ?
            ORDER BY fetched_at DESC, id DESC LIMIT ?
            """,
            (server_key, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM snapshots ORDER BY fetched_at DESC, id DESC LIMIT ?",
            (limit,),
        )
    return list(cur.fetchall())
