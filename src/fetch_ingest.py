"""Download map.sql for one or more servers and insert snapshots into SQLite."""

from __future__ import annotations

import logging
from pathlib import Path

from . import downloader, parser, sched_terminal, storage
from .config import AppConfig, ServerConfig

log = logging.getLogger(__name__)


def fetch_one_server(cfg: AppConfig, server: ServerConfig, db_path: Path) -> int:
    """Download + parse + store one server. Returns snapshot id, or ``0`` if duplicate."""
    result = downloader.download_map_sql(server, cfg.settings)

    with storage.open_db(db_path) as conn:
        existing = storage.find_snapshot_by_hash(conn, server.key, result.sha256)
        if existing is not None:
            msg = (
                f"[{server.key}] no change (sha256 matches existing snapshot id={existing['id']})"
            )
            print(msg)
            log.info(msg)
            return 0

        raw_path = (
            downloader.save_raw_snapshot(result)
            if cfg.settings.keep_raw_snapshots
            else None
        )
        rows = parser.parse_map_sql(result.content)

        snapshot_id, inserted = storage.insert_snapshot(
            conn,
            server_key=server.key,
            fetched_at=result.fetched_at,
            source_url=result.url,
            raw_path=raw_path,
            byte_size=result.byte_size,
            sha256=result.sha256,
            rows=rows,
        )

        sched_terminal.print_new_snapshot_success(
            server_key=server.key,
            snapshot_id=int(snapshot_id),
            village_rows=int(inserted),
            byte_size=int(result.byte_size),
            when_iso=result.fetched_at.isoformat(),
        )

        msg = (
            f"[{server.key}] stored snapshot id={snapshot_id} "
            f"({inserted} villages, {result.byte_size:,} bytes)"
        )
        log.info(msg)
        return int(snapshot_id)


def fetch_all_enabled_servers(cfg: AppConfig, db_path: Path) -> None:
    """Fetch every enabled server; log failures and continue."""
    for s in cfg.enabled_servers():
        try:
            fetch_one_server(cfg, s, db_path)
        except Exception:
            log.exception("Fetch failed for server %s", s.key)
