"""User-defined map presets for the dashboard (center, zoom, highlight)."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

DEFAULT_CUSTOM_MAPS_PATH = Path("config") / "custom_maps.yaml"

_VALID_MODES = frozenset({"everyone", "player", "alliance", "tribe", "multi"})


@dataclass
class CustomMapPreset:
    """One saved custom map view."""

    id: str
    name: str
    center_x: int
    center_y: int
    view_radius: int  # half-side of square viewport (tiles); 0 = full world
    highlight_mode: str  # everyone | player | alliance | tribe | multi
    player_id: int = 0  # legacy single id (still written for YAML compat)
    alliance_id: int = 0
    tribe_name: str = ""
    player_ids: list[int] = field(default_factory=list)
    alliance_ids: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.highlight_mode not in _VALID_MODES:
            self.highlight_mode = "everyone"
        # Migrate legacy singular ids into lists when lists were empty (YAML older format)
        if self.highlight_mode == "player":
            if not self.player_ids and int(self.player_id) > 0:
                self.player_ids = [int(self.player_id)]
        if self.highlight_mode == "alliance":
            if not self.alliance_ids and int(self.alliance_id) > 0:
                self.alliance_ids = [int(self.alliance_id)]


def _slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "map"


def new_preset_id(name: str) -> str:
    return f"{_slug(name)}-{uuid.uuid4().hex[:8]}"


def resolve_highlight_village_ids(
    idx: pd.DataFrame, preset: CustomMapPreset
) -> frozenset[int]:
    """Village ids to highlight for this preset (latest snapshot index)."""
    layers = resolve_highlight_layers(idx, preset)
    if not layers:
        return frozenset()
    out: set[int] = set()
    for vid_set, _ in layers:
        out |= set(vid_set)
    return frozenset(out)


def resolve_highlight_layers(
    idx: pd.DataFrame, preset: CustomMapPreset
) -> list[tuple[frozenset[int], str]]:
    """Highlight layers: each (village_ids, legend label). Assigned in order alliances → players."""
    if idx.empty:
        return []
    mode = preset.highlight_mode
    if mode == "everyone":
        return []

    if mode == "tribe":
        tn = (preset.tribe_name or "").strip()
        if not tn:
            return []
        m = idx[idx["tribe_name"] == tn]
        if m.empty:
            return []
        return [(frozenset(m["village_id"].astype(int).tolist()), f"Tribe «{tn}»")]

    alliance_ids: list[int] = []
    player_ids: list[int] = []

    if mode == "multi":
        alliance_ids = sorted({int(x) for x in preset.alliance_ids if int(x) > 0})
        player_ids = sorted({int(x) for x in preset.player_ids if int(x) > 0})
    elif mode == "alliance":
        if preset.alliance_ids:
            alliance_ids = sorted({int(x) for x in preset.alliance_ids if int(x) > 0})
        elif int(preset.alliance_id) > 0:
            alliance_ids = [int(preset.alliance_id)]
    elif mode == "player":
        if preset.player_ids:
            player_ids = sorted({int(x) for x in preset.player_ids if int(x) > 0})
        elif int(preset.player_id) > 0:
            player_ids = [int(preset.player_id)]

    if mode == "alliance" and not alliance_ids:
        return []
    if mode == "player" and not player_ids:
        return []
    # multi with both empty → no overlays (neutral map framing only)

    remaining = set(int(v) for v in idx["village_id"].tolist())
    layers: list[tuple[frozenset[int], str]] = []

    for aid in alliance_ids:
        sub = idx.loc[idx["alliance_id"] == int(aid)]
        if sub.empty:
            continue
        an = str(sub["alliance_name"].iloc[0]) if len(sub) else ""
        take = frozenset(int(v) for v in sub["village_id"].tolist() if int(v) in remaining)
        if not take:
            continue
        lbl = f"Alliance «{an}» (#{aid})" if an else f"Alliance #{aid}"
        layers.append((take, lbl))
        remaining -= set(take)

    for pid in player_ids:
        sub = idx.loc[idx["player_id"] == int(pid)]
        if sub.empty:
            continue
        pn = str(sub["player_name"].iloc[0]) if len(sub) else ""
        take = frozenset(int(v) for v in sub["village_id"].tolist() if int(v) in remaining)
        if not take:
            continue
        lbl = f"Player «{pn}» (#{pid})" if pn else f"Player #{pid}"
        layers.append((take, lbl))
        remaining -= set(take)

    return layers


def load_custom_maps(path: str | Path | None = None) -> list[CustomMapPreset]:
    p = Path(path) if path else DEFAULT_CUSTOM_MAPS_PATH
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    items = raw.get("presets") or []
    out: list[CustomMapPreset] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            hm = str(it.get("highlight_mode", "everyone")).strip().lower()
            if hm not in _VALID_MODES:
                hm = "everyone"
            _pids_raw = it.get("player_ids")
            _pids = (
                [int(x) for x in _pids_raw if int(x) > 0]
                if isinstance(_pids_raw, list)
                else []
            )
            _aids_raw = it.get("alliance_ids")
            _aids = (
                [int(x) for x in _aids_raw if int(x) > 0]
                if isinstance(_aids_raw, list)
                else []
            )
            out.append(
                CustomMapPreset(
                    id=str(it["id"]).strip(),
                    name=str(it.get("name", it["id"])).strip(),
                    center_x=int(it.get("center_x", 0)),
                    center_y=int(it.get("center_y", 0)),
                    view_radius=max(0, int(it.get("view_radius", 0))),
                    highlight_mode=hm,
                    player_id=int(it.get("player_id", 0) or 0),
                    alliance_id=int(it.get("alliance_id", 0) or 0),
                    tribe_name=str(it.get("tribe_name", "") or ""),
                    player_ids=_pids,
                    alliance_ids=_aids,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save_custom_maps(
    presets: list[CustomMapPreset], path: str | Path | None = None
) -> None:
    p = Path(path) if path else DEFAULT_CUSTOM_MAPS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"presets": [asdict(x) for x in presets]}
    p.write_text(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False), encoding="utf-8")
