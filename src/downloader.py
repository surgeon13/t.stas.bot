"""Download map.sql files from Travian servers."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import ServerConfig, Settings

log = logging.getLogger(__name__)

SNAPSHOTS_DIR = Path("data") / "snapshots"


@dataclass(frozen=True)
class DownloadResult:
    server_key: str
    url: str
    fetched_at: datetime
    byte_size: int
    sha256: str
    content: bytes


def _ensure_snapshot_dir(server_key: str) -> Path:
    target = SNAPSHOTS_DIR / server_key
    target.mkdir(parents=True, exist_ok=True)
    return target


def _snapshot_filename(server_key: str, fetched_at: datetime) -> str:
    ts = fetched_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{server_key}__{ts}.map.sql"


def download_map_sql(server: ServerConfig, settings: Settings) -> DownloadResult:
    """Fetch map.sql from a single server, with retries. Returns content in memory."""
    url = server.map_sql_url
    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/plain, application/sql, */*;q=0.5",
    }

    last_err: Exception | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            log.info("Downloading %s (attempt %d/%d)", url, attempt, settings.max_retries)
            resp = requests.get(url, headers=headers, timeout=settings.request_timeout)
            resp.raise_for_status()
            content = resp.content
            break
        except requests.RequestException as e:
            last_err = e
            backoff = min(30, 2 ** attempt)
            log.warning("Download failed (%s); retrying in %ds", e, backoff)
            time.sleep(backoff)
    else:
        raise RuntimeError(f"Failed to download {url} after {settings.max_retries} attempts") from last_err

    fetched_at = datetime.now(timezone.utc)
    sha = hashlib.sha256(content).hexdigest()

    return DownloadResult(
        server_key=server.key,
        url=url,
        fetched_at=fetched_at,
        byte_size=len(content),
        sha256=sha,
        content=content,
    )


def save_raw_snapshot(result: DownloadResult) -> Path:
    """Write the downloaded content to data/snapshots/<server_key>/."""
    target_dir = _ensure_snapshot_dir(result.server_key)
    raw_path = target_dir / _snapshot_filename(result.server_key, result.fetched_at)
    raw_path.write_bytes(result.content)
    log.info("Saved raw snapshot: %s (%d bytes)", raw_path, result.byte_size)
    return raw_path
