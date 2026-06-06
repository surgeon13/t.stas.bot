"""Load and validate the unified servers + app settings JSON file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, MutableMapping, Sequence
from urllib.parse import urlencode

DEFAULT_CONFIG_PATH = Path("config") / "servers.json"


def _normalize_follow_entry(x: Any, *, label: str) -> int | str:
    if isinstance(x, int):
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        if not s:
            raise ValueError(f"{label}: empty string in follow list")
        if s.isdigit():
            return int(s)
        return s
    raise ValueError(f"{label}: expected int or str, got {type(x).__name__}")


def _parse_follow_list(raw: Any, *, field_name: str) -> tuple[int | str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(
            f"{field_name} must be an array ([] in JSON); use empty array if none"
        )
    return tuple(_normalize_follow_entry(x, label=field_name) for x in raw)


@dataclass(frozen=True)
class ServerConfig:
    key: str
    name: str
    base_url: str
    enabled: bool = True
    tags: tuple[str, ...] = ()

    @property
    def map_sql_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/map.sql"

    def travian_tile_url(self, x: int, y: int) -> str:
        """Travian: Legends map tile URL (same coords as map.sql / statistics)."""
        qs = urlencode({"x": str(int(x)), "y": str(int(y))})
        return f"{self.base_url.rstrip('/')}/position_details.php?{qs}"


@dataclass(frozen=True)
class Settings:
    schedule: str = "daily@00:01"  # daily@HH:MM | every@6h | every@30m
    request_timeout: int = 60
    max_retries: int = 3
    user_agent: str = "t.statistics.stas.bot/0.1"
    keep_raw_snapshots: bool = True
    inactive_search_radius: int = 30
    inactive_min_snapshots: int = 2
    inactive_exclude_npc: bool = True
    dashboard_follow_players: tuple[int | str, ...] = field(default_factory=tuple)
    dashboard_follow_alliances: tuple[int | str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AppConfig:
    servers: tuple[ServerConfig, ...]
    settings: Settings = field(default_factory=Settings)

    def enabled_servers(self) -> tuple[ServerConfig, ...]:
        return tuple(s for s in self.servers if s.enabled)

    def get_server(self, key: str) -> ServerConfig | None:
        for s in self.servers:
            if s.key == key:
                return s
        return None


def _parse_server(raw: dict[str, Any]) -> ServerConfig:
    missing = [f for f in ("key", "name", "base_url") if f not in raw]
    if missing:
        raise ValueError(f"Server entry missing required fields: {missing} in {raw!r}")

    return ServerConfig(
        key=str(raw["key"]).strip(),
        name=str(raw["name"]).strip(),
        base_url=str(raw["base_url"]).strip(),
        enabled=bool(raw.get("enabled", True)),
        tags=tuple(str(t) for t in (raw.get("tags") or ())),
    )


def _parse_settings(raw: dict[str, Any] | None) -> Settings:
    raw = raw or {}
    defaults = Settings()
    schedule = str(raw.get("schedule", defaults.schedule))
    from .scheduler import parse_schedule_spec

    parse_schedule_spec(schedule)
    return Settings(
        schedule=schedule,
        request_timeout=int(raw.get("request_timeout", defaults.request_timeout)),
        max_retries=int(raw.get("max_retries", defaults.max_retries)),
        user_agent=str(raw.get("user_agent", defaults.user_agent)),
        keep_raw_snapshots=bool(raw.get("keep_raw_snapshots", defaults.keep_raw_snapshots)),
        inactive_search_radius=int(
            raw.get("inactive_search_radius", defaults.inactive_search_radius)
        ),
        inactive_min_snapshots=int(
            raw.get("inactive_min_snapshots", defaults.inactive_min_snapshots)
        ),
        inactive_exclude_npc=bool(
            raw.get("inactive_exclude_npc", defaults.inactive_exclude_npc)
        ),
        dashboard_follow_players=_parse_follow_list(
            raw.get("dashboard_follow_players"),
            field_name="dashboard_follow_players",
        ),
        dashboard_follow_alliances=_parse_follow_list(
            raw.get("dashboard_follow_alliances"),
            field_name="dashboard_follow_alliances",
        ),
    )


def dump_server_public_dict(s: ServerConfig) -> dict[str, Any]:
    """JSON-serializable server record."""
    return {
        "key": s.key,
        "name": s.name,
        "base_url": s.base_url,
        "enabled": s.enabled,
        "tags": list(s.tags),
    }


def settings_to_plain_dict(settings: Settings) -> dict[str, Any]:
    """Round-trip ``settings`` for JSON edits (omit empty follow lists entirely)."""
    d: dict[str, Any] = {
        "schedule": settings.schedule,
        "request_timeout": settings.request_timeout,
        "max_retries": settings.max_retries,
        "user_agent": settings.user_agent,
        "keep_raw_snapshots": settings.keep_raw_snapshots,
        "inactive_search_radius": settings.inactive_search_radius,
        "inactive_min_snapshots": settings.inactive_min_snapshots,
        "inactive_exclude_npc": settings.inactive_exclude_npc,
    }
    if settings.dashboard_follow_players:
        d["dashboard_follow_players"] = list(settings.dashboard_follow_players)
    if settings.dashboard_follow_alliances:
        d["dashboard_follow_alliances"] = list(settings.dashboard_follow_alliances)
    return d


def _validate_servers_list(
    servers_raw: Any, *, cfg_label: Path | str
) -> tuple[ServerConfig, ...]:
    if not isinstance(servers_raw, list) or not servers_raw:
        raise ValueError(
            f"{cfg_label}: \"servers\" must be a non-empty array. "
            "Add worlds in JSON or run: python main.py add-server ..."
        )

    servers = tuple(_parse_server(s) for s in servers_raw)

    keys = [s.key for s in servers]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{cfg_label}: duplicate server keys found: {keys}")

    return servers


def append_server(
    *,
    config_path: Path,
    key: str,
    name: str,
    base_url: str,
    tags: Sequence[str],
    enabled: bool = True,
    dry_run: bool = False,
) -> tuple[Path, str]:
    """Append one server to ``config_path`` (.json). Returns ``(path, body)``.

    Writes unless ``dry_run``. Creates a new file with default ``settings`` when missing.
    """
    config_path = Path(config_path)
    if config_path.suffix.lower() != ".json":
        raise ValueError(
            f"app config must be a .json file; got {config_path} "
            f"(defaults to {DEFAULT_CONFIG_PATH})"
        )

    entry = {
        "key": key.strip(),
        "name": name.strip(),
        "base_url": base_url.strip(),
        "enabled": bool(enabled),
        "tags": [str(t).strip() for t in tags if str(t).strip()],
    }
    missing = [f for f in ("key", "name", "base_url") if not entry[f]]
    if missing:
        raise ValueError(f"add-server: required fields empty: {missing}")

    outer: MutableMapping[str, Any]
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            parsed = json.load(f)
        if parsed is None or not isinstance(parsed, dict):
            raise ValueError(f"{config_path}: root must be a JSON object")
        outer = dict(parsed)
        raw_list = outer.get("servers")
        if raw_list is None:
            outer["servers"] = []
            raw_list = outer["servers"]
        if not isinstance(raw_list, list):
            raise ValueError(f'{config_path}: "servers" must be an array')
        st = outer.get("settings")
        if st is None:
            outer["settings"] = {}
        elif not isinstance(st, dict):
            raise ValueError(f'{config_path}: "settings" must be an object')
    else:
        outer = {"servers": [], "settings": settings_to_plain_dict(Settings())}
        raw_list = outer["servers"]

    existing_keys: set[str] = set()
    for s in raw_list:
        if not isinstance(s, dict):
            raise ValueError(f'{config_path}: each "servers" item must be an object')
        try:
            existing_keys.add(_parse_server(s).key)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{config_path}: invalid server entry {s!r}") from e

    if entry["key"] in existing_keys:
        raise ValueError(f"server key already exists in {config_path}: {entry['key']!r}")

    raw_list.append(entry)

    outer["servers"] = raw_list

    body = json.dumps(outer, indent=2, ensure_ascii=False) + "\n"
    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(body, encoding="utf-8")
    return config_path, body


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    if cfg_path.suffix.lower() != ".json":
        raise ValueError(f"Unsupported config extension (use .json): {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path}: root must be a JSON object")

    servers = _validate_servers_list(raw.get("servers"), cfg_label=cfg_path)
    settings = _parse_settings(raw.get("settings"))
    return AppConfig(servers=servers, settings=settings)
