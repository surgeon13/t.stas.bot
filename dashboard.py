"""Streamlit dashboard.

Run with:

    python -m streamlit run dashboard.py

Reads the same ``statistics.db`` produced by ``python main.py fetch``.

Optional — run fetches inside the Streamlit **process** (background thread). **Enabled by default**;
set **`T_STATS_EMBED_SCHEDULER=0`** before `streamlit run` only if you do **not** want this process
to fetch (e.g. you run **`python main.py run`** elsewhere instead — never both).

    set T_STATS_EMBED_SCHEDULER=0       # Windows — disable embedded fetch only
    $env:T_STATS_EMBED_SCHEDULER="0"   # PowerShell

Ad hoc stdin schedules (same commands as ``python main.py run``) are off by default
inside Streamlit unless you set ``T_STATS_EMBED_SCHED_STDIN=1`` (stdin is shared).

Uses ``settings.schedule`` in ``config/servers.json``. If embedded fetch stays off,
run ``python main.py run`` in another terminal (**same DB**) instead — do not run both.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path


def _require_streamlit_runtime() -> None:
    """Bail out with a helpful message if the user runs `python dashboard.py`
    directly instead of `streamlit run dashboard.py`.

    Without Streamlit's runner, every `st.*` call emits a 'missing
    ScriptRunContext' warning and nothing is actually served.
    """
    try:
        from streamlit.runtime import exists as _runtime_exists
    except Exception:
        return
    if not _runtime_exists():
        print(
            "\nThis file is a Streamlit app — it must be launched through "
            "Streamlit's runner, not as a plain Python script.\n\n"
            "Run it instead with:\n\n"
            "    python -m streamlit run dashboard.py\n\n"
            "Streamlit will then print a Local URL (e.g. http://localhost:8501)\n"
            "that you can open in your browser.\n",
            file=sys.stderr,
        )
        raise SystemExit(2)


_require_streamlit_runtime()


import html
import altair as alt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from urllib.parse import urlencode

# Altair is still used for line charts; lift its default 5k row guard so any
# stray scatter doesn't blow up either.
alt.data_transformers.disable_max_rows()

import src  # noqa: F401  (forces utf-8 stdio)
from src import analyzer, storage
from src.config import AppConfig, ServerConfig, load_config
from src.embed_scheduler import (
    embedded_scheduler_enabled,
    embedded_scheduler_last_fetch_at,
    embedded_scheduler_last_fetch_error,
    embedded_scheduler_started,
    start_embedded_fetch_scheduler,
)
from src.fetch_ingest import fetch_all_enabled_servers
from src.custom_maps import (
    CustomMapPreset,
    load_custom_maps,
    new_preset_id,
    resolve_highlight_layers,
    resolve_highlight_village_ids,
    save_custom_maps,
)
from src.chart_renderers import render_bar_chart as _render_chart_bar
from src.chart_renderers import render_line_chart as _render_chart_line
from src.ui_settings import (
    LIGHT_DASH_APP_THEMES,
    MAP_PALETTES,
    UISettings,
    VALID_CHART_BACKENDS,
    VALID_CHART_COLORS,
    VALID_CHART_SIZES,
    VALID_SHELL_APPEARANCE,
    VALID_OVERVIEW_BAR_KINDS,
    ChartSizePreset,
    build_dashboard_shell_css,
    chart_graph_colorway,
    effective_shell_theme_slug,
    get_dash_app_theme,
    get_palette,
    load_ui_settings,
    resolve_chart_preset,
    save_ui_settings,
)

# ---------------------------------------------------------------------------
# Paths + optional embedded fetch scheduler (same as ``python main.py run``).
# ---------------------------------------------------------------------------

DB_PATH = Path(os.environ.get("T_STATS_DB", "statistics.db"))
SCHEDULER_CONFIG_PATH = Path(os.environ.get("T_STATS_CONFIG", "config/servers.json"))
start_embedded_fetch_scheduler(config_path=SCHEDULER_CONFIG_PATH, db_path=DB_PATH)


# ---------------------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="t.statistics.stas.bot",
    page_icon=":bar_chart:",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Cached data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=30)
def load_app_config() -> AppConfig:
    return load_config(SCHEDULER_CONFIG_PATH)


@st.cache_resource
def get_conn(db_path: str) -> sqlite3.Connection:
    storage.init_db(Path(db_path))
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=30)
def list_snapshots(server_key: str) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    df = pd.read_sql_query(
        """
        SELECT id, server_key, fetched_at, byte_size, row_count, sha256
        FROM snapshots WHERE server_key = ?
        ORDER BY fetched_at DESC, id DESC
        """,
        conn,
        params=(server_key,),
    )
    return df


@st.cache_data(ttl=30)
def server_history_summary(server_key: str) -> pd.DataFrame:
    """Aggregate per-snapshot totals for the server."""
    conn = get_conn(str(DB_PATH))
    df = pd.read_sql_query(
        """
        SELECT s.id                         AS snapshot_id,
               s.fetched_at                 AS fetched_at,
               COUNT(v.village_id)          AS villages,
               COUNT(DISTINCT CASE WHEN v.player_id   != 0 THEN v.player_id   END) AS players,
               COUNT(DISTINCT CASE WHEN v.alliance_id != 0 THEN v.alliance_id END) AS alliances,
               COALESCE(SUM(v.population), 0) AS population
        FROM snapshots s
        LEFT JOIN villages v ON v.snapshot_id = s.id
        WHERE s.server_key = ?
        GROUP BY s.id
        ORDER BY s.fetched_at ASC, s.id ASC
        """,
        conn,
        params=(server_key,),
    )
    if not df.empty:
        df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    return df


_RANK_DELTA_COLS = frozenset({"pop_delta", "villages_delta", "members_delta"})


def _coerce_rank_delta_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure delta columns are numeric (pandas may infer ``object`` from ``None``)."""
    if df.empty:
        return df
    out = df.copy()
    for col in _RANK_DELTA_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


@st.cache_data(ttl=30)
def players_dataframe(server_key: str) -> pd.DataFrame:
    """All players in the latest snapshot, with delta vs. previous snapshot."""
    conn = get_conn(str(DB_PATH))
    rows = analyzer.players_ranked(conn, server_key, top_n=1_000_000)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df = df.rename(columns={"rank": "#"})
    return _coerce_rank_delta_dtypes(df)


@st.cache_data(ttl=30)
def alliances_dataframe(server_key: str) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.alliances_ranked(conn, server_key, top_n=1_000_000)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df = df.rename(columns={"rank": "#"})
    return _coerce_rank_delta_dtypes(df)


@st.cache_data(ttl=30)
def villages_dataframe(server_key: str, *, player_id: int | None = None) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.villages_ranked(conn, server_key, top_n=1_000_000, player_id=player_id)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df = df.rename(columns={"rank": "#"})
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return _coerce_rank_delta_dtypes(df)


@st.cache_data(ttl=30)
def villages_top_by_growth(server_key: str, *, limit: int = 20) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.villages_ranked(
        conn, server_key, top_n=limit, sort="growth"
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["coords"] = df.apply(
        lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1
    )
    return _coerce_rank_delta_dtypes(df)


@st.cache_data(ttl=30)
def villages_top_by_loss(server_key: str, *, limit: int = 20) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.villages_ranked(conn, server_key, top_n=limit, sort="loss")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["coords"] = df.apply(
        lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1
    )
    return _coerce_rank_delta_dtypes(df)


@st.cache_data(ttl=60)
def tribe_counts_latest_snapshot(server_key: str) -> dict[int, int]:
    """Village counts by ``tribe_id`` in latest snapshot (Natars / Nature tabs & diagnostics)."""
    conn = get_conn(str(DB_PATH))
    return analyzer.tribe_village_counts_latest(conn, server_key)


def _dashboard_warn_missing_nature_tiles(thumb: dict[int, int]) -> None:
    """Travian Legends map.sql usually has no tribe-4 oasis rows."""
    if int(thumb.get(4, 0)) != 0:
        return
    st.info(
        "Your latest snapshot contains **no Nature (tribe 4)** villages. Travian Legends **`map.sql`** "
        "typically lists **Natars** as **tribe 5** in `x_world`, but usually **omits** wild oasis / Nature "
        "as **tribe 4** rows, so ingestion has nothing to list here — normal for many worlds, not a search bug.\n\n"
        "Each **`x_world`** row is **`(village_id, x, y, tribe_id, …)`** — `tribe_id` is the integer right "
        "after coordinates.\n\n"
        "**Oasis** in a village name is often a **regular player village**, not a wilderness Nature tile. "
        "If **Overview → tribe distribution** shows **Nature: 0**, this tab cannot return matches."
    )


def _render_special_tribe_village_search(
    *,
    server: ServerConfig,
    cfg: AppConfig,
    snapshots_df: pd.DataFrame,
    tribe_id: int,
    tab_subheader: str,
    count_metric_label: str,
    session_state_key: str,
    ui_key_prefix: str,
    csv_slug: str,
    map_highlight_label: str,
    after_count_metrics: Callable[[dict[int, int]], None] | None = None,
) -> None:
    """Radius or whole-world search for villages of a fixed ``tribe_id`` (Nature 4 / Natars 5)."""
    st.subheader(f"{tab_subheader} — {server.name}")
    if snapshots_df.empty:
        st.warning("No snapshots yet — fetch map.sql first.")
        return
    thumb = tribe_counts_latest_snapshot(server.key)
    st.metric(count_metric_label, f"{int(thumb.get(int(tribe_id), 0)):,}")
    if after_count_metrics is not None:
        after_count_metrics(thumb)
    st.info(
        "**Entire map** lists every stored village matching this tribe only. "
        "**Within radius** filters by Euclidean distance from the reference coords "
        "(still reflected in **dist** columns). "
        "Use **Overview · tribe distribution** to see tribe mix in your latest fetch."
    )
    scope_opts = {"entire": "Entire map", "radius": "Within radius"}
    npc_scope_key = st.radio(
        "Search scope",
        options=("entire", "radius"),
        format_func=lambda k: scope_opts[k],
        horizontal=True,
        key=f"{ui_key_prefix}_scope",
    )
    whole_world = npc_scope_key == "entire"
    oc1, oc2, oc3 = st.columns(3)
    ocx = oc1.number_input(
        "Reference center **x** (for distance column)",
        value=0,
        step=1,
        key=f"{ui_key_prefix}_cx",
    )
    ocy = oc2.number_input(
        "Reference center **y**",
        value=0,
        step=1,
        key=f"{ui_key_prefix}_cy",
    )
    orad = oc3.number_input(
        "Radius (tiles)",
        min_value=1,
        max_value=600,
        value=min(int(cfg.settings.inactive_search_radius), 600),
        step=1,
        key=f"{ui_key_prefix}_rad",
        disabled=whole_world,
        help="Only used when **Within radius** is selected.",
    )
    of1, of2 = st.columns(2)
    o_vp_lo = of1.number_input(
        "Min population",
        min_value=-1,
        value=-1,
        step=50,
        key=f"{ui_key_prefix}_pop_lo",
        help="**-1** = no minimum.",
    )
    o_vp_hi = of2.number_input(
        "Max population",
        min_value=-1,
        value=-1,
        step=50,
        key=f"{ui_key_prefix}_pop_hi",
        help="**-1** = no maximum.",
    )
    npc_row_lim = st.number_input(
        "Max rows returned",
        min_value=1,
        max_value=100000,
        value=20000,
        step=500,
        key=f"{ui_key_prefix}_row_limit",
        help="Raises DB work for very large worlds — increase only if needed.",
    )

    if st.button("Search", type="primary", key=f"{ui_key_prefix}_search_btn"):
        _ovl, _ovh = int(o_vp_lo), int(o_vp_hi)
        if _ovl >= 0 and _ovh >= 0 and _ovl > _ovh:
            st.warning("Max population must be ≥ min.")
        else:
            conn = get_conn(str(DB_PATH))
            nf = analyzer.npc_targets_near(
                conn,
                server.key,
                int(ocx),
                int(ocy),
                radius=int(orad),
                whole_world=whole_world,
                tribe_ids=[int(tribe_id)],
                village_pop_min=_ovl,
                village_pop_max=_ovh,
                limit=int(npc_row_lim),
            )
            st.session_state[session_state_key] = {
                "rows": [asdict(r) for r in nf],
                "cx": int(ocx),
                "cy": int(ocy),
                "rad": 0 if whole_world else int(orad),
                "whole_world": bool(whole_world),
                "limit_used": int(npc_row_lim),
                "hit_cap": len(nf) >= int(npc_row_lim) and int(npc_row_lim) > 0,
            }

    nlast = st.session_state.get(session_state_key)
    if nlast and nlast.get("rows") is not None:
        st.metric("Matches", len(nlast["rows"]))
        df_n = pd.DataFrame(nlast["rows"])
        if not df_n.empty:
            _tc = df_n.groupby("tribe_id").size().to_dict()
            _bits = []
            for _tid in sorted(_tc.keys()):
                _tn = analyzer.TRIBE_NAMES.get(int(_tid), str(_tid))
                _bits.append(f"{_tn}: **{_tc[_tid]:,}**")
            st.caption(" · ".join(_bits))
            if nlast.get("hit_cap"):
                st.warning(
                    f"Returned **{len(df_n):,}** rows (= **Max rows**). Raise the cap and search "
                    "again if you suspect more matches."
                )
            snap_npc = int(snapshots_df.iloc[0]["id"])
            idx_npc = _map_index(server.key, snap_npc)
            _whole_m = bool(nlast.get("whole_world", False))
            _nr = int(nlast.get("rad") or 0)
            _vp_npc: tuple[int, int, int] | None = None
            if not _whole_m and _nr > 0:
                _vp_npc = (int(nlast["cx"]), int(nlast["cy"]), _nr)
            st.markdown("##### Map (same rows as CSV & table)")
            st.caption(
                f"**{len(df_n):,}** villages highlighted"
                + (" — viewport shows **full map**." if _whole_m else "")
            )
            render_world_map(
                server_key=server.key,
                snapshot_id=snap_npc,
                idx=idx_npc,
                hl_village_ids=frozenset(int(v) for v in df_n["village_id"].tolist()),
                highlight_label=map_highlight_label,
                palette_key=str(st.session_state["dash_map_palette"]),
                plotly_key=(
                    f"{csv_slug}_map_{server.key}_{snap_npc}_"
                    f"w{int(_whole_m)}_{nlast['cx']}_{nlast['cy']}_{_nr}_{len(df_n)}"
                ),
                viewport=_vp_npc,
                plot_height=_dash_chart_sizes().full_map,
            )
            _npc_exp = df_n[
                [
                    "village_id",
                    "village_name",
                    "x",
                    "y",
                    "population",
                    "tribe_id",
                    "tribe_name",
                    "player_id",
                    "player_name",
                    "alliance_id",
                    "alliance_name",
                    "distance_tiles",
                ]
            ].copy()
            _ncsv = _npc_exp.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV — all matches",
                data=_ncsv,
                file_name=f"{csv_slug}_{server.key}_snap{snap_npc}_{len(df_n)}.csv",
                mime="text/csv",
                key=f"{csv_slug}_csv_{server.key}",
            )
            df_n = _apply_coords_game_links(df_n.copy(), server.base_url)
            n_show = df_n.rename(columns={"distance_tiles": "dist"})
            n_show["village"] = _village_name_link_series(
                n_show["village_name"], n_show["village_id"], server.key
            )
            n_show = n_show.drop(columns=["village_name"])
            n_show["player"] = _player_name_link_series(
                n_show["player_name"], n_show["player_id"], server.key
            )
            n_show["alliance"] = _alliance_name_link_series(
                n_show["alliance_name"], n_show["alliance_id"], server.key
            )
            n_show = n_show.drop(
                columns=["player_id", "player_name", "alliance_id", "alliance_name"]
            )
            n_show = n_show.rename(columns={"tribe_name": "tribe"})
            n_show = n_show[
                [
                    "village_id",
                    "village",
                    "coords",
                    "dist",
                    "population",
                    "tribe",
                    "tribe_id",
                    "player",
                    "alliance",
                ]
            ]
            npc_cc = dict(_link_column_config_village_player())
            npc_cc["tribe_id"] = st.column_config.NumberColumn(
                "Tribe id", width="small"
            )
            npc_cc["tribe"] = st.column_config.TextColumn("Tribe", width="small")
            st.markdown("##### Table (paged)")
            _paginated_dataframe(
                n_show,
                key=f"tbl_{csv_slug}_{server.key}",
                default_page_size=100,
                width="stretch",
                hide_index=True,
                column_config=npc_cc,
            )


@st.cache_data(ttl=30)
def player_history_df(server_key: str, player_id: int) -> tuple[pd.DataFrame, str, str]:
    conn = get_conn(str(DB_PATH))
    h = analyzer.player_history(conn, server_key, player_id)
    if h is None:
        return pd.DataFrame(), "", ""
    df = pd.DataFrame([p.__dict__ for p in h.points])
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    return df, h.player_name, h.tribe_name


@st.cache_data(ttl=30)
def player_village_ledger_df(server_key: str, player_id: int) -> pd.DataFrame:
    """Per-village settled / conquered / pre-existing ledger for one player."""
    conn = get_conn(str(DB_PATH))
    rows = analyzer.player_villages_with_history(conn, server_key, player_id)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    df["acquired_at"] = pd.to_datetime(df["acquired_at"], errors="coerce")
    return df


@st.cache_data(ttl=30)
def player_villages_lost_df(server_key: str, player_id: int) -> pd.DataFrame:
    """History rows: villages ever owned but not in latest snapshot (still on map)."""
    conn = get_conn(str(DB_PATH))
    rows = analyzer.player_villages_lost(conn, server_key, player_id)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["lost_at"] = pd.to_datetime(df["lost_at"], errors="coerce")
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return df


@st.cache_data(ttl=30)
def player_villages_destroyed_df(server_key: str, player_id: int) -> pd.DataFrame:
    """Villages the player owned that no longer appear in the latest snapshot (coords = last sighting)."""
    conn = get_conn(str(DB_PATH))
    rows = analyzer.player_villages_destroyed(conn, server_key, player_id)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["last_seen_at"] = pd.to_datetime(df["last_seen_at"], errors="coerce")
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return df


@st.cache_data(ttl=30)
def alliance_villages_lost_df(server_key: str, alliance_id: int) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.alliance_villages_lost(conn, server_key, int(alliance_id))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["lost_at"] = pd.to_datetime(df["lost_at"], errors="coerce")
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return df


@st.cache_data(ttl=30)
def alliance_villages_destroyed_df(server_key: str, alliance_id: int) -> pd.DataFrame:
    conn = get_conn(str(DB_PATH))
    rows = analyzer.alliance_villages_destroyed(conn, server_key, int(alliance_id))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r.__dict__ for r in rows])
    df["last_seen_at"] = pd.to_datetime(df["last_seen_at"], errors="coerce")
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return df


@st.cache_data(ttl=30)
def alliance_conquered_villages_df(server_key: str, alliance_id: int) -> pd.DataFrame:
    """Villages current members hold that were conquered (prior owner existed in history).

    Rosters and holdings use the **latest** stored snapshot — same semantics as ledger stats.
    """
    conn = get_conn(str(DB_PATH))
    latest = storage.latest_snapshot(conn, server_key)
    if latest is None or int(alliance_id) <= 0:
        return pd.DataFrame()
    sid = int(latest["id"])
    aids = analyzer.alliance_members_at_snapshot(conn, sid, int(alliance_id))
    rows_l: list[dict[str, object]] = []
    for m in aids:
        for acq in analyzer.player_villages_with_history(conn, server_key, m.player_id):
            if acq.status != "conquered":
                continue
            rows_l.append(
                {
                    "village_id": acq.village_id,
                    "village_name": acq.village_name,
                    "x": acq.x,
                    "y": acq.y,
                    "population": acq.population,
                    "holder_player_id": m.player_id,
                    "holder_player_name": m.player_name,
                    "from_player_id": int(acq.from_player_id or 0),
                    "from_player_name": str(acq.from_player_name or ""),
                    "from_alliance_name": str(acq.from_alliance_name or ""),
                    "acquired_at": acq.acquired_at,
                }
            )
    if not rows_l:
        return pd.DataFrame()
    df = pd.DataFrame(rows_l)
    df["acquired_at"] = pd.to_datetime(df["acquired_at"], errors="coerce")
    df["coords"] = df.apply(lambda r: f"({int(r.x):+d}|{int(r.y):+d})", axis=1)
    return df.sort_values(["acquired_at", "village_id"], ascending=[False, True])


def _alliance_split_chiefed_and_tag_loss_ids(
    lost_df: pd.DataFrame,
) -> tuple[frozenset[int], frozenset[int]]:
    """Alliance lost-on-map villages: chiefed-away (blue) vs same-holder tag loss (yellow)."""
    if lost_df.empty:
        return frozenset(), frozenset()
    if "chiefed_loss" not in lost_df.columns:
        return frozenset(), frozenset(int(v) for v in lost_df["village_id"].tolist())
    ch = lost_df["chiefed_loss"].fillna(False).astype(bool)
    chief_ids = frozenset(int(v) for v in lost_df.loc[ch, "village_id"].tolist())
    other_ids = frozenset(int(v) for v in lost_df.loc[~ch, "village_id"].tolist())
    return chief_ids, other_ids


@st.cache_data(ttl=30)
def alliance_history_df(server_key: str, alliance_id: int) -> tuple[pd.DataFrame, str]:
    conn = get_conn(str(DB_PATH))
    h = analyzer.alliance_history(conn, server_key, alliance_id)
    if h is None:
        return pd.DataFrame(), ""
    df = pd.DataFrame([p.__dict__ for p in h.points])
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    return df, h.alliance_name


@st.cache_data(ttl=30)
def village_history_df(
    server_key: str, village_id: int
) -> tuple[pd.DataFrame, str, tuple[int, int]]:
    conn = get_conn(str(DB_PATH))
    h = analyzer.village_history(conn, server_key, village_id)
    if h is None:
        return pd.DataFrame(), "", (0, 0)
    df = pd.DataFrame([p.__dict__ for p in h.points])
    df["fetched_at"] = pd.to_datetime(df["fetched_at"])
    return df, h.village_name, (h.x, h.y)


# ---------------------------------------------------------------------------
# Sidebar — global filters
# ---------------------------------------------------------------------------


def sidebar_select_server(cfg: AppConfig) -> ServerConfig | None:
    enabled = list(cfg.enabled_servers())
    if not enabled:
        st.sidebar.error("No enabled servers in config.")
        return None
    keys = [s.key for s in enabled]
    labels = {s.key: f"{s.name} ({s.key})" for s in enabled}
    chosen = st.sidebar.selectbox(
        "Server",
        options=keys,
        format_func=lambda k: labels[k],
        key="server_key",
    )
    return next(s for s in enabled if s.key == chosen)


def sidebar_dashboard_settings() -> None:
    """Chart size / Plotly palette + map canvas theme → ``config/ui.yaml``."""
    ui0 = load_ui_settings()
    opts = [p.key for p in MAP_PALETTES]

    if "dash_map_palette" not in st.session_state:
        st.session_state["dash_map_palette"] = ui0.map_palette
    if st.session_state["dash_map_palette"] not in opts:
        st.session_state["dash_map_palette"] = opts[0]

    if "dash_chart_size" not in st.session_state:
        st.session_state["dash_chart_size"] = ui0.chart_size
    if st.session_state["dash_chart_size"] not in VALID_CHART_SIZES:
        st.session_state["dash_chart_size"] = "compact"

    if "dash_chart_colors" not in st.session_state:
        st.session_state["dash_chart_colors"] = ui0.chart_colors
    if st.session_state["dash_chart_colors"] not in VALID_CHART_COLORS:
        st.session_state["dash_chart_colors"] = "muted"

    if "dash_chart_renderer" not in st.session_state:
        st.session_state["dash_chart_renderer"] = ui0.chart_renderer
    if st.session_state["dash_chart_renderer"] not in VALID_CHART_BACKENDS:
        st.session_state["dash_chart_renderer"] = "plotly"

    if "dash_overview_bar_kind" not in st.session_state:
        st.session_state["dash_overview_bar_kind"] = ui0.overview_bar_kind
    if st.session_state["dash_overview_bar_kind"] not in VALID_OVERVIEW_BAR_KINDS:
        st.session_state["dash_overview_bar_kind"] = "horizontal"

    if "dash_app_theme" not in st.session_state:
        st.session_state["dash_app_theme"] = ui0.app_theme
    _lt = list(LIGHT_DASH_APP_THEMES)
    if (
        str(st.session_state["dash_app_theme"]).strip().lower()
        not in LIGHT_DASH_APP_THEMES
    ):
        st.session_state["dash_app_theme"] = _lt[0]

    if "dash_appearance" not in st.session_state:
        st.session_state["dash_appearance"] = ui0.appearance
    _ap = str(st.session_state["dash_appearance"]).strip().lower()
    if _ap not in VALID_SHELL_APPEARANCE:
        st.session_state["dash_appearance"] = "light"

    _dash_shell_key = effective_shell_theme_slug(
        appearance=str(st.session_state.get("dash_appearance")),
        light_app_theme=str(st.session_state.get("dash_app_theme")),
    )
    st.sidebar.markdown(
        build_dashboard_shell_css(get_dash_app_theme(_dash_shell_key)),
        unsafe_allow_html=True,
    )

    sz_labels = {
        "compact": "Compact — denser graphs (recommended)",
        "comfortable": "Comfortable — medium height",
        "spacious": "Spacious — tall graphs",
    }
    clr_labels = {
        "default": "Default — Plotly automatic colors",
        "muted": "Muted — calm blues/greens/rust",
        "ocean": "Ocean — teals / blues",
        "warm": "Warm — amber / red / orange",
        "cool": "Cool — violet / cyan / teal",
        "colorblind": "Accessible — colorblind-friendly set",
        "royal": "Royal blue — cobalt to periwinkle depths",
        "mist_grey": "Mist grey — zinc / charcoal neutrals",
        "twilight": "Twilight — plum / violet aurora fade",
        "forest_edge": "Forest edge — deep emerald greens",
    }
    ren_labels = {
        "plotly": "Plotly — full control, theme colors apply",
        "streamlit": "Streamlit — built-in charts (ignores theme colors)",
        "altair": "Altair / Vega-Lite — responsive, theme colors apply",
    }
    obar_labels = {
        "horizontal": "Horizontal bars — readable labels (default)",
        "vertical": "Vertical bars — upright columns",
        "dots": "Dot plot — points only",
        "ranked_table": "Ranked table — no chart",
    }

    st.sidebar.markdown("##### Dashboard appearance")
    st.sidebar.radio(
        "Shell mode",
        options=list(VALID_SHELL_APPEARANCE),
        format_func=lambda m: "Light" if m == "light" else "Dark",
        horizontal=True,
        key="dash_appearance",
        help="Light: pick a palette below. Dark: fixed high-contrast Obsidian shell.",
    )
    _light_shell = (
        str(st.session_state.get("dash_appearance", "")).strip().lower() == "light"
    )
    st.sidebar.selectbox(
        "Light palette (backgrounds & tab bar)",
        options=list(LIGHT_DASH_APP_THEMES),
        format_func=lambda k: get_dash_app_theme(k).title,
        key="dash_app_theme",
        disabled=not _light_shell,
        help="Used when Shell mode is **Light**. Saved so switching Dark → Light restores your choice.",
    )
    st.sidebar.selectbox(
        "Line & bar chart engine",
        options=list(VALID_CHART_BACKENDS),
        format_func=lambda k: ren_labels[k],
        key="dash_chart_renderer",
        help="World map stays Plotly. This only changes history / overview line & bar charts.",
    )
    st.sidebar.selectbox(
        "Chart & graph heights",
        options=list(VALID_CHART_SIZES),
        format_func=lambda k: sz_labels[k],
        key="dash_chart_size",
        help="Line/bar chart height and world-map panel height.",
    )
    st.sidebar.selectbox(
        "Chart & graph colors (plots)",
        options=list(VALID_CHART_COLORS),
        format_func=lambda k: clr_labels[k],
        key="dash_chart_colors",
        help="Line/bar charts when engine is Plotly or Altair. Streamlit uses the app theme.",
    )
    st.sidebar.selectbox(
        "Overview: tribe / alliance totals",
        options=list(VALID_OVERVIEW_BAR_KINDS),
        format_func=lambda k: obar_labels[k],
        key="dash_overview_bar_kind",
        help='How to show tribe distribution and top alliances by population on the Overview tab. Try "dots" or "ranked table" if bars feel busy.',
    )
    st.sidebar.selectbox(
        "World map theme (canvas)",
        options=opts,
        format_func=lambda k: next(p.title for p in MAP_PALETTES if p.key == k),
        key="dash_map_palette",
    )

    persisted = load_ui_settings()
    new_prefs = UISettings(
        map_palette=st.session_state["dash_map_palette"],
        chart_size=st.session_state["dash_chart_size"],
        chart_colors=st.session_state["dash_chart_colors"],
        chart_renderer=st.session_state["dash_chart_renderer"],
        overview_bar_kind=st.session_state["dash_overview_bar_kind"],
        app_theme=str(st.session_state["dash_app_theme"]).strip().lower(),
        appearance=str(st.session_state["dash_appearance"]).strip().lower(),
    )
    if new_prefs != persisted:
        save_ui_settings(new_prefs)


cfg = load_app_config()
sidebar_dashboard_settings()
server = sidebar_select_server(cfg)

if server is None:
    st.stop()

snapshots_df = list_snapshots(server.key)
if snapshots_df.empty:
    st.title("t.statistics.stas.bot")
    st.warning(
        f"No snapshots stored yet for **{server.name}**. "
        "Run `python main.py fetch` first."
    )
    st.stop()

st.markdown(
    f"##### t.statistics.stas.bot  \n"
    f"<span style='opacity:.82;font-weight:400'>{server.name}</span>",
    unsafe_allow_html=True,
)
st.caption(
    f"`{server.key}` · snapshots **{len(snapshots_df)}** · latest "
    f"{pd.to_datetime(snapshots_df.iloc[0]['fetched_at']).strftime('%Y-%m-%d %H:%M UTC')}"
)

st.sidebar.markdown(
    f"**Snapshots stored**: {len(snapshots_df)}  \n"
    f"**Latest**: {pd.to_datetime(snapshots_df.iloc[0]['fetched_at']).strftime('%Y-%m-%d %H:%M UTC')}"
)
st.sidebar.markdown("---")
st.sidebar.markdown("##### Map collection")
_embed_on = embedded_scheduler_enabled()
if _embed_on:
    st.sidebar.success(
        f"Daily fetch **ON** — schedule **`{cfg.settings.schedule}`** (local time)."
    )
    if embedded_scheduler_started():
        st.sidebar.caption("Background scheduler thread is running in this process.")
    _lf = embedded_scheduler_last_fetch_at()
    if _lf:
        st.sidebar.caption(f"Last automated fetch finished: **{_lf}** (local).")
    _lfe = embedded_scheduler_last_fetch_error()
    if _lfe:
        st.sidebar.error(f"Last fetch error: {_lfe}")
    st.sidebar.caption("Do **not** also run `python main.py run` against the same DB.")
else:
    st.sidebar.warning(
        "Embedded fetch **OFF** (`T_STATS_EMBED_SCHEDULER=0`). "
        "Run `python main.py` or `scripts/run_daily_fetch.bat` elsewhere."
    )
if st.sidebar.button("Fetch now (all enabled servers)", key="sidebar_fetch_now"):
    with st.spinner("Downloading map.sql and updating database…"):
        fetch_all_enabled_servers(cfg, DB_PATH)
        st.cache_data.clear()
    st.sidebar.success("Fetch complete — reloading dashboard.")
    st.rerun()
st.sidebar.caption(
    "Set **`settings.schedule`** in `config/servers.json` (e.g. `daily@00:01`). "
    "The dashboard auto-refreshes cached tables after each fetch."
)
st.sidebar.markdown("---")


# ---------------------------------------------------------------------------
# Helpers — formatting
# ---------------------------------------------------------------------------

def _dash_chart_sizes() -> ChartSizePreset:
    return resolve_chart_preset(load_ui_settings().chart_size)


def _dash_chart_colorway() -> list[str] | None:
    return chart_graph_colorway(load_ui_settings().chart_colors)


def _dash_line_chart(data: pd.DataFrame, *, height: int) -> None:
    """Line chart — backend from ``dashboard.chart_renderer``."""
    _render_chart_line(
        data,
        height=height,
        colorway=_dash_chart_colorway(),
        backend=load_ui_settings().chart_renderer,
    )


PAGE_SIZE_OPTIONS: tuple[int, ...] = (10, 25, 50, 100, 200)

INACTIVE_PAGE_OPTS: tuple[int, ...] = (10, 25, 50, 100, 250, 500)
INACTIVE_DEFAULT_PAGE_SIZE = 25
INACTIVE_PAGING_THRESHOLD = 10

# Top tab leaderboards — show deeper cuts; paging defaults reveal full list on load
LB_LEADERBOARD_ROWS = 50
LB_LEADERBOARD_PAGE_OPTS: tuple[int, ...] = (25, 50, 75, 100, 150, 200)


def _leaderboard_pagination_kwargs() -> dict[str, object]:
    return {
        "page_size_options": LB_LEADERBOARD_PAGE_OPTS,
        "default_page_size": min(LB_LEADERBOARD_ROWS, 100),
    }


def _dataframe_height(row_count: int, *, row_px: int = 35, cap_px: int = 700) -> int:
    return min(cap_px, 38 + max(1, row_count) * row_px)


def _paginated_dataframe(
    df: pd.DataFrame,
    *,
    key: str,
    page_size_options: tuple[int, ...] = PAGE_SIZE_OPTIONS,
    default_page_size: int = 50,
    min_rows_for_paging: int | None = 10,
    **dataframe_kwargs,
) -> None:
    """Paged ``st.dataframe`` with rows-per-page and page number controls.

    When ``min_rows_for_paging`` is set and the table has at most that many rows,
    every row is shown and paging controls are hidden.
    """
    prefix = f"_pg_{key}"
    ps_key = f"{prefix}_ps"
    pg_key = f"{prefix}_page"

    n = len(df)
    if n == 0:
        st.caption("No rows.")
        return

    if min_rows_for_paging is not None and n <= min_rows_for_paging:
        st.caption(f"Showing **{n:,}** row(s).")
        visible = df
        kwargs = dict(dataframe_kwargs)
        kwargs.setdefault("height", _dataframe_height(len(visible)))
        st.dataframe(visible, **kwargs)
        return

    opts = tuple(page_size_options) if page_size_options else PAGE_SIZE_OPTIONS
    if default_page_size not in opts:
        default_page_size = opts[min(len(opts) // 2, len(opts) - 1)]
    idx_default = opts.index(default_page_size)

    def _reset_page() -> None:
        st.session_state[pg_key] = 1

    c1, c2, _ = st.columns([1, 1, 4])
    with c1:
        page_size = st.selectbox(
            "Rows per page",
            options=opts,
            index=idx_default,
            key=ps_key,
            on_change=_reset_page,
        )
    page_size = int(page_size)
    total_pages = max(1, (n + page_size - 1) // page_size)

    if pg_key not in st.session_state:
        st.session_state[pg_key] = 1
    else:
        cur = int(st.session_state[pg_key])
        cur = min(max(1, cur), total_pages)
        st.session_state[pg_key] = cur

    with c2:
        st.number_input(
            "Page",
            min_value=1,
            max_value=total_pages,
            step=1,
            key=pg_key,
        )
    page_n = int(st.session_state[pg_key])
    start = (page_n - 1) * page_size
    end = min(start + page_size, n)

    st.caption(
        f"Showing **{start + 1}–{end}** of **{n:,}** rows · page **{page_n}** / **{total_pages}**"
    )
    visible = df.iloc[start:end]
    kwargs = dict(dataframe_kwargs)
    kwargs.setdefault("height", _dataframe_height(len(visible)))
    st.dataframe(visible, **kwargs)


def _dash_bar_chart(
    data: pd.DataFrame,
    *,
    height: int,
    x_tick_angle: int = -35,
    bar_kind: str | None = None,
) -> None:
    bk = (
        bar_kind if bar_kind is not None else load_ui_settings().overview_bar_kind
    )
    if bk == "ranked_table":
        col = data.columns[0]
        tbl = data.sort_values(col, ascending=False).reset_index()
        st.dataframe(tbl, width="stretch", hide_index=True)
        return
    _render_chart_bar(
        data,
        height=height,
        colorway=_dash_chart_colorway(),
        backend=load_ui_settings().chart_renderer,
        x_tick_angle=x_tick_angle,
        bar_kind=bk,
    )


def fmt_dt(iso: str) -> str:
    return pd.to_datetime(iso).strftime("%Y-%m-%d %H:%M UTC")


def village_detail_query_string(village_id: int, server_key: str) -> str:
    """Relative query string for opening the dashboard with a village panel."""
    return urlencode({"village_detail": str(village_id), "server_key": server_key})


def player_detail_query_string(player_id: int, server_key: str) -> str:
    return urlencode({"player_detail": str(player_id), "server_key": server_key})


def alliance_detail_query_string(alliance_id: int, server_key: str) -> str:
    return urlencode({"alliance_detail": str(alliance_id), "server_key": server_key})


def _detail_href(query: str) -> str:
    return "?" + query


# LinkColumn shows this capture group; fragment is ignored by the browser for navigation.
_LINK_LABEL_FRAGMENT_RE = r"#(.+)$"


def _link_fragment_label(text: str) -> str:
    t = (
        str(text)
        .replace("#", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )
    return t or "—"


def player_profile_href(
    player_id: int, player_name: str, server_key: str
) -> str | None:
    if player_id <= 0:
        return None
    q = player_detail_query_string(player_id, server_key)
    lab = _link_fragment_label(player_name) if player_name else f"player {player_id}"
    return _detail_href(q) + "#" + lab


def alliance_profile_href(
    alliance_id: int, alliance_name: str, server_key: str
) -> str | None:
    if alliance_id <= 0:
        return None
    q = alliance_detail_query_string(alliance_id, server_key)
    lab = (
        _link_fragment_label(alliance_name)
        if alliance_name
        else f"alliance {alliance_id}"
    )
    return _detail_href(q) + "#" + lab


def village_profile_href(
    village_id: int, village_name: str, server_key: str
) -> str | None:
    if village_id <= 0:
        return None
    q = village_detail_query_string(village_id, server_key)
    lab = (
        _link_fragment_label(village_name)
        if village_name
        else f"village {village_id}"
    )
    return _detail_href(q) + "#" + lab


def _player_name_link_series(
    names: pd.Series, ids: pd.Series, server_key: str
) -> pd.Series:
    out: list[str | None] = []
    for nm, pid in zip(names.tolist(), ids.tolist()):
        try:
            p = int(pid)
        except (TypeError, ValueError):
            p = 0
        if nm is None or (isinstance(nm, float) and pd.isna(nm)):
            nm_s = ""
        else:
            nm_s = str(nm)
        out.append(player_profile_href(p, nm_s, server_key))
    return pd.Series(out, index=names.index, dtype=object)


def _alliance_name_link_series(
    names: pd.Series, ids: pd.Series, server_key: str
) -> pd.Series:
    out: list[str | None] = []
    for nm, aid in zip(names.tolist(), ids.tolist()):
        try:
            a = int(aid)
        except (TypeError, ValueError):
            a = 0
        if nm is None or (isinstance(nm, float) and pd.isna(nm)):
            nm_s = ""
        else:
            nm_s = str(nm)
        out.append(alliance_profile_href(a, nm_s, server_key))
    return pd.Series(out, index=names.index, dtype=object)


def _village_name_link_series(
    names: pd.Series, ids: pd.Series, server_key: str
) -> pd.Series:
    out: list[str | None] = []
    for nm, vid in zip(names.tolist(), ids.tolist()):
        try:
            v = int(vid)
        except (TypeError, ValueError):
            v = 0
        if nm is None or (isinstance(nm, float) and pd.isna(nm)):
            nm_s = ""
        else:
            nm_s = str(nm)
        out.append(village_profile_href(v, nm_s, server_key))
    return pd.Series(out, index=names.index, dtype=object)


def travian_tile_href(base_url: str, x: int, y: int) -> str:
    """Direct Travian Legends map URL for tile (x, y)."""
    q = urlencode({"x": str(int(x)), "y": str(int(y))})
    return f"{base_url.rstrip('/')}/position_details.php?{q}"


def _game_coord_markdown_link(base_url: str, x: int, y: int) -> str:
    """Inline HTML link — opens Travian map in a new browser tab."""
    label = f"({int(x):+d}|{int(y):+d})"
    url = html.escape(travian_tile_href(base_url, x, y), quote=True)
    return (
        f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
        f"{html.escape(label)}</a>"
    )


def _game_coords_link_series(base_url: str, xs: pd.Series, ys: pd.Series) -> pd.Series:
    """LinkColumn values: Travian ``position_details.php`` (opens in a new tab)."""
    out: list[str] = []
    for xr, yr in zip(xs.tolist(), ys.tolist()):
        try:
            x_i = int(xr)
            y_i = int(yr)
        except (TypeError, ValueError):
            x_i, y_i = 0, 0
        coord_label = f"({x_i:+d}|{y_i:+d})"
        lab = _link_fragment_label(coord_label)
        out.append(f"{travian_tile_href(base_url, x_i, y_i)}#{lab}")
    return pd.Series(out, index=xs.index, dtype=object)


def _apply_coords_game_links(
    df: pd.DataFrame,
    base_url: str,
    *,
    x_col: str = "x",
    y_col: str = "y",
    coords_col: str = "coords",
    drop_xy: bool = True,
) -> pd.DataFrame:
    """Replace or add ``coords`` with Travian map links when ``x``/``y`` are present."""
    if df.empty or x_col not in df.columns or y_col not in df.columns:
        return df
    out = df.copy()
    out[coords_col] = _game_coords_link_series(base_url, out[x_col], out[y_col])
    if drop_xy:
        out = out.drop(columns=[x_col, y_col])
    return out


def _link_column_coords_game() -> dict:
    return {
        "coords": st.column_config.LinkColumn(
            "coords",
            help="Open this tile on the Travian map (new browser tab)",
            display_text=_LINK_LABEL_FRAGMENT_RE,
            width="small",
        ),
    }


def _events_village_display_df(df: pd.DataFrame, server: ServerConfig) -> pd.DataFrame:
    """Events tables: ``x``/``y`` → clickable ``coords`` (Travian map, new tab)."""
    if df.empty or "x" not in df.columns:
        return df
    out = _apply_coords_game_links(df, server.base_url)
    cols = list(out.columns)
    if "village_name" in cols and "coords" in cols:
        cols.remove("coords")
        cols.insert(cols.index("village_name") + 1, "coords")
        out = out[cols]
    return out


DETAIL_QUERY_KEYS = frozenset(
    {"village_detail", "player_detail", "alliance_detail", "server_key"}
)


def _clear_all_detail_params() -> None:
    for k in DETAIL_QUERY_KEYS:
        if k in st.query_params:
            del st.query_params[k]


def _link_column_config_players_tab() -> dict:
    return {
        "player": st.column_config.LinkColumn(
            "Player", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
        "alliance": st.column_config.LinkColumn(
            "Alliance", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
    }


def _link_column_config_alliance_tab() -> dict:
    return {
        "alliance": st.column_config.LinkColumn(
            "Alliance", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
    }


def _link_column_lb_player() -> dict:
    return {
        "player": st.column_config.LinkColumn(
            "player", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
    }


def _link_column_config_village_player() -> dict:
    return {
        **_link_column_coords_game(),
        "village": st.column_config.LinkColumn(
            "Village", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
        "player": st.column_config.LinkColumn(
            "Player", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
        "alliance": st.column_config.LinkColumn(
            "Alliance", display_text=_LINK_LABEL_FRAGMENT_RE, width="medium"
        ),
    }


def render_village_detail_block(server: ServerConfig, village_id: int) -> None:
    """History + owners table for one village (shared by Villages tab & deep links)."""
    vh_df, vname, (vx, vy) = village_history_df(server.key, int(village_id))
    if vh_df.empty:
        st.warning(f"No data for village id **{village_id}** on this server.")
        return
    coord_link = _game_coord_markdown_link(server.base_url, vx, vy)
    st.markdown(
        f"**{vname}** &nbsp;·&nbsp; coords {coord_link} &nbsp;·&nbsp; "
        f"{len(vh_df)} snapshot(s) &nbsp;·&nbsp; "
        f"distinct owners: {vh_df['player_id'].nunique()}",
        unsafe_allow_html=True,
    )
    if len(vh_df) >= 2:
        sz = _dash_chart_sizes()
        _dash_line_chart(
            vh_df.set_index("fetched_at")[["population"]],
            height=sz.detail_line,
        )
    _paginated_dataframe(
        vh_df[["snapshot_id", "fetched_at", "player_name",
               "alliance_name", "population"]]
        .rename(columns={
            "player_name": "owner",
            "alliance_name": "alliance",
        }),
        key=f"detail_village_hist_{int(village_id)}",
        width="stretch",
        hide_index=True,
    )


def render_player_detail_block(
    server: ServerConfig, player_id: int, *, snapshot_id: int
) -> None:
    """Full player view: history, village ledger, relative map (dashboard / deep link)."""
    ph_df, name, tribe = player_history_df(server.key, int(player_id))
    if ph_df.empty:
        st.warning(f"No data for player id **{player_id}** on this server.")
        return
    st.markdown(
        f"**{name}** &nbsp;·&nbsp; tribe **{tribe}** &nbsp;·&nbsp; "
        f"{len(ph_df)} snapshot(s)"
    )
    cols = st.columns(2)
    cols[0].metric("Latest population", f"{int(ph_df.iloc[-1]['population']):,}")
    cols[1].metric("Latest villages", f"{int(ph_df.iloc[-1]['villages']):,}")

    if len(ph_df) >= 2:
        sz = _dash_chart_sizes()
        _dash_line_chart(
            ph_df.set_index("fetched_at")[["population"]],
            height=sz.detail_line,
        )
    _paginated_dataframe(
        ph_df[["snapshot_id", "fetched_at", "alliance_name", "villages", "population"]]
        .rename(columns={"alliance_name": "alliance"}),
        key=f"detail_player_hist_{int(player_id)}",
        width="stretch",
        hide_index=True,
    )

    st.markdown(
        "###### Village ledger — current holdings (settled / conquered / pre-existing)"
    )
    ledger_df = player_village_ledger_df(server.key, int(player_id))
    lost_df = player_villages_lost_df(server.key, int(player_id))

    if ledger_df.empty:
        st.caption("No villages owned in the latest snapshot.")
    else:
        counts = ledger_df["status"].value_counts().to_dict()
        mc = st.columns(4)
        mc[0].metric("Total", f"{len(ledger_df)}")
        mc[1].metric("Settled", f"{counts.get('settled', 0)}")
        mc[2].metric("Conquered", f"{counts.get('conquered', 0)}")
        mc[3].metric("Pre-existing", f"{counts.get('pre-existing', 0)}")

        show_df = ledger_df.assign(
            chiefed_from=ledger_df.apply(
                lambda r: (
                    r["from_player_name"]
                    if r["status"] == "conquered"
                    else "(founded)" if r["status"] == "settled"
                    else "(unknown)"
                ),
                axis=1,
            ),
            coords=_game_coords_link_series(
                server.base_url,
                ledger_df["x"],
                ledger_df["y"],
            ),
        )[
            [
                "village_id", "village_name", "coords", "population",
                "status", "chiefed_from", "from_alliance_name",
                "acquired_at",
            ]
        ].rename(
            columns={
                "village_name": "village",
                "from_alliance_name": "from_alliance",
                "acquired_at": "date (UTC)",
            }
        )
        cc = dict(_link_column_coords_game())
        _paginated_dataframe(
            show_df,
            key=f"detail_player_ledger_{int(player_id)}",
            width="stretch",
            hide_index=True,
            column_config=cc,
        )

    st.markdown("###### Villages lost to others (historical)")
    if lost_df.empty:
        st.caption(
            "No lost villages tracked — tiles you no longer hold that we still "
            "see elsewhere on the latest map (requires earlier snapshots). "
            "Abandoned/destroyed tiles that disappear entirely are not listed here."
        )
    else:
        st.metric("Lost (still on map)", f"{len(lost_df)}")
        lf = lost_df.rename(
            columns={
                "village_name": "village",
                "population": "pop",
                "to_player_name": "owner",
                "to_alliance_name": "their_alliance",
                "lost_at": "lost (UTC)",
            }
        )
        lf_disp = lf.assign(
            coords=_game_coords_link_series(
                server.base_url, lf["x"], lf["y"]
            ),
            village=_village_name_link_series(
                lf["village"], lf["village_id"], server.key
            ),
            owner=_player_name_link_series(
                lf["owner"].fillna(""),
                lf["to_player_id"],
                server.key,
            ),
        )[
            [
                "village_id",
                "village",
                "coords",
                "pop",
                "owner",
                "their_alliance",
                "lost (UTC)",
            ]
        ]
        lost_cc = {
            **_link_column_coords_game(),
            "village": st.column_config.LinkColumn(
                "village",
                display_text=_LINK_LABEL_FRAGMENT_RE,
                width="medium",
            ),
            "owner": st.column_config.LinkColumn(
                "owner",
                display_text=_LINK_LABEL_FRAGMENT_RE,
                width="medium",
            ),
        }
        _paginated_dataframe(
            lf_disp,
            key=f"detail_player_lost_{int(player_id)}",
            width="stretch",
            hide_index=True,
            column_config=lost_cc,
        )

    st.markdown("###### Relative map — this player vs the rest of the world")
    _render_player_map_fragment(
        server_key=server.key,
        snapshot_id=snapshot_id,
        player_id=int(player_id),
        player_name=name,
    )


def render_alliance_detail_block(
    server: ServerConfig, alliance_id: int, *, snapshot_id: int
) -> None:
    ah_df, name = alliance_history_df(server.key, int(alliance_id))
    if ah_df.empty:
        st.warning(f"No data for alliance id **{alliance_id}** on this server.")
        return
    st.markdown(f"**{name}** &nbsp;·&nbsp; {len(ah_df)} snapshot(s)")
    cols = st.columns(3)
    cols[0].metric("Latest population", f"{int(ah_df.iloc[-1]['population']):,}")
    cols[1].metric("Members", f"{int(ah_df.iloc[-1]['members']):,}")
    cols[2].metric("Villages", f"{int(ah_df.iloc[-1]['villages']):,}")

    st.markdown("###### Members (current snapshot)")
    conn = get_conn(str(DB_PATH))
    mem_rows = analyzer.alliance_members_at_snapshot(
        conn, int(snapshot_id), int(alliance_id)
    )
    if not mem_rows:
        st.caption("No member villages linked to this alliance in the selected snapshot.")
    else:
        mdf = pd.DataFrame([r.__dict__ for r in mem_rows])
        mdf = mdf.rename(columns={"tribe_name": "tribe"})
        mdf["player"] = _player_name_link_series(
            mdf["player_name"], mdf["player_id"], server.key
        )
        roster = mdf[
            ["player_id", "player", "tribe", "villages", "population"]
        ].copy()
        _paginated_dataframe(
            roster,
            key=f"detail_ally_members_{int(alliance_id)}",
            width="stretch",
            hide_index=True,
            column_config={
                "player": st.column_config.LinkColumn(
                    "Player",
                    display_text=_LINK_LABEL_FRAGMENT_RE,
                    width="medium",
                ),
            },
        )

    st.markdown("###### Map — this alliance vs the rest of the world")
    _render_alliance_map_fragment(
        server=server,
        snapshot_id=int(snapshot_id),
        alliance_id=int(alliance_id),
        alliance_name=name,
    )

    if len(ah_df) >= 2:
        sz = _dash_chart_sizes()
        _dash_line_chart(
            ah_df.set_index("fetched_at")[["population", "members"]],
            height=sz.detail_line,
        )
    with st.expander("Snapshot history (table)", expanded=False):
        _paginated_dataframe(
            ah_df[["snapshot_id", "fetched_at", "members", "villages", "population"]],
            key=f"detail_ally_hist_{int(alliance_id)}",
            width="stretch",
            hide_index=True,
        )


def _map_span_from_df(df: pd.DataFrame) -> int:
    if df.empty:
        return 50
    span_x = max(abs(int(df["x"].min())), abs(int(df["x"].max())), 50)
    span_y = max(abs(int(df["y"].min())), abs(int(df["y"].max())), 50)
    return max(span_x, span_y) + 2


def _multi_highlight_marker_specs(
    count: int, palette_key: str
) -> list[tuple[str, str]]:
    """Plotly marker (fill_rgb, line_rgb) for layered highlights — distinct hues."""
    pal = get_palette(palette_key)
    bg_luma = 0.299 * pal.bg[0] + 0.587 * pal.bg[1] + 0.114 * pal.bg[2]
    dark_bg = bg_luma < 90.0
    fills = [
        (255, 107, 107),
        (79, 168, 255),
        (102, 207, 110),
        (255, 213, 79),
        (217, 123, 230),
        (93, 211, 230),
        (255, 183, 77),
        (185, 220, 120),
        (244, 143, 177),
        (128, 199, 244),
        (156, 204, 101),
        (229, 115, 115),
        (174, 204, 98),
        (255, 167, 38),
        (171, 130, 255),
    ]
    if not dark_bg:
        fills = [
            (211, 47, 47),
            (25, 118, 210),
            (46, 125, 50),
            (245, 124, 0),
            (123, 31, 162),
            (0, 121, 107),
            (198, 40, 40),
            (57, 73, 171),
            (239, 83, 80),
            (30, 136, 229),
            (67, 160, 71),
            (251, 140, 0),
            (142, 36, 170),
            (0, 137, 123),
            (229, 57, 53),
            (21, 101, 192),
        ]
    out: list[tuple[str, str]] = []
    for i in range(max(count, 1)):
        r, g, b = fills[i % len(fills)]
        fill = f"rgb({r},{g},{b})"
        line = "rgb(255,255,255)" if dark_bg else "rgb(26,26,26)"
        out.append((fill, line))
    return out


# Player map: red = lost owner, yellow = off-map. Alliance map swaps to yellow = left tag, red = deleted,
# plus blue chiefed-loss layer.
_PM_LOST_RED = ("rgb(239, 68, 68)", "rgb(127, 29, 29)")
_PM_CUR_GREEN = ("rgb(34, 197, 94)", "rgb(20, 83, 45)")
_PM_OFF_YELLOW = ("rgb(234, 179, 8)", "rgb(120, 53, 15)")
_PM_ALLY_CHIEF_BLUE = ("rgb(59, 130, 246)", "rgb(29, 78, 216)")


def _resolve_map_highlight_layers(
    hl_layers: list[tuple[object, ...]],
    palette_key: str,
) -> list[tuple[frozenset[int], str, tuple[str, str]]]:
    rows: list[tuple[frozenset[int], str, tuple[str, str] | None]] = []
    for ent in hl_layers:
        if len(ent) < 2:
            continue
        ids_raw, lab = ent[0], str(ent[1])
        fid = ids_raw if isinstance(ids_raw, frozenset) else frozenset(int(v) for v in ids_raw)
        if not fid:
            continue
        if len(ent) >= 4 and isinstance(ent[2], str) and isinstance(ent[3], str):
            rows.append((fid, lab, (ent[2], ent[3])))
        else:
            rows.append((fid, lab, None))
    implicit_n = sum(1 for _fid, _lab, spec in rows if spec is None)
    pool = iter(_multi_highlight_marker_specs(max(implicit_n, 1), palette_key))
    resolved: list[tuple[frozenset[int], str, tuple[str, str]]] = []
    for fid, lab, spec in rows:
        rgb = spec if spec is not None else next(pool)
        resolved.append((fid, lab, rgb))
    return resolved


def _offline_destroyed_customdata(frame: pd.DataFrame) -> np.ndarray:
    return np.column_stack(
        [
            frame["village_id"].astype(int).to_numpy(),
            frame["village_name"].fillna("").astype(str).to_numpy(),
            frame["population"].fillna(0).astype(int).to_numpy(),
            frame["x"].astype(int).to_numpy(),
            frame["y"].astype(int).to_numpy(),
            pd.to_datetime(frame["last_seen_at"], errors="coerce")
            .dt.strftime("%Y-%m-%d %H:%M")
            .fillna("")
            .astype(str)
            .to_numpy(),
        ]
    )


def _plotly_world_map_figure(
    idx: pd.DataFrame,
    hl_village_ids: frozenset[int],
    palette_key: str,
    viewport: tuple[int, int, int] | None = None,
    *,
    plot_height: int = 720,
    hl_layers: list[tuple[object, ...]] | None = None,
    offline_player_dots: pd.DataFrame | None = None,
    offline_marker_rgb: tuple[str, str] | None = None,
    offline_trace_name: str | None = None,
    offline_hover_note: str | None = None,
) -> tuple[go.Figure, int]:
    pal = get_palette(palette_key)
    use_window = viewport is not None and int(viewport[2]) > 0
    if use_window:
        cx, cy, vr = int(viewport[0]), int(viewport[1]), int(viewport[2])
        span = max(vr, 1)
        pad = max(span * 0.02, 0.5)
        lo_x, hi_x = cx - span - pad, cx + span + pad
        lo_y, hi_y = cy - span - pad, cy + span + pad
    else:
        span = _map_span_from_df(idx)
        pad = span * 0.02
        lo_x = lo_y = -span - pad
        hi_x = hi_y = span + pad
    bg = f"rgb{pal.bg}"
    axis_col = f"rgb{pal.axis}"
    dot_col = f"rgb{pal.dot}"
    hl_col = f"rgb{pal.hl_fill}"
    hl_line = f"rgb{pal.hl_outline}"

    def _sub_customdata(sub: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [
                sub["village_id"].to_numpy(),
                sub["village_name"].fillna("").astype(str).to_numpy(),
                sub["population"].fillna(0).astype(int).to_numpy(),
                sub["player_name"].fillna("").astype(str).to_numpy(),
                sub["alliance_name"].fillna("").astype(str).to_numpy(),
                sub["tribe_name"].fillna("").astype(str).to_numpy(),
                sub["x"].astype(int).to_numpy(),
                sub["y"].astype(int).to_numpy(),
                sub["player_id"].fillna(0).astype(int).to_numpy(),
            ]
        )

    hover = (
        "<b>%{customdata[1]}</b> (id %{customdata[0]})<br>"
        "pop %{customdata[2]} · (%{customdata[6]:+d}|%{customdata[7]:+d})<br>"
        "%{customdata[3]} (player id %{customdata[8]})<br>"
        "%{customdata[4]} · %{customdata[5]}<extra></extra>"
    )

    resolved_layers: list[tuple[frozenset[int], str, tuple[str, str]]] = []
    if hl_layers is not None:
        resolved_layers = _resolve_map_highlight_layers(list(hl_layers), palette_key)

    has_off = offline_player_dots is not None and not offline_player_dots.empty
    off_fill, off_line = (
        offline_marker_rgb if offline_marker_rgb is not None else _PM_OFF_YELLOW
    )
    off_name = offline_trace_name or "Destroyed (gone from map)"
    off_hover = offline_hover_note or "destroyed/off-map"
    hover_destroyed = (
        f"<b>%{{customdata[1]}}</b> (id %{{customdata[0]}}) · {off_hover}<br>"
        "last UTC %{customdata[5]} · pop %{customdata[2]} "
        "· (%{customdata[3]:+d}|%{customdata[4]:+d})<extra></extra>"
    )

    fig = go.Figure()
    show_layer_legend = False

    def _destroyed_gl() -> None:
        nonlocal show_layer_legend
        assert offline_player_dots is not None
        ys = offline_player_dots
        cd = _offline_destroyed_customdata(ys)
        sz = max(pal.hl_radius + 3, 9)
        fig.add_trace(
            go.Scattergl(
                x=ys["x"].astype(int),
                y=ys["y"].astype(int),
                mode="markers",
                marker=dict(
                    size=float(sz),
                    color=off_fill,
                    line=dict(width=1.5, color=off_line),
                ),
                customdata=cd,
                hovertemplate=hover_destroyed,
                name=off_name[:80] + ("…" if len(off_name) > 80 else ""),
                showlegend=True,
            )
        )
        show_layer_legend = True

    if resolved_layers:
        union_fc: frozenset[int] = frozenset()
        for vs, _lab, _r in resolved_layers:
            union_fc |= vs
        bg_df = idx[~idx["village_id"].isin(union_fc)] if union_fc else idx
        if not bg_df.empty:
            fig.add_trace(
                go.Scattergl(
                    x=bg_df["x"],
                    y=bg_df["y"],
                    mode="markers",
                    marker=dict(size=5, color=dot_col, line=dict(width=0)),
                    customdata=_sub_customdata(bg_df),
                    hovertemplate=hover,
                    name="Others",
                    showlegend=True,
                )
            )
        if has_off:
            _destroyed_gl()
        for vs, label, (fill_rgb, line_rgb) in resolved_layers:
            fg_df = idx[idx["village_id"].isin(vs)]
            if fg_df.empty:
                continue
            show_layer_legend = True
            fig.add_trace(
                go.Scattergl(
                    x=fg_df["x"],
                    y=fg_df["y"],
                    mode="markers",
                    marker=dict(
                        size=max(pal.hl_radius + 3, 9),
                        color=fill_rgb,
                        line=dict(width=1.5, color=line_rgb),
                    ),
                    customdata=_sub_customdata(fg_df),
                    hovertemplate=hover,
                    name=label[:80] + ("…" if len(label) > 80 else ""),
                    showlegend=True,
                )
            )
    elif hl_village_ids:
        bg_df = idx[~idx["village_id"].isin(hl_village_ids)]
        fg_df = idx[idx["village_id"].isin(hl_village_ids)]
        if not bg_df.empty:
            fig.add_trace(
                go.Scattergl(
                    x=bg_df["x"],
                    y=bg_df["y"],
                    mode="markers",
                    marker=dict(size=5, color=dot_col, line=dict(width=0)),
                    customdata=_sub_customdata(bg_df),
                    hovertemplate=hover,
                    name="",
                    showlegend=False,
                )
            )
        if not fg_df.empty:
            fig.add_trace(
                go.Scattergl(
                    x=fg_df["x"],
                    y=fg_df["y"],
                    mode="markers",
                    marker=dict(
                        size=max(pal.hl_radius + 3, 9),
                        color=hl_col,
                        line=dict(width=1.5, color=hl_line),
                    ),
                    customdata=_sub_customdata(fg_df),
                    hovertemplate=hover,
                    name="",
                    showlegend=False,
                )
            )
    elif has_off:
        if not idx.empty:
            fig.add_trace(
                go.Scattergl(
                    x=idx["x"],
                    y=idx["y"],
                    mode="markers",
                    marker=dict(size=5, color=dot_col, line=dict(width=0)),
                    customdata=_sub_customdata(idx),
                    hovertemplate=hover,
                    name="Others",
                    showlegend=True,
                )
            )
        _destroyed_gl()
    else:
        fig.add_trace(
            go.Scattergl(
                x=idx["x"],
                y=idx["y"],
                mode="markers",
                marker=dict(size=5, color=dot_col, line=dict(width=0)),
                customdata=_sub_customdata(idx),
                hovertemplate=hover,
                name="",
                showlegend=False,
            )
        )

    leg = None
    if resolved_layers or show_layer_legend:
        leg = dict(
            orientation="h",
            yanchor="bottom",
            y=1.01,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        )

    fig.update_layout(
        margin=dict(l=8, r=8, t=52 if leg else 8, b=8),
        paper_bgcolor=bg,
        plot_bgcolor=bg,
        height=int(plot_height),
        dragmode="pan",
        hovermode="closest",
        legend=leg,
        xaxis=dict(
            range=[lo_x, hi_x],
            scaleanchor="y",
            scaleratio=1,
            gridcolor=axis_col,
            zerolinecolor=axis_col,
            zerolinewidth=1,
            showgrid=True,
            title=dict(text="x", font=dict(color=axis_col)),
            tickfont=dict(color=axis_col),
        ),
        yaxis=dict(
            range=[lo_y, hi_y],
            gridcolor=axis_col,
            zerolinecolor=axis_col,
            zerolinewidth=1,
            showgrid=True,
            title=dict(text="y", font=dict(color=axis_col)),
            tickfont=dict(color=axis_col),
        ),
    )
    return fig, span

def render_world_map(
    *,
    server_key: str,
    snapshot_id: int,
    highlight_label: str,
    palette_key: str,
    idx: pd.DataFrame | None = None,
    hl_village_ids: frozenset[int] | None = None,
    plotly_key: str | None = None,
    viewport: tuple[int, int, int] | None = None,
    plot_height: int = 720,
    hl_layers: list[tuple[object, ...]] | None = None,
    offline_player_dots: pd.DataFrame | None = None,
    offline_marker_rgb: tuple[str, str] | None = None,
    offline_trace_name: str | None = None,
    offline_hover_note: str | None = None,
    metrics_village_ids: frozenset[int] | None = None,
    # Legacy PNG-era keyword names (some trees still call these)
    all_df: pd.DataFrame | None = None,
    highlight_df: pd.DataFrame | None = None,
) -> None:
    """Interactive Plotly map: hover for details; click syncs the village to the pinned profile (URL)."""
    if idx is None:
        idx = all_df
    if idx is None or idx.empty:
        st.info("No villages to map.")
        return

    if hl_village_ids is None:
        if highlight_df is not None and not highlight_df.empty:
            hl_village_ids = frozenset(int(v) for v in highlight_df["village_id"].tolist())
        else:
            hl_village_ids = frozenset()

    offline_n = (
        len(offline_player_dots) if offline_player_dots is not None and not offline_player_dots.empty else 0
    )

    if plotly_key is None:
        plotly_key = f"map_{server_key}_{snapshot_id}"

    nonempty_l = (
        [(ent[0], ent[1]) for ent in hl_layers if len(ent) >= 2 and len(ent[0]) > 0]
        if hl_layers
        else []
    )
    if nonempty_l:
        u_ids: set[int] = set()
        for vs, _ in nonempty_l:
            u_ids |= set(vs)
        n_markers = len(u_ids) + offline_n
        focus_for_metrics = metrics_village_ids if metrics_village_ids is not None else frozenset(u_ids)
    else:
        n_markers = len(hl_village_ids) + offline_n
        focus_for_metrics = (
            metrics_village_ids if metrics_village_ids is not None else hl_village_ids
        )

    total = len(idx)
    fig, _ = _plotly_world_map_figure(
        idx,
        hl_village_ids,
        palette_key,
        viewport=viewport,
        plot_height=plot_height,
        hl_layers=hl_layers,
        offline_player_dots=offline_player_dots,
        offline_marker_rgb=offline_marker_rgb,
        offline_trace_name=offline_trace_name,
        offline_hover_note=offline_hover_note,
    )

    vp_note = ""
    if viewport is not None and int(viewport[2]) > 0:
        _vx, _vy, _vr = int(viewport[0]), int(viewport[1]), int(viewport[2])
        vp_note = (
            f" **Viewport:** center ({_vx:+d}|{_vy:+d}), half-side {_vr} tiles (square). "
        )

    st.caption(
        f"**{highlight_label}**  ·  "
        f"{n_markers:,} marked of {total:,} villages.{vp_note} "
        "**Hover** for details; **tap or click** a dot to open that village’s **pinned profile** at the top "
        "of the page (same tab). Links under the map can open the village or player in a **new tab**. "
        "Pan/drag; mouse wheel zoom if your browser sends it to the chart."
    )
    plot_state = st.plotly_chart(
        fig,
        key=plotly_key,
        on_select="rerun",
        selection_mode="points",
        theme=None,
        width="stretch",
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )

    points: list = []
    if plot_state is not None:
        try:
            sel = plot_state["selection"]
        except (KeyError, TypeError):
            sel = getattr(plot_state, "selection", None)
        if sel:
            try:
                points = list(sel.get("points", [])) if hasattr(sel, "get") else list(sel["points"])
            except (KeyError, TypeError):
                points = []

    if points:
        p0 = points[0]
        cd = p0["customdata"] if isinstance(p0, dict) else getattr(p0, "customdata", None)
        if cd is not None and len(cd) >= 1:
            try:
                svid = int(float(cd[0]))
            except (TypeError, ValueError):
                svid = None
            if svid is not None and svid > 0:
                _qpv = st.query_params.get("village_detail")
                try:
                    _cur_vid = (
                        int(str(_qpv).strip())
                        if _qpv is not None and str(_qpv).strip()
                        else None
                    )
                except (TypeError, ValueError):
                    _cur_vid = None
                if _cur_vid != int(svid):
                    st.session_state["_pending_map_village_detail"] = (
                        server_key,
                        int(svid),
                    )
                    st.rerun()
                vname = str(cd[1]) if len(cd) > 1 else ""
                vname_esc = html.escape(vname)
                qv = village_detail_query_string(svid, server_key)
                st.markdown(
                    f'<p><a href="?{qv}" target="_blank" rel="noopener noreferrer" '
                    f'style="font-size:1.1rem;font-weight:600;">'
                    f"Village: {vname_esc} (#{svid}) — new tab →</a></p>",
                    unsafe_allow_html=True,
                )
                spid: int | None = None
                if len(cd) >= 9:
                    try:
                        spid = int(float(cd[8]))
                    except (TypeError, ValueError):
                        spid = None
                if spid is not None and spid > 0:
                    pname = str(cd[3]) if len(cd) > 3 else ""
                    pname_esc = html.escape(pname)
                    qp = player_detail_query_string(spid, server_key)
                    st.markdown(
                        f'<p><a href="?{qp}" target="_blank" rel="noopener noreferrer" '
                        f'style="font-size:1.05rem;font-weight:600;">'
                        f"Player: {pname_esc} (#{spid}) — stats in new tab →</a></p>",
                        unsafe_allow_html=True,
                    )

    if n_markers > 0 and len(focus_for_metrics) > 0:
        sub = idx[idx["village_id"].isin(focus_for_metrics)]
        if not sub.empty:
            cx = float(sub["x"].mean())
            cy = float(sub["y"].mean())
            cols = st.columns(4)
            cols[0].metric("Centroid x",  f"{cx:+.1f}")
            cols[1].metric("Centroid y",  f"{cy:+.1f}")
            cols[2].metric(
                "X range",
                f"{int(sub['x'].min()):+d} … {int(sub['x'].max()):+d}",
            )
            cols[3].metric(
                "Y range",
                f"{int(sub['y'].min()):+d} … {int(sub['y'].max()):+d}",
            )


@st.cache_data(ttl=600, max_entries=8, show_spinner=False)
def _map_index(server_key: str, snapshot_id: int) -> pd.DataFrame:
    """Lean, map-only index of every village in a snapshot.

    Pulls just the columns the Map tab needs (no deltas, no joins to the
    previous snapshot). Used for the highlight filters and the per-row
    detail expander; goes straight through `pd.read_sql_query` so we never
    pay for the dataclass round-trip the analyzer would otherwise do.
    """
    conn = get_conn(str(DB_PATH))
    df = pd.read_sql_query(
        """
        SELECT village_id, village_name, x, y, population,
               player_id, player_name, alliance_id, alliance_name,
               tribe_id, region, extra_json
        FROM villages
        WHERE snapshot_id = ?
        """,
        conn,
        params=(snapshot_id,),
    )
    df["tribe_name"] = df["tribe_id"].map(
        lambda tid: analyzer.TRIBE_NAMES.get(int(tid), f"tribe_{int(tid)}")
    )
    df["flag"] = [
        analyzer.village_flag_label(
            None if r is None or (isinstance(r, float) and pd.isna(r)) else str(r),
            ej if isinstance(ej, str) else None,
        )
        for r, ej in zip(df["region"].tolist(), df["extra_json"].tolist())
    ]
    df["coords"] = df.apply(lambda r: f"({int(r['x']):+d}|{int(r['y']):+d})", axis=1)
    return df


def _render_three_tone_overlay_map(
    *,
    server_key: str,
    snapshot_id: int,
    idx: pd.DataFrame,
    lost_ids: frozenset[int],
    current_ids: frozenset[int],
    destroyed_df: pd.DataFrame,
    caption: str,
    lost_layer_label: str,
    current_layer_label: str,
    highlight_label: str,
    plotly_key: str,
    plot_height: int,
    lost_marker_rgb: tuple[str, str] | None = None,
    offline_marker_rgb: tuple[str, str] | None = None,
    offline_trace_name: str | None = None,
    offline_hover_note: str | None = None,
    chiefed_ids: frozenset[int] | None = None,
    chiefed_layer_label: str = "Chiefed — lost to new owner",
    chiefed_marker_rgb: tuple[str, str] | None = None,
) -> None:
    """Player default: green = still owned, red = lost (still on map), yellow dots = destroyed / off-map.

    Alliance overlays can invert lost/offline colours and add ``chiefed_ids`` drawn in blue
    ahead of yellow / red semantics for non-chiefed losses."""

    chief_rgb = chiefed_marker_rgb if chiefed_marker_rgb is not None else _PM_ALLY_CHIEF_BLUE
    lost_rgb = lost_marker_rgb if lost_marker_rgb is not None else _PM_LOST_RED
    layers: list[tuple[object, ...]] = []
    if chiefed_ids:
        layers.append(
            (chiefed_ids, chiefed_layer_label, chief_rgb[0], chief_rgb[1])
        )
    if lost_ids:
        layers.append((lost_ids, lost_layer_label, lost_rgb[0], lost_rgb[1]))
    if current_ids:
        layers.append((current_ids, current_layer_label, _PM_CUR_GREEN[0], _PM_CUR_GREEN[1]))

    offline = (
        destroyed_df[["village_id", "village_name", "population", "x", "y", "last_seen_at"]].copy()
        if not destroyed_df.empty
        else None
    )

    st.caption(caption)
    render_world_map(
        server_key=server_key,
        snapshot_id=snapshot_id,
        idx=idx,
        hl_village_ids=frozenset(),
        hl_layers=layers if layers else None,
        offline_player_dots=offline,
        offline_marker_rgb=offline_marker_rgb,
        offline_trace_name=offline_trace_name,
        offline_hover_note=offline_hover_note,
        metrics_village_ids=current_ids,
        highlight_label=highlight_label,
        palette_key=str(st.session_state["dash_map_palette"]),
        plotly_key=plotly_key,
        plot_height=plot_height,
    )


def _render_alliance_loss_by_opposing_alliances(
    server: ServerConfig, lost_df: pd.DataFrame, table_key: str
) -> None:
    """Roll-up of villages still on-map that flipped off this alliance, grouped by current holder alliance."""
    st.markdown("###### Villages lost to other alliances (still on latest map)")
    if lost_df.empty:
        st.caption(
            "No villages recorded as **having left this alliance tag** while still present on "
            "the latest world snapshot."
        )
        return
    ld = lost_df.copy()
    if "to_alliance_id" not in ld.columns:
        ld["to_alliance_id"] = 0
    ld["to_alliance_id"] = ld["to_alliance_id"].fillna(0).astype(int)
    ld["to_alliance_name"] = ld["to_alliance_name"].fillna("").astype(str)
    has_chief = "chiefed_loss" in ld.columns

    rows_m: list[dict[str, object]] = []
    for (to_aid, to_aname), g in ld.groupby(["to_alliance_id", "to_alliance_name"], sort=False):
        aid_i = int(to_aid)
        name_s = str(to_aname).strip()
        n = len(g)
        ch = (
            int(g["chiefed_loss"].fillna(False).astype(bool).sum())
            if has_chief
            else 0
        )
        if aid_i <= 0 and not name_s:
            label = "No alliance tag (current holder)"
        elif name_s:
            label = name_s
        else:
            label = f"Alliance id {aid_i}"
        rows_m.append(
            {
                "to_alliance_id": aid_i,
                "to_alliance_name": name_s,
                "_label": label,
                "villages": n,
                "chiefed": ch,
                "same_owner": n - ch,
            }
        )
    if not rows_m:
        st.caption("No grouped rows.")
        return
    sm = pd.DataFrame(rows_m)
    sm = sm.sort_values(["villages", "chiefed"], ascending=[False, False])
    aidv = sm["to_alliance_id"].astype(int)
    nm_strip = sm["to_alliance_name"].astype(str).str.strip()
    link_names_arr = np.where(
        nm_strip != "",
        nm_strip,
        np.where(
            aidv > 0,
            "Alliance " + aidv.astype(str),
            sm["_label"].astype(str),
        ),
    )
    disp = pd.DataFrame(
        {
            "opponent_alliance": _alliance_name_link_series(
                pd.Series(link_names_arr, index=sm.index),
                aidv.astype(int),
                server.key,
            ),
            "villages": sm["villages"].astype(int),
            "chiefed": sm["chiefed"].astype(int),
            "left_tag_same_player": sm["same_owner"].astype(int),
        }
    )
    _paginated_dataframe(
        disp,
        key=f"ally_loss_by_opp_{table_key}",
        width="stretch",
        hide_index=True,
        column_config={
            "opponent_alliance": st.column_config.LinkColumn(
                "Opponent alliance (now)",
                display_text=_LINK_LABEL_FRAGMENT_RE,
                width="medium",
            ),
        },
    )
    st.caption(
        "**Chiefed**: new village owner vs last owner under our tag · **Same player**: alliance tag slid off "
        "without chief (member moved)."
    )


def _render_alliance_territory_tables(
    *,
    server: ServerConfig,
    alliance_id: int,
    lost_df: pd.DataFrame,
    destroyed_df: pd.DataFrame,
    key_suffix: str,
) -> None:
    """Conquered holdings + consolidated loss list for one alliance (detail + Map tab)."""
    st.markdown("###### Conquests & losses (conquers use **latest** member roster)")
    aid_key = str(int(alliance_id))
    tk = f"{server.key}_{aid_key}_{key_suffix}"
    _render_alliance_loss_by_opposing_alliances(server, lost_df, tk)
    nloss = (0 if lost_df.empty else len(lost_df)) + (
        0 if destroyed_df.empty else len(destroyed_df)
    )

    cdf = alliance_conquered_villages_df(server.key, int(alliance_id))
    with st.expander(
        f"Conquered — current alliance holdings ({len(cdf)} villages)",
        expanded=False,
    ):
        if cdf.empty:
            st.caption(
                "No **conquered** villages on current members’ ledgers (only settled / pre-existing), "
                "or not enough history to detect a prior owner."
            )
        else:
            show = cdf.copy()
            show["village"] = _village_name_link_series(
                show["village_name"], show["village_id"], server.key
            )
            show["coords"] = _game_coords_link_series(
                server.base_url, show["x"], show["y"]
            )
            show["holder"] = _player_name_link_series(
                show["holder_player_name"], show["holder_player_id"], server.key
            )
            show["previous_owner"] = _player_name_link_series(
                show["from_player_name"], show["from_player_id"], server.key
            )
            cols = [
                "village",
                "coords",
                "population",
                "holder",
                "previous_owner",
                "from_alliance_name",
                "acquired_at",
            ]
            out = (
                show[cols]
                .rename(columns={"from_alliance_name": "prior_owner_alliance"})
                .sort_values("acquired_at", ascending=False)
            )
            _paginated_dataframe(
                out,
                key=f"ally_conquer_{tk}",
                width="stretch",
                hide_index=True,
                column_config={
                    **_link_column_coords_game(),
                    "village": st.column_config.LinkColumn(
                        "Village",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                    "holder": st.column_config.LinkColumn(
                        "Holder",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                    "previous_owner": st.column_config.LinkColumn(
                        "Previous owner",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                },
            )

    with st.expander(
        f"Lost to others — left / chiefed / destroyed ({nloss} villages)",
        expanded=False,
    ):
        loss_parts: list[pd.DataFrame] = []
        if not lost_df.empty:
            lt = lost_df.copy()
            if "to_alliance_id" not in lt.columns:
                lt["to_alliance_id"] = 0
            if "chiefed_loss" in lt.columns:
                ch = lt["chiefed_loss"].fillna(False).astype(bool).to_numpy()
                lt["reason"] = np.where(
                    ch,
                    "Chiefed — new village owner",
                    "Owner moved alliance tag (still same player)",
                )
            else:
                lt["reason"] = "No longer with this alliance tag"
            lt["still_on_latest_map"] = True
            loss_parts.append(
                lt[
                    [
                        "village_id",
                        "village_name",
                        "x",
                        "y",
                        "population",
                        "lost_at",
                        "to_player_id",
                        "to_player_name",
                        "to_alliance_id",
                        "to_alliance_name",
                        "still_on_latest_map",
                        "reason",
                    ]
                ]
            )
        if not destroyed_df.empty:
            dt = destroyed_df.copy()
            dt["lost_at"] = dt["last_seen_at"]
            dt["to_player_id"] = np.nan
            dt["to_player_name"] = None
            dt["to_alliance_id"] = np.nan
            dt["to_alliance_name"] = None
            dt["still_on_latest_map"] = False
            dt["reason"] = "Gone from latest map (last-known coords)"
            loss_parts.append(
                dt[
                    [
                        "village_id",
                        "village_name",
                        "x",
                        "y",
                        "population",
                        "lost_at",
                        "to_player_id",
                        "to_player_name",
                        "to_alliance_id",
                        "to_alliance_name",
                        "still_on_latest_map",
                        "reason",
                    ]
                ]
            )

        if not loss_parts:
            st.caption("No historical losses recorded for this alliance tag.")
        else:
            comb = pd.concat(loss_parts, ignore_index=True)
            comb["lost_at"] = pd.to_datetime(comb["lost_at"], errors="coerce")
            comb["to_player_id"] = (
                pd.to_numeric(comb["to_player_id"], errors="coerce").fillna(0).astype(int)
            )
            comb["to_player_name"] = comb["to_player_name"].fillna("").astype(str)
            comb["to_alliance_id"] = (
                pd.to_numeric(comb["to_alliance_id"], errors="coerce").fillna(0).astype(int)
            )
            comb["to_alliance_name"] = comb["to_alliance_name"].fillna("").astype(str)
            _on_map = np.array(comb["still_on_latest_map"].tolist(), dtype=bool)
            _aid_arr = comb["to_alliance_id"].to_numpy(dtype=int)
            _nm_strip = comb["to_alliance_name"].astype(str).str.strip().to_numpy()
            _lost_ally_lab = np.where(
                ~_on_map,
                "—",
                np.where(
                    _nm_strip != "",
                    _nm_strip,
                    np.where(
                        _aid_arr > 0,
                        "Alliance " + _aid_arr.astype(str),
                        "No alliance tag",
                    ),
                ),
            )
            _lost_ally_id = np.where(_on_map, _aid_arr, 0)
            disp = pd.DataFrame(
                {
                    "village": _village_name_link_series(
                        comb["village_name"], comb["village_id"], server.key
                    ),
                    "coords": _game_coords_link_series(
                        server.base_url, comb["x"].astype(int), comb["y"].astype(int)
                    ),
                    "on_latest_map": comb["still_on_latest_map"],
                    "population": comb["population"].astype(int),
                    "current_owner": _player_name_link_series(
                        comb["to_player_name"], comb["to_player_id"], server.key
                    ),
                    "lost_to_alliance": _alliance_name_link_series(
                        pd.Series(_lost_ally_lab, index=comb.index),
                        pd.Series(_lost_ally_id, index=comb.index),
                        server.key,
                    ),
                    "reason": comb["reason"],
                    "lost_at": comb["lost_at"],
                }
            ).sort_values("lost_at", ascending=False)
            _paginated_dataframe(
                disp,
                key=f"ally_loss_{tk}",
                width="stretch",
                hide_index=True,
                column_config={
                    **_link_column_coords_game(),
                    "village": st.column_config.LinkColumn(
                        "Village",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                    "current_owner": st.column_config.LinkColumn(
                        "Current owner",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                    "lost_to_alliance": st.column_config.LinkColumn(
                        "Lost to alliance (now)",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                },
            )


def _render_player_map_fragment(
    *, server_key: str, snapshot_id: int, player_id: int, player_name: str
) -> None:
    """Per-player relative map. Wrapped in `@st.fragment` so changing the
    player picker does NOT trigger a rerun of the whole script (e.g. it
    won't also re-render the standalone Map tab)."""
    idx = _map_index(server_key, snapshot_id)
    lost_df = player_villages_lost_df(server_key, player_id)
    destroyed_df = player_villages_destroyed_df(server_key, player_id)
    mine = idx[idx["player_id"] == int(player_id)]
    mine_ids = frozenset(int(v) for v in mine["village_id"].tolist()) if not mine.empty else frozenset()
    lost_ids = frozenset(int(v) for v in lost_df["village_id"].tolist()) if not lost_df.empty else frozenset()

    _render_three_tone_overlay_map(
        server_key=server_key,
        snapshot_id=snapshot_id,
        idx=idx,
        lost_ids=lost_ids,
        current_ids=mine_ids,
        destroyed_df=destroyed_df,
        caption=(
            "**Green:** villages they still own · **Red:** lost to someone else · "
            "**Yellow:** destroyed / disappeared from latest map (dot at **last-known** coords)."
        ),
        lost_layer_label="Lost — new owner (still on map)",
        current_layer_label="Current holdings",
        highlight_label=f"{player_name} — holdings & losses",
        plotly_key=f"map_player_{server_key}_{snapshot_id}_{player_id}",
        plot_height=_dash_chart_sizes().embedded_map,
    )


def _render_alliance_map_fragment(
    *,
    server: ServerConfig,
    snapshot_id: int,
    alliance_id: int,
    alliance_name: str,
) -> None:
    server_key = server.key
    idx = _map_index(server_key, snapshot_id)
    if idx.empty:
        st.info("No villages to map.")
        return
    aid = int(alliance_id)
    if aid <= 0:
        st.info("Semantic map needs a positive **alliance id** in data.")
        hl_ids = frozenset()
        render_world_map(
            server_key=server_key,
            snapshot_id=snapshot_id,
            idx=idx,
            hl_village_ids=hl_ids,
            highlight_label=alliance_name,
            palette_key=str(st.session_state["dash_map_palette"]),
            plotly_key=f"map_alliance_{server_key}_{snapshot_id}_{aid}",
            plot_height=_dash_chart_sizes().embedded_map,
        )
        return

    lost_df = alliance_villages_lost_df(server_key, aid)
    destroyed_df = alliance_villages_destroyed_df(server_key, aid)
    cur = idx[idx["alliance_id"] == aid]
    cur_ids = frozenset(int(v) for v in cur["village_id"].tolist()) if not cur.empty else frozenset()
    chief_ids, tag_loss_ids = _alliance_split_chiefed_and_tag_loss_ids(lost_df)

    _render_three_tone_overlay_map(
        server_key=server_key,
        snapshot_id=snapshot_id,
        idx=idx,
        lost_ids=tag_loss_ids,
        current_ids=cur_ids,
        destroyed_df=destroyed_df,
        caption=(
            "**Green:** current alliance villages · **Blue:** chiefed — still on the map "
            "under a new owner · **Yellow:** village still allied to the same owner but "
            "no longer shows this alliance tag · **Red:** dots = gone from the latest map "
            "(**last-known** tile)."
        ),
        chiefed_ids=chief_ids,
        chiefed_layer_label="Chiefed away (new owner)",
        lost_layer_label="Left alliance tag (same holder)",
        current_layer_label="Current alliance villages",
        highlight_label=f"{alliance_name} — footprint & losses",
        plotly_key=f"map_alliance_{server_key}_{snapshot_id}_{aid}",
        plot_height=_dash_chart_sizes().embedded_map,
        lost_marker_rgb=_PM_OFF_YELLOW,
        offline_marker_rgb=_PM_LOST_RED,
        offline_trace_name="Deleted — off latest map",
        offline_hover_note="deleted / off latest map",
    )
    _render_alliance_territory_tables(
        server=server,
        alliance_id=aid,
        lost_df=lost_df,
        destroyed_df=destroyed_df,
        key_suffix=f"dmap_{int(snapshot_id)}",
    )


def _render_world_map_fragment(*, server: ServerConfig, snapshot_id: int) -> None:
    """Standalone Map tab. Wrapped in `@st.fragment` so the radio/selectbox
    interactions only re-render *this* fragment instead of the whole page."""
    server_key = server.key
    idx = _map_index(server_key, snapshot_id)
    if idx.empty:
        st.info("No villages to map.")
        return

    mode = st.radio(
        "Highlight by",
        options=["Player", "Alliance", "Tribe", "Just show everyone"],
        horizontal=True,
        key="map_mode",
    )

    hl = idx.iloc[0:0]
    label = "World"
    picked_player_id: int | None = None

    if mode == "Player":
        opts = (
            idx.groupby("player_id")
            .agg(
                player_name=("player_name", "max"),
                tribe_name=("tribe_name", "max"),
                villages=("village_id", "count"),
            )
            .reset_index()
            .sort_values("villages", ascending=False)
        )
        opt_map = opts.set_index("player_id")
        picked_pid = st.selectbox(
            "Player to highlight",
            options=opts["player_id"].tolist(),
            format_func=lambda pid: (
                f"{opt_map.loc[pid, 'player_name']} "
                f"({opt_map.loc[pid, 'tribe_name']}, "
                f"{int(opt_map.loc[pid, 'villages'])} villages)"
            ),
            key="map_player_pick",
        )
        picked_player_id = int(picked_pid)
        hl = idx[idx["player_id"] == picked_player_id]
        label = str(opt_map.loc[picked_player_id, "player_name"])

    elif mode == "Alliance":
        ally_opts = (
            idx[idx["alliance_name"].fillna("") != ""]
            .groupby("alliance_name")
            .agg(
                villages=("village_id", "count"),
                members=("player_id", "nunique"),
            )
            .reset_index()
            .sort_values("villages", ascending=False)
        )
        if ally_opts.empty:
            st.info("No alliances in the latest snapshot.")
        else:
            ally_map = ally_opts.set_index("alliance_name")
            picked_ally = st.selectbox(
                "Alliance to highlight",
                options=ally_opts["alliance_name"].tolist(),
                format_func=lambda a: (
                    f"{a} "
                    f"({int(ally_map.loc[a, 'members'])} members, "
                    f"{int(ally_map.loc[a, 'villages'])} villages)"
                ),
                key="map_ally_pick",
            )
            hl = idx[idx["alliance_name"] == picked_ally]
            label = f"Alliance {picked_ally}"

    elif mode == "Tribe":
        tribes = sorted(idx["tribe_name"].dropna().unique().tolist())
        picked_tribe = st.selectbox(
            "Tribe to highlight", options=tribes, key="map_tribe_pick"
        )
        hl = idx[idx["tribe_name"] == picked_tribe]
        label = f"Tribe {picked_tribe}"

    else:
        label = "World (no highlight)"

    if mode == "Player" and picked_player_id is not None and not hl.empty:
        lost_df = player_villages_lost_df(server_key, picked_player_id)
        destroyed_df = player_villages_destroyed_df(server_key, picked_player_id)
        lost_ids = (
            frozenset(int(v) for v in lost_df["village_id"].tolist())
            if not lost_df.empty
            else frozenset()
        )
        cur_ids = frozenset(int(v) for v in hl["village_id"].tolist())
        _render_three_tone_overlay_map(
            server_key=server_key,
            snapshot_id=snapshot_id,
            idx=idx,
            lost_ids=lost_ids,
            current_ids=cur_ids,
            destroyed_df=destroyed_df,
            caption=(
                "**Green:** villages they still own · **Red:** lost to someone else · "
                "**Yellow:** destroyed / disappeared from latest map (dot at **last-known** coords)."
            ),
            lost_layer_label="Lost — new owner (still on map)",
            current_layer_label="Current holdings",
            highlight_label=f"{label} — holdings & losses",
            plotly_key=f"map_world_{server_key}_{snapshot_id}_p{picked_player_id}",
            plot_height=_dash_chart_sizes().full_map,
        )
    elif mode == "Alliance" and not hl.empty:
        _au = hl["alliance_id"].dropna().unique()
        aid_world = int(_au[0]) if len(_au) else 0
        if aid_world > 0:
            lost_df = alliance_villages_lost_df(server_key, aid_world)
            destroyed_df = alliance_villages_destroyed_df(server_key, aid_world)
            chief_ids, tag_loss_ids = _alliance_split_chiefed_and_tag_loss_ids(lost_df)
            cur_ids = frozenset(int(v) for v in hl["village_id"].tolist())
            _render_three_tone_overlay_map(
                server_key=server_key,
                snapshot_id=snapshot_id,
                idx=idx,
                lost_ids=tag_loss_ids,
                current_ids=cur_ids,
                destroyed_df=destroyed_df,
                caption=(
                    "**Green:** current alliance villages · **Blue:** chiefed — still on the map "
                    "under a new owner · **Yellow:** village still allied to the same owner but "
                    "no longer shows this alliance tag · **Red:** dots = gone from the latest map "
                    "(**last-known** tile)."
                ),
                chiefed_ids=chief_ids,
                chiefed_layer_label="Chiefed away (new owner)",
                lost_layer_label="Left alliance tag (same holder)",
                current_layer_label="Current alliance villages",
                highlight_label=f"{label} — footprint & losses",
                plotly_key=f"map_world_{server_key}_{snapshot_id}_a{aid_world}",
                plot_height=_dash_chart_sizes().full_map,
                lost_marker_rgb=_PM_OFF_YELLOW,
                offline_marker_rgb=_PM_LOST_RED,
                offline_trace_name="Deleted — off latest map",
                offline_hover_note="deleted / off latest map",
            )
            _render_alliance_territory_tables(
                server=server,
                alliance_id=aid_world,
                lost_df=lost_df,
                destroyed_df=destroyed_df,
                key_suffix=f"wmap_{int(snapshot_id)}",
            )
        else:
            hl_ids = frozenset(hl["village_id"].tolist())
            render_world_map(
                server_key=server_key,
                snapshot_id=snapshot_id,
                idx=idx,
                hl_village_ids=hl_ids,
                highlight_label=label,
                palette_key=str(st.session_state["dash_map_palette"]),
                plotly_key=f"map_world_{server_key}_{snapshot_id}",
                plot_height=_dash_chart_sizes().full_map,
            )
    else:
        hl_ids = frozenset(hl["village_id"].tolist()) if not hl.empty else frozenset()
        render_world_map(
            server_key=server_key,
            snapshot_id=snapshot_id,
            idx=idx,
            hl_village_ids=hl_ids,
            highlight_label=label,
            palette_key=str(st.session_state["dash_map_palette"]),
            plotly_key=f"map_world_{server_key}_{snapshot_id}",
            plot_height=_dash_chart_sizes().full_map,
        )

    with st.expander("Highlighted villages — full list", expanded=False):
        if hl.empty:
            st.caption("Pick a player / alliance / tribe to see their villages here.")
        else:
            h2 = hl[
                ["village_id", "village_name", "x", "y", "flag", "tribe_name",
                 "population", "player_name", "alliance_name"]
            ].rename(
                columns={
                    "tribe_name": "tribe",
                }
            ).copy()
            h2 = _apply_coords_game_links(h2, server.base_url)
            h2["village"] = _village_name_link_series(
                hl["village_name"], hl["village_id"], server_key
            )
            h2 = h2.drop(columns=["village_name"])
            h2["player"] = _player_name_link_series(
                hl["player_name"], hl["player_id"], server_key
            )
            h2["alliance"] = _alliance_name_link_series(
                hl["alliance_name"], hl["alliance_id"], server_key
            )
            h2 = h2.drop(columns=["player_name", "alliance_name"])
            h2 = h2[
                [
                    "village_id",
                    "village",
                    "coords",
                    "flag",
                    "tribe",
                    "population",
                    "player",
                    "alliance",
                ]
            ]
            _paginated_dataframe(
                h2,
                key=f"map_hl_{server_key}_{int(snapshot_id)}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_config_village_player(),
            )


def _render_custom_maps_fragment(*, server_key: str, snapshot_id: int) -> None:
    """Saved map presets: center, optional square viewport, highlight mode."""
    st.caption(
        "Presets are stored in **config/custom_maps.yaml** (per project). "
        "**View radius** 0 = full symmetric world; otherwise a square window "
        "(half-side in tiles) around **Center x/y**."
    )
    idx = _map_index(server_key, snapshot_id)
    if idx.empty:
        st.info("No villages to map.")
        return

    presets = load_custom_maps()
    preset: CustomMapPreset | None = None

    if presets:
        hdr = st.columns([3, 1])
        with hdr[0]:
            sel_i = st.selectbox(
                "Saved map",
                options=list(range(len(presets))),
                format_func=lambda i: presets[i].name,
                key="custom_map_pick",
            )
            preset = presets[int(sel_i)]
        with hdr[1]:
            st.write("")
            st.write("")
            if st.button("Delete selected", key="custom_map_delete"):
                keep = [p for p in presets if p.id != preset.id]
                save_custom_maps(keep)
                st.rerun()

    if preset is not None:
        hl_layers_live = resolve_highlight_layers(idx, preset)
        hl_union = resolve_highlight_village_ids(idx, preset)
        lbl_extra = preset.name
        if hl_layers_live:
            lbl_extra += " · " + " · ".join(lab for _, lab in hl_layers_live[:12])
            if len(hl_layers_live) > 12:
                lbl_extra += " …"
        vp: tuple[int, int, int] | None = None
        if preset.view_radius > 0:
            vp = (preset.center_x, preset.center_y, preset.view_radius)
        render_world_map(
            server_key=server_key,
            snapshot_id=snapshot_id,
            idx=idx,
            hl_village_ids=hl_union,
            hl_layers=hl_layers_live if hl_layers_live else None,
            highlight_label=lbl_extra,
            palette_key=str(st.session_state["dash_map_palette"]),
            plotly_key=f"map_custom_{server_key}_{snapshot_id}_{preset.id}",
            viewport=vp,
            plot_height=_dash_chart_sizes().full_map,
        )
    else:
        st.info("No saved custom maps yet — add one below.")

    st.markdown("##### New saved map")
    with st.form("custom_map_create", clear_on_submit=True):
        name = st.text_input("Display name", placeholder="My front line")
        c1, c2, c3 = st.columns(3)
        cx = c1.number_input("Center x", value=0, step=1, key="cm_cx")
        cy = c2.number_input("Center y", value=0, step=1, key="cm_cy")
        vr = c3.number_input(
            "View radius (0 = full world)",
            min_value=0,
            value=0,
            step=1,
            key="cm_vr",
            help="Half-side of the square viewport in map tiles.",
        )
        mode = st.radio(
            "Highlight",
            options=["everyone", "multi", "tribe"],
            horizontal=True,
            format_func=lambda m: (
                {"everyone": "Everyone", "multi": "Players & alliances (multi)", "tribe": "Tribe"}.get(
                    m, m
                )
            ),
            key="cm_mode",
        )

        sel_alliance_ids: list[int] = []
        sel_player_ids: list[int] = []
        tribe_name = ""

        if mode == "multi":
            st.caption(
                "Pick any number of **alliances** and/or **players** (add/remove anytime before save). "
                "Each group gets a **different color**; villages already painted by an alliance group "
                "are not duplicated for a player group."
            )
            ally_summ = (
                idx[idx["alliance_id"] > 0]
                .groupby("alliance_id")
                .agg(
                    alliance_name=("alliance_name", "max"),
                    villages=("village_id", "count"),
                    members=("player_id", "nunique"),
                )
                .reset_index()
                .sort_values("villages", ascending=False)
            )
            if not ally_summ.empty:
                am = ally_summ.set_index("alliance_id")
                sel_alliance_ids = [
                    int(x)
                    for x in st.multiselect(
                        "Alliances",
                        options=ally_summ["alliance_id"].tolist(),
                        format_func=lambda aid: (
                            f"{am.loc[int(aid), 'alliance_name']} "
                            f"({int(am.loc[int(aid), 'members'])} members, "
                            f"{int(am.loc[int(aid), 'villages'])} villages)"
                        ),
                        key="cm_alliances_multi",
                    )
                ]
            else:
                st.caption("No alliances found in this snapshot — you can still pick players.")

            pl_opts = (
                idx.groupby("player_id")
                .agg(
                    player_name=("player_name", "max"),
                    tribe_name=("tribe_name", "max"),
                    villages=("village_id", "count"),
                )
                .reset_index()
                .sort_values("villages", ascending=False)
            )
            opt_map_p = pl_opts.set_index("player_id")
            sel_player_ids = [
                int(x)
                for x in st.multiselect(
                    "Players",
                    options=pl_opts["player_id"].tolist(),
                    format_func=lambda pid: (
                        f"{opt_map_p.loc[int(pid), 'player_name']} "
                        f"({opt_map_p.loc[int(pid), 'tribe_name']}, "
                        f"{int(opt_map_p.loc[int(pid), 'villages'])} villages)"
                    ),
                    key="cm_players_multi",
                )
            ]
        elif mode == "tribe":
            tribes = sorted(idx["tribe_name"].dropna().unique().tolist())
            tribe_name = st.selectbox("Tribe", options=tribes, key="cm_tribe")

        submitted = st.form_submit_button("Save map")
        if submitted:
            nm = (name or "").strip()
            if not nm:
                st.warning("Please enter a display name.")
            elif mode == "tribe" and not (tribe_name or "").strip():
                st.warning("Pick a tribe or choose **Everyone**.")
            else:
                fresh = load_custom_maps()
                _a_save = [int(a) for a in sel_alliance_ids if int(a) > 0]
                _p_save = [int(p) for p in sel_player_ids if int(p) > 0]
                fresh.append(
                    CustomMapPreset(
                        id=new_preset_id(nm),
                        name=nm,
                        center_x=int(cx),
                        center_y=int(cy),
                        view_radius=max(0, int(vr)),
                        highlight_mode=mode,
                        player_id=_p_save[0] if len(_p_save) == 1 else 0,
                        alliance_id=_a_save[0] if len(_a_save) == 1 else 0,
                        tribe_name=tribe_name if mode == "tribe" else "",
                        player_ids=_p_save if mode == "multi" else [],
                        alliance_ids=_a_save if mode == "multi" else [],
                    )
                )
                save_custom_maps(fresh)
                st.rerun()


# ---------------------------------------------------------------------------
# Map selection → URL (consumes marker before pinned-profile reads query params)
# ---------------------------------------------------------------------------

_map_pending = st.session_state.pop("_pending_map_village_detail", None)
if _map_pending is not None:
    _mp_sk, _mp_vid = _map_pending
    if (
        isinstance(_mp_sk, str)
        and _mp_sk == server.key
        and isinstance(_mp_vid, int)
        and _mp_vid > 0
    ):
        st.query_params["server_key"] = server.key
        st.query_params["village_detail"] = str(_mp_vid)
        for _mp_k in ("player_detail", "alliance_detail"):
            if _mp_k in st.query_params:
                del st.query_params[_mp_k]


# ---------------------------------------------------------------------------
# Deep links: ?village_detail=&player_detail=&alliance_detail=&server_key=
# ---------------------------------------------------------------------------

_q_sk = st.query_params.get("server_key")
if _q_sk == server.key and not snapshots_df.empty:
    _latest_snap = int(snapshots_df.iloc[0]["id"])
    _has_pin = any(
        st.query_params.get(k)
        for k in ("village_detail", "player_detail", "alliance_detail")
    )
    if _has_pin:
        st.subheader("Pinned profile")
        st.caption(
            "Opened from a **map tap/click** (pinned in this tab) or a table link on a "
            "**Player** / **Alliance** / **Village** name (often a new tab). "
            "Click below to clear query params."
        )
        if st.button("Clear pinned views", key="clear_all_detail_pins"):
            _clear_all_detail_params()
            st.rerun()

    if st.query_params.get("village_detail"):
        try:
            _deep_vid = int(st.query_params["village_detail"])
        except (TypeError, ValueError):
            _deep_vid = None
        if _deep_vid is not None:
            st.markdown("##### Village")
            render_village_detail_block(server, _deep_vid)
            st.divider()

    if st.query_params.get("player_detail"):
        try:
            _deep_pid = int(st.query_params["player_detail"])
        except (TypeError, ValueError):
            _deep_pid = None
        if _deep_pid is not None:
            st.markdown("##### Player")
            render_player_detail_block(
                server, _deep_pid, snapshot_id=_latest_snap
            )
            st.divider()

    if st.query_params.get("alliance_detail"):
        try:
            _deep_aid = int(st.query_params["alliance_detail"])
        except (TypeError, ValueError):
            _deep_aid = None
        if _deep_aid is not None:
            st.markdown("##### Alliance")
            render_alliance_detail_block(
                server, _deep_aid, snapshot_id=_latest_snap
            )
            st.divider()


# ---------------------------------------------------------------------------
# Dashboard watchlists + leaderboards tab (`servers.json` settings)
# ---------------------------------------------------------------------------

def _resolve_watch_player_targets(
    server_key: str, entries: tuple[int | str, ...]
) -> tuple[list[int], list[str]]:
    if not entries:
        return [], []
    conn = get_conn(str(DB_PATH))
    warns: list[str] = []
    ids: list[int] = []
    seen: set[int] = set()
    for e in entries:
        q = str(int(e)) if isinstance(e, int) else str(e).strip()
        m = analyzer.find_players(conn, server_key, q, limit=30)
        if not m:
            warns.append(f"Watch player `{e}` — not found in latest snapshot.")
            continue
        if len(m) > 1 and not (
            isinstance(e, int) or (isinstance(e, str) and str(e).strip().isdigit())
        ):
            warns.append(
                f"Watch `{e}` — multiple name hits; pinned **{m[0][1]}** (player id={m[0][0]})."
            )
        pid = m[0][0]
        if pid not in seen:
            seen.add(pid)
            ids.append(pid)
    return ids, warns


def _resolve_watch_alliance_targets(
    server_key: str, entries: tuple[int | str, ...]
) -> tuple[list[int], list[str]]:
    if not entries:
        return [], []
    conn = get_conn(str(DB_PATH))
    warns: list[str] = []
    ids: list[int] = []
    seen: set[int] = set()
    for e in entries:
        q = str(int(e)) if isinstance(e, int) else str(e).strip()
        m = analyzer.find_alliances(conn, server_key, q, limit=30)
        if not m:
            warns.append(f"Watch alliance `{e}` — not found in latest snapshot.")
            continue
        if len(m) > 1 and not (
            isinstance(e, int) or (isinstance(e, str) and str(e).strip().isdigit())
        ):
            warns.append(
                f"Watch `{e}` — multiple alliance hits; pinned **{m[0][1]}** "
                f"(alliance id={m[0][0]})."
            )
        aid = m[0][0]
        if aid not in seen:
            seen.add(aid)
            ids.append(aid)
    return ids, warns


def render_dashboard_watch_pins(srv: ServerConfig, app_cfg: AppConfig) -> None:
    pf = app_cfg.settings.dashboard_follow_players
    af = app_cfg.settings.dashboard_follow_alliances
    if not pf and not af:
        return
    p_ids, pw = _resolve_watch_player_targets(srv.key, pf)
    a_ids, aw = _resolve_watch_alliance_targets(srv.key, af)
    for w in pw + aw:
        st.warning(w)

    df_p = players_dataframe(srv.key)
    df_a = alliances_dataframe(srv.key)

    st.markdown("##### Watching (from config)")
    shown_any = False
    if p_ids:
        pins = df_p[df_p["player_id"].isin(p_ids)].copy()
        pins = pins.sort_values("population", ascending=False)
        if pins.empty:
            st.caption(
                "Player watchlist: no matching rows in rankings (verify ids/names in YAML)."
            )
        else:
            shown_any = True
            show = pins[
                ["player_id", "tribe_name", "villages", "population",
                 "pop_delta", "is_new"]
            ].rename(columns={"tribe_name": "tribe", "pop_delta": "Δ pop"})
            show.insert(
                1,
                "player",
                _player_name_link_series(pins["player_name"], pins["player_id"], srv.key),
            )
            show.insert(
                3,
                "alliance",
                _alliance_name_link_series(
                    pins["alliance_name"].fillna(""),
                    pins["alliance_id"],
                    srv.key,
                ),
            )
            _paginated_dataframe(
                show,
                key=f"watch_players_{srv.key}",
                width="stretch",
                hide_index=True,
                column_config={
                    "player": st.column_config.LinkColumn(
                        "player",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                    "alliance": st.column_config.LinkColumn(
                        "alliance",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                },
            )

    if a_ids:
        ain = df_a[df_a["alliance_id"].isin(a_ids)].copy()
        ain = ain.sort_values("population", ascending=False)
        if ain.empty:
            st.caption(
                "Alliance watchlist: no matching rows (verify ids/tag substrings in YAML)."
            )
        else:
            shown_any = True
            ashow = ain[
                ["alliance_id", "members", "villages", "population",
                 "pop_delta", "members_delta", "is_new"]
            ].rename(
                columns={"pop_delta": "Δ pop", "members_delta": "Δ members"}
            )
            ashow.insert(
                1,
                "alliance",
                _alliance_name_link_series(
                    ain["alliance_name"].fillna(""),
                    ain["alliance_id"],
                    srv.key,
                ),
            )
            _paginated_dataframe(
                ashow,
                key=f"watch_alliances_{srv.key}",
                width="stretch",
                hide_index=True,
                column_config={
                    "alliance": st.column_config.LinkColumn(
                        "alliance",
                        display_text=_LINK_LABEL_FRAGMENT_RE,
                        width="medium",
                    ),
                },
            )

    if not shown_any and (p_ids or a_ids):
        st.caption("Watchlists resolved but no dataframe rows matched.")
    elif not p_ids and not a_ids and (pf or af):
        st.caption("Configure `dashboard_follow_players` / `dashboard_follow_alliances`.")


def render_leaderboards_top_twenty(srv: ServerConfig) -> None:
    n = LB_LEADERBOARD_ROWS
    kwa = _leaderboard_pagination_kwargs()

    st.caption(
        f"**Latest** snapshot (+ **Δ vs previous** where available). Showing up to "
        f"**{n}** ranked rows per table; pagination defaults load the full slice. "
        "Needs ≥2 snapshots for delta-driven boards."
    )
    df_p = players_dataframe(srv.key)
    df_a = alliances_dataframe(srv.key)
    df_v = villages_dataframe(srv.key)
    gfs = villages_top_by_growth(srv.key, limit=n)
    lfs = villages_top_by_loss(srv.key, limit=n)

    if df_p.empty and df_a.empty and df_v.empty:
        st.info("No leaderboard data.")
        return

    with st.expander("Players · population & villages", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f":blue[**Top {n} by population**]")
            p1 = df_p.head(n).copy()
            if p1.empty:
                st.caption("—")
            else:
                t = p1.rename(columns={"tribe_name": "tribe", "pop_delta": "Δ pop",
                                       "villages_delta": "Δ vil"}).copy()
                t.insert(1, "player", _player_name_link_series(
                    p1["player_name"], p1["player_id"], srv.key))
                t.insert(2, "alliance", _alliance_name_link_series(
                    p1["alliance_name"].fillna(""), p1["alliance_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "alliance", "tribe", "villages",
                       "population", "Δ pop", "Δ vil", "is_new"]],
                    key=f"lb_p_pop_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_players_tab(),
                    **kwa,
                )
        with c2:
            st.markdown(f":blue[**Top {n} by village count**]")
            pv = df_p.sort_values(["villages", "population"], ascending=False).head(n).copy()
            if pv.empty:
                st.caption("—")
            else:
                t = pv.rename(columns={"tribe_name": "tribe", "pop_delta": "Δ pop",
                                       "villages_delta": "Δ vil"}).copy()
                t.insert(1, "player", _player_name_link_series(
                    pv["player_name"], pv["player_id"], srv.key))
                t.insert(2, "alliance", _alliance_name_link_series(
                    pv["alliance_name"].fillna(""), pv["alliance_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "alliance", "tribe", "villages",
                       "population", "Δ pop", "Δ vil", "is_new"]],
                    key=f"lb_p_vil_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_players_tab(),
                    **kwa,
                )

    with st.expander("Players · deltas & newcomers", expanded=True):
        r1, r2, r3 = st.columns(3)
        with r1:
            st.markdown(f":green[**Top {n} population gain**] _(vs previous)_")
            gd = df_p.dropna(subset=["pop_delta"]).nlargest(n, "pop_delta").copy()
            if gd.empty:
                st.caption("No deltas yet.")
            else:
                t = gd.rename(columns={"tribe_name": "tribe"})
                t.insert(1, "player", _player_name_link_series(
                    gd["player_name"], gd["player_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "tribe", "villages", "population",
                       "pop_delta", "is_new"]].rename(columns={"pop_delta": "Δ pop"}),
                    key=f"lb_p_grow_{srv.key}",
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_lb_player(),
                    **kwa,
                )
        with r2:
            st.markdown(f":orange[**Brand-new accounts**] _(Δ villages from 0)_")
            nw = df_p[df_p["is_new"] == True].copy()  # noqa: E712
            nw = nw.sort_values("population", ascending=False).head(n)
            if nw.empty:
                st.caption("None since last snapshot (or single snapshot stored).")
            else:
                t = nw.rename(columns={"tribe_name": "tribe"})
                t.insert(1, "player", _player_name_link_series(
                    nw["player_name"], nw["player_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "tribe", "villages", "population"]],
                    key=f"lb_p_new_{srv.key}",
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_lb_player(),
                    **kwa,
                )
        with r3:
            st.markdown(f":red[**Top {n} population loss**] _(vs previous)_")
            ploss = df_p.dropna(subset=["pop_delta"]).nsmallest(n, "pop_delta").copy()
            if ploss.empty:
                st.caption("No deltas yet.")
            else:
                t = ploss.rename(columns={"tribe_name": "tribe"})
                t.insert(1, "player", _player_name_link_series(
                    ploss["player_name"], ploss["player_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "tribe", "villages", "population",
                       "pop_delta", "is_new"]].rename(columns={"pop_delta": "Δ pop"}),
                    key=f"lb_p_ploss_{srv.key}",
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_lb_player(),
                    **kwa,
                )

        st.divider()
        e1, e2 = st.columns(2)
        with e1:
            st.markdown(f":green[**Top {n} new village slots**] _(Δ villages)_")
            vs = df_p.dropna(subset=["villages_delta"]).nlargest(n, "villages_delta").copy()
            if vs.empty:
                st.caption("No village-slot deltas.")
            else:
                t = vs.rename(columns={"tribe_name": "tribe", "pop_delta": "Δ pop",
                                       "villages_delta": "Δ vil"})
                t.insert(1, "player", _player_name_link_series(
                    vs["player_name"], vs["player_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "tribe", "villages", "population",
                       "Δ pop", "Δ vil", "is_new"]],
                    key=f"lb_p_vdmax_{srv.key}",
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_lb_player(),
                    **kwa,
                )
        with e2:
            st.markdown(f":red[**Top {n} village-slot drops**] _(Δ villages)_")
            vs2 = df_p.dropna(subset=["villages_delta"]).nsmallest(n, "villages_delta").copy()
            if vs2.empty:
                st.caption("No village-slot deltas.")
            else:
                t = vs2.rename(columns={"tribe_name": "tribe", "pop_delta": "Δ pop",
                                        "villages_delta": "Δ vil"})
                t.insert(1, "player", _player_name_link_series(
                    vs2["player_name"], vs2["player_id"], srv.key))
                _paginated_dataframe(
                    t[["#", "player", "tribe", "villages", "population",
                       "Δ pop", "Δ vil", "is_new"]],
                    key=f"lb_p_vdmin_{srv.key}",
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_lb_player(),
                    **kwa,
                )

    with st.expander("Players · avg population / village", expanded=True):
        ap = df_p[df_p["villages"] >= 2].copy()
        if ap.empty:
            st.caption("Need players with ≥2 villages.")
        else:
            ap["_avg"] = (ap["population"] / ap["villages"].replace(0, 1)).round(1)
            ap = ap.nlargest(n, "_avg")
            t = ap.rename(columns={"tribe_name": "tribe", "_avg": "avg pop/vil"})
            st.markdown(f":violet[**Top {n} by avg pop/village**] _(≥2 villages)_")
            t.insert(1, "player", _player_name_link_series(
                ap["player_name"], ap["player_id"], srv.key))
            _paginated_dataframe(
                t[["#", "player", "tribe", "villages", "population",
                   "avg pop/vil"]],
                key=f"lb_p_avg_{srv.key}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_lb_player(),
                **kwa,
            )

    with st.expander("Alliances · rankings & deltas", expanded=True):
        a1, a2, a3 = st.columns(3)
        with a1:
            st.markdown(f":blue[**Top {n} — alliance population**]")
            x = df_a.head(n).copy()
            if not x.empty:
                x.insert(1, "alliance", _alliance_name_link_series(
                    x["alliance_name"], x["alliance_id"], srv.key))
                _paginated_dataframe(
                    x[["#", "alliance", "members", "villages", "population",
                       "pop_delta", "members_delta", "is_new"]].rename(
                        columns={
                            "pop_delta": "Δ pop",
                            "members_delta": "Δ members",
                        }
                    ),
                    key=f"lb_a_pop_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_alliance_tab(),
                    **kwa,
                )
            else:
                st.caption("—")
        with a2:
            st.markdown(f":blue[**Top {n} — member count**]")
            xm = df_a.sort_values(["members", "population"], ascending=False).head(n).copy()
            if not xm.empty:
                xm.insert(1, "alliance", _alliance_name_link_series(
                    xm["alliance_name"], xm["alliance_id"], srv.key))
                _paginated_dataframe(
                    xm[["#", "alliance", "members", "villages",
                        "population", "members_delta"]].rename(
                            columns={"members_delta": "Δ members"}
                        ),
                    key=f"lb_a_mem_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_alliance_tab(),
                    **kwa,
                )
            else:
                st.caption("—")
        with a3:
            st.markdown(f":green[**Top {n} — population gained**] _(vs previous)_")
            ag = df_a.dropna(subset=["pop_delta"]).nlargest(n, "pop_delta").copy()
            if not ag.empty:
                ag.insert(1, "alliance", _alliance_name_link_series(
                    ag["alliance_name"], ag["alliance_id"], srv.key))
                _paginated_dataframe(
                    ag[["#", "alliance", "population", "pop_delta"]].rename(
                        columns={"pop_delta": "Δ pop"}
                    ),
                    key=f"lb_a_dpop_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_alliance_tab(),
                    **kwa,
                )
            else:
                st.caption("No deltas.")

        st.divider()
        b1, b2 = st.columns(2)
        with b1:
            st.markdown(f":red[**Top {n} — population lost**] _(vs previous)_")
            al = df_a.dropna(subset=["pop_delta"]).nsmallest(n, "pop_delta").copy()
            if al.empty:
                st.caption("No deltas.")
            else:
                al.insert(1, "alliance", _alliance_name_link_series(
                    al["alliance_name"], al["alliance_id"], srv.key))
                _paginated_dataframe(
                    al[["#", "alliance", "population", "pop_delta"]].rename(
                        columns={"pop_delta": "Δ pop"}
                    ),
                    key=f"lb_a_ploss_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_alliance_tab(),
                    **kwa,
                )
        with b2:
            st.markdown(f":green[**Top {n} — members gained**] _(vs previous)_")
            mg = df_a.dropna(subset=["members_delta"]).nlargest(n, "members_delta").copy()
            if mg.empty:
                st.caption("No member deltas.")
            else:
                mg.insert(1, "alliance", _alliance_name_link_series(
                    mg["alliance_name"], mg["alliance_id"], srv.key))
                _paginated_dataframe(
                    mg[["#", "alliance", "members", "members_delta"]].rename(
                        columns={"members_delta": "Δ members"}
                    ),
                    key=f"lb_a_mdmax_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config=_link_column_config_alliance_tab(),
                    **kwa,
                )

    with st.expander("Villages · giants, climbers, losers", expanded=True):
        v1, v2, v3 = st.columns(3)
        with v1:
            st.markdown(f":blue[**Top {n} — village population**]")
            topv = df_v.head(n).copy()
            if topv.empty:
                st.caption("—")
            else:
                topv["_gc"] = _game_coords_link_series(
                    srv.base_url, topv["x"], topv["y"]
                )
                topv.insert(
                    1,
                    "village",
                    _village_name_link_series(
                        topv["village_name"], topv["village_id"], srv.key
                    ),
                )
                _paginated_dataframe(
                    topv[[
                        "#", "village", "_gc", "tribe_name", "player_name",
                        "population", "pop_delta", "flag_label",
                    ]].rename(
                        columns={
                            "_gc": "coords",
                            "tribe_name": "tribe",
                            "population": "pop",
                            "pop_delta": "Δ",
                            "flag_label": "flag",
                        }
                    ),
                    key=f"lb_v_pop_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config={
                        **_link_column_coords_game(),
                        "village": st.column_config.LinkColumn(
                            "village",
                            display_text=_LINK_LABEL_FRAGMENT_RE,
                            width="medium",
                        ),
                    },
                    **kwa,
                )
        with v2:
            st.markdown(f":green[**Top {n} — growth**] _(vs previous)_")
            if gfs.empty:
                st.caption("—")
            else:
                gfs2 = gfs.copy()
                gfs2["_gc"] = _game_coords_link_series(srv.base_url, gfs2["x"], gfs2["y"])
                gfs2.insert(
                    1,
                    "village",
                    _village_name_link_series(
                        gfs2["village_name"], gfs2["village_id"], srv.key
                    ),
                )
                _paginated_dataframe(
                    gfs2[[
                        "rank", "village", "_gc", "population", "pop_delta",
                        "player_name",
                    ]].rename(
                        columns={
                            "rank": "#",
                            "_gc": "coords",
                            "pop_delta": "Δ",
                        }
                    ),
                    key=f"lb_v_gr_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config={
                        **_link_column_coords_game(),
                        "village": st.column_config.LinkColumn(
                            "village",
                            display_text=_LINK_LABEL_FRAGMENT_RE,
                            width="medium",
                        ),
                    },
                    **kwa,
                )
        with v3:
            st.markdown(f":red[**Top {n} — population loss**] _(vs previous)_")
            if lfs.empty:
                st.caption("—")
            else:
                l2 = lfs.copy()
                l2["_gc"] = _game_coords_link_series(srv.base_url, l2["x"], l2["y"])
                l2.insert(
                    1,
                    "village",
                    _village_name_link_series(
                        l2["village_name"], l2["village_id"], srv.key
                    ),
                )
                _paginated_dataframe(
                    l2[[
                        "rank", "village", "_gc", "population", "pop_delta",
                        "player_name",
                    ]].rename(
                        columns={
                            "rank": "#",
                            "_gc": "coords",
                            "pop_delta": "Δ",
                        }
                    ),
                    key=f"lb_v_loss_{srv.key}",
                    width="stretch", hide_index=True,
                    column_config={
                        **_link_column_coords_game(),
                        "village": st.column_config.LinkColumn(
                            "village",
                            display_text=_LINK_LABEL_FRAGMENT_RE,
                            width="medium",
                        ),
                    },
                    **kwa,
                )
# ---------------------------------------------------------------------------
# Tabs (toolbar-styled via _apply_minimal_shell CSS)
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="dash-toolbar-divider" aria-hidden="true"></div>',
    unsafe_allow_html=True,
)

(
    tab_overview,
    tab_top20,
    tab_players,
    tab_alliances,
    tab_villages,
    tab_map,
    tab_custom_maps,
    tab_inactives,
    tab_natars,
    tab_nature,
    tab_events,
    tab_snapshots,
) = st.tabs(
    [
        ":bar_chart: Overview",
        ":trophy: Leaderboards",
        ":bust_in_silhouette: Players",
        ":crossed_swords: Alliances",
        ":house: Villages",
        ":world_map: Map",
        ":round_pushpin: Custom",
        ":zzz: Inactives",
        "Natars (NPC)",
        "Nature",
        ":sparkles: Events",
        ":floppy_disk: Snapshots",
    ]
)


# ---------------------------- Overview ------------------------------------- #

with tab_overview:
    st.subheader(f"Overview — {server.name}")
    history = server_history_summary(server.key)
    latest = history.iloc[-1] if not history.empty else None

    cols = st.columns(4)
    cols[0].metric("Villages",        f"{int(latest['villages']):,}"   if latest is not None else "0")
    cols[1].metric("Active players",  f"{int(latest['players']):,}"    if latest is not None else "0")
    cols[2].metric("Alliances",       f"{int(latest['alliances']):,}"  if latest is not None else "0")
    cols[3].metric("Total population", f"{int(latest['population']):,}" if latest is not None else "0")

    render_dashboard_watch_pins(server, cfg)

    if len(history) >= 2:
        st.markdown("##### Population over time")
        sz = _dash_chart_sizes()
        _dash_line_chart(
            history.set_index("fetched_at")[["population"]],
            height=sz.overview_line,
        )

        st.markdown("##### Players & alliances over time")
        _dash_line_chart(
            history.set_index("fetched_at")[["players", "alliances"]],
            height=sz.overview_line,
        )
    else:
        st.info(
            "Only one snapshot stored. Charts will appear once a second snapshot is collected."
        )

    conn = get_conn(str(DB_PATH))
    latest_id = int(snapshots_df.iloc[0]["id"])
    stats = analyzer.compute_snapshot_stats(conn, latest_id, top_n=20)

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.markdown("##### Tribe distribution")
        tribes_df = pd.DataFrame(
            {"tribe": list(stats.tribe_counts.keys()), "villages": list(stats.tribe_counts.values())}
        )
        ob = _dash_chart_sizes().overview_bar
        _dash_bar_chart(
            tribes_df.set_index("tribe")[["villages"]],
            height=ob,
        )

    with col_right:
        st.markdown("##### Top 20 alliances by population")
        top_a = pd.DataFrame(stats.top_alliances)
        if not top_a.empty:
            ob = _dash_chart_sizes().overview_bar
            _dash_bar_chart(
                top_a.set_index("alliance_name")[["population"]],
                height=ob,
                x_tick_angle=-45,
            )

            tbl = top_a.reset_index(drop=True)
            tbl.insert(0, "#", tbl.index + 1)
            tbl.insert(
                2,
                "alliance",
                _alliance_name_link_series(
                    tbl["alliance_name"], tbl["alliance_id"], server.key
                ),
            )
            tbl = tbl.drop(columns=["alliance_name"])
            st.dataframe(
                tbl[["#", "alliance", "alliance_id", "members", "villages", "population"]],
                width="stretch",
                hide_index=True,
                column_config={
                    **_link_column_config_alliance_tab(),
                    "#": st.column_config.NumberColumn("#", format="%d", width="small"),
                    "alliance_id": st.column_config.NumberColumn(
                        "id", format="%d", width="small"
                    ),
                    "members": st.column_config.NumberColumn("members", format="%d"),
                    "villages": st.column_config.NumberColumn("villages", format="%d"),
                    "population": st.column_config.NumberColumn(
                        "population", format="%d", width="medium"
                    ),
                },
            )
        else:
            st.caption("No alliances in the latest snapshot.")
# ---------------------------- Leaderboards tab ------------------------------ #

with tab_top20:
    st.subheader(f"Leaderboards — {server.name}")
    render_leaderboards_top_twenty(server)


# ---------------------------- Players -------------------------------------- #

with tab_players:
    st.subheader(f"Players — {server.name}")
    df = players_dataframe(server.key)
    if df.empty:
        st.info("No players to show.")
    else:
        cols = st.columns([2, 1, 1])
        name_filter = cols[0].text_input("Filter by player name (substring)", "")
        tribes = sorted(df["tribe_name"].unique().tolist())
        tribe_filter = cols[1].multiselect("Tribe", options=tribes, default=tribes)
        alliances = sorted(df["alliance_name"].fillna("").unique().tolist())
        alliance_filter = cols[2].multiselect(
            "Alliance", options=alliances, default=alliances
        )

        view_df = df.copy()
        if name_filter:
            view_df = view_df[view_df["player_name"].str.contains(name_filter, case=False, na=False)]
        view_df = view_df[view_df["tribe_name"].isin(tribe_filter)]
        view_df = view_df[view_df["alliance_name"].fillna("").isin(alliance_filter)]

        base_cols = [
            "#", "player_id", "tribe_name",
            "villages", "population", "pop_delta", "villages_delta", "is_new",
        ]
        plist = view_df[base_cols].rename(
            columns={
                "tribe_name": "tribe",
                "pop_delta": "Δ pop",
                "villages_delta": "Δ vil",
            }
        ).copy()
        plist.insert(
            2,
            "player",
            _player_name_link_series(
                view_df["player_name"], view_df["player_id"], server.key
            ),
        )
        plist.insert(
            3,
            "alliance",
            _alliance_name_link_series(
                view_df["alliance_name"], view_df["alliance_id"], server.key
            ),
        )
        _paginated_dataframe(
            plist,
            key=f"tbl_players_{server.key}",
            width="stretch",
            hide_index=True,
            column_config=_link_column_config_players_tab(),
        )
        st.caption(
            "Click **Player** or **Alliance** names for pinned profile views in a **new browser tab** "
            "(same dashboard URL with query params)."
        )

        st.markdown("---")
        st.markdown("##### Player detail")
        if view_df.empty:
            st.caption("No players match the current filters.")
        else:
            options = view_df["player_id"].tolist()

            def player_label(pid: int) -> str:
                row = df[df["player_id"] == pid].iloc[0]
                return f"{row['player_name']} (id={pid}, {row['tribe_name']})"

            picked = st.selectbox(
                "Pick a player to view their full history",
                options=options,
                format_func=player_label,
                key="player_pick",
            )
            render_player_detail_block(
                server,
                int(picked),
                snapshot_id=int(snapshots_df.iloc[0]["id"]),
            )


# ---------------------------- Alliances ------------------------------------ #

with tab_alliances:
    st.subheader(f"Alliances — {server.name}")
    df = alliances_dataframe(server.key)
    if df.empty:
        st.info("No alliances to show.")
    else:
        name_filter = st.text_input("Filter by alliance name (substring)", "", key="ally_filter")
        view_df = df.copy()
        if name_filter:
            view_df = view_df[view_df["alliance_name"].str.contains(name_filter, case=False, na=False)]

        alist = view_df[
            ["#", "alliance_id", "members", "villages",
             "population", "pop_delta", "members_delta", "is_new"]
        ].rename(
            columns={
                "pop_delta": "Δ pop",
                "members_delta": "Δ mem",
            }
        ).copy()
        alist.insert(
            2,
            "alliance",
            _alliance_name_link_series(
                view_df["alliance_name"], view_df["alliance_id"], server.key
            ),
        )
        _paginated_dataframe(
            alist,
            key=f"tbl_alliances_{server.key}",
            width="stretch",
            hide_index=True,
            column_config=_link_column_config_alliance_tab(),
        )
        st.caption(
            "Click the **Alliance** name for a pinned profile view in a **new browser tab**."
        )

        st.markdown("---")
        st.markdown("##### Alliance detail")
        if view_df.empty:
            st.caption("No alliances match the current filter.")
        else:
            options = view_df["alliance_id"].tolist()

            def ally_label(aid: int) -> str:
                row = df[df["alliance_id"] == aid].iloc[0]
                return f"{row['alliance_name']} (id={aid})"

            picked = st.selectbox(
                "Pick an alliance to view its history",
                options=options,
                format_func=ally_label,
                key="ally_pick",
            )
            render_alliance_detail_block(
                server,
                int(picked),
                snapshot_id=int(snapshots_df.iloc[0]["id"]),
            )


# ---------------------------- Villages ------------------------------------- #

with tab_villages:
    st.subheader(f"Villages — {server.name}")

    df_all = villages_dataframe(server.key)
    if df_all.empty:
        st.info("No villages to show.")
    else:
        cols = st.columns([2, 1, 1])
        name_filter = cols[0].text_input("Filter by village or owner name", "", key="village_filter")
        tribes = sorted(df_all["tribe_name"].unique().tolist())
        tribe_filter = cols[1].multiselect("Tribe", options=tribes, default=tribes, key="vil_tribe")
        sort_by = cols[2].selectbox(
            "Sort by", options=["population", "Δ pop (gainers)", "Δ pop (losers)"],
            key="vil_sort",
        )

        view_df = df_all.copy()
        if name_filter:
            mask = (
                view_df["village_name"].str.contains(name_filter, case=False, na=False)
                | view_df["player_name"].str.contains(name_filter, case=False, na=False)
            )
            view_df = view_df[mask]
        view_df = view_df[view_df["tribe_name"].isin(tribe_filter)]

        if sort_by == "Δ pop (gainers)":
            view_df = view_df.sort_values("pop_delta", ascending=False, na_position="last")
        elif sort_by == "Δ pop (losers)":
            view_df = view_df.sort_values("pop_delta", ascending=True, na_position="last")
        else:
            view_df = view_df.sort_values("population", ascending=False)

        vil = _apply_coords_game_links(
            view_df[
                ["village_id", "x", "y", "flag_label", "tribe_name",
                 "population", "pop_delta", "is_new", "owner_changed"]
            ],
            server.base_url,
        ).rename(
            columns={
                "flag_label": "flag",
                "tribe_name": "tribe",
                "pop_delta": "Δ pop",
            }
        )
        vil.insert(
            1,
            "village",
            _village_name_link_series(
                view_df["village_name"], view_df["village_id"], server.key
            ),
        )
        vil.insert(
            8,
            "player",
            _player_name_link_series(
                view_df["player_name"], view_df["player_id"], server.key
            ),
        )
        vil.insert(
            9,
            "alliance",
            _alliance_name_link_series(
                view_df["alliance_name"], view_df["alliance_id"], server.key
            ),
        )
        _paginated_dataframe(
            vil,
            key=f"tbl_villages_{server.key}",
            width="stretch",
            hide_index=True,
            column_config=_link_column_config_village_player(),
        )
        st.caption(
            "**Coords** open the tile on the Travian map; **village**, **player**, and **alliance** "
            "names open pinned dashboard views — all in **new browser tabs** "
            "(★ / · in **flag** = map.sql capital marker; text = region if present)."
        )

        st.markdown("---")
        st.markdown("##### Village detail")
        if view_df.empty:
            st.caption("No villages match the current filters.")
        else:
            options = view_df["village_id"].head(500).tolist()
            id_to_name = dict(zip(df_all["village_id"], df_all["village_name"]))

            def village_label(vid: int) -> str:
                return f"{id_to_name.get(vid, '?')} (id={vid})"

            picked = st.selectbox(
                "Pick a village (top 500 from filter)",
                options=options,
                format_func=village_label,
                key="vil_pick",
            )
            render_village_detail_block(server, int(picked))


# ---------------------------- Map ------------------------------------------ #

with tab_map:
    st.subheader(f"World map — {server.name}")
    if snapshots_df.empty:
        st.info("No snapshots stored yet.")
    else:
        _render_world_map_fragment(
            server=server,
            snapshot_id=int(snapshots_df.iloc[0]["id"]),
        )


# ---------------------------- Custom maps ---------------------------------- #

with tab_custom_maps:
    st.subheader(f"Custom maps — {server.name}")
    if snapshots_df.empty:
        st.info("No snapshots stored yet.")
    else:
        _render_custom_maps_fragment(
            server_key=server.key,
            snapshot_id=int(snapshots_df.iloc[0]["id"]),
        )


# ---------------------------- Inactives ------------------------------------ #

with tab_inactives:
    st.subheader(f"Inactive search — {server.name}")
    st.caption(
        "Find villages whose population looks **stuck** (inactive-farm proxy). "
        "Use **Latest vs previous** with only 2 daily snapshots; use **Entire history** when you "
        "have many fetches stored. Search a tile ring (**min** / **max** radius) from a center."
    )
    if len(snapshots_df) < 2:
        st.warning(
            f"Need at least **2** snapshots for inactive search (you have {len(snapshots_df)}). "
            "Use **Fetch now** in the sidebar or wait for the daily schedule."
        )
    else:
        _s = cfg.settings
        flat_mode = st.selectbox(
            "Population rule",
            options=("latest_pair", "all_history"),
            format_func=lambda k: (
                "No change — latest vs previous snapshot (recommended)"
                if k == "latest_pair"
                else "No change — entire stored history (strict)"
            ),
            key="inactive_flat_mode",
            help="**Latest vs previous** compares only the two newest snapshots (best for daily auto-fetch).",
        )
        if flat_mode == "all_history" and len(snapshots_df) < int(_s.inactive_min_snapshots):
            st.info(
                f"**Entire history** mode uses **min snapshots / village** (default "
                f"{_s.inactive_min_snapshots}). You have {len(snapshots_df)} stored — "
                "fetch more or switch to **Latest vs previous**."
            )
        c1, c2, c3 = st.columns(3)
        cx = c1.number_input("Center x", value=0, step=1, key="inactive_cx")
        cy = c2.number_input("Center y", value=0, step=1, key="inactive_cy")
        min_sn = c3.number_input(
            "Min snapshots / village",
            min_value=2,
            max_value=max(len(snapshots_df), 2),
            value=min(int(_s.inactive_min_snapshots), len(snapshots_df)),
            step=1,
            key="inactive_min_sn",
        )
        r1, r2, r3 = st.columns(3)
        rad_min = r1.number_input(
            "Minimum radius (tiles)",
            min_value=0,
            max_value=600,
            value=0,
            step=1,
            key="inactive_radius_min",
            help="Inner edge of the search ring (0 = include the center tile).",
        )
        rad_max = r2.number_input(
            "Maximum radius (tiles)",
            min_value=1,
            max_value=600,
            value=int(_s.inactive_search_radius),
            step=1,
            key="inactive_radius_max",
            help="Outer edge of the search ring (Euclidean distance from center).",
        )
        include_npc = r3.checkbox(
            "Include NPC / unowned",
            value=not _s.inactive_exclude_npc,
            key="inactive_include_npc",
            help="Nature & Natars tribe villages and **player_id 0** — off by default in config.",
        )
        row_limit = st.number_input(
            "Max results (map + export use the full set)",
            min_value=100,
            max_value=20000,
            value=2000,
            step=100,
            help="Higher values return more villages but can slow the dashboard. The map always shows every match returned (up to this cap).",
            key="inactive_row_limit",
        )
        ipp1, ipp2 = st.columns(2)
        inactive_pp_min = ipp1.number_input(
            "Min player population (total, latest snapshot)",
            min_value=0,
            max_value=50_000_000,
            value=0,
            step=100,
            key="inactive_ppmin",
            help="Sum of population over **all villages** that player owns. **0** = no minimum.",
        )
        inactive_pp_max = ipp2.number_input(
            "Max player population (total, latest snapshot)",
            min_value=0,
            max_value=50_000_000,
            value=0,
            step=100,
            key="inactive_ppmax",
            help="**0** = no maximum (disabled).",
        )

        if st.button("Search", type="primary", key="inactive_search_btn"):
            _ppmn, _ppmx = int(inactive_pp_min), int(inactive_pp_max)
            _rmin, _rmax = int(rad_min), int(rad_max)
            if _rmin > _rmax:
                st.warning("Maximum radius must be ≥ minimum radius.")
            elif _ppmn > 0 and _ppmx > 0 and _ppmn > _ppmx:
                st.warning(
                    "Max player population must be ≥ min when both bounds are set "
                    "(use **0** on either side to disable that bound)."
                )
            else:
                conn = get_conn(str(DB_PATH))
                found = analyzer.inactive_villages_near(
                    conn,
                    server.key,
                    int(cx),
                    int(cy),
                    radius_min=_rmin,
                    radius_max=_rmax,
                    min_snapshots=int(min_sn),
                    exclude_npc=not include_npc,
                    limit=int(row_limit),
                    player_total_pop_min=_ppmn,
                    player_total_pop_max=_ppmx,
                    flat_mode=flat_mode,
                )
                st.session_state["inactive_last"] = {
                    "rows": [asdict(r) for r in found],
                    "cx": int(cx),
                    "cy": int(cy),
                    "rad_min": _rmin,
                    "rad_max": _rmax,
                    "flat_mode": flat_mode,
                    "snapshot_count": len(snapshots_df),
                    "limit_used": int(row_limit),
                    "hit_cap": len(found) >= int(row_limit) and int(row_limit) > 0,
                }

        last = st.session_state.get("inactive_last")
        if last and last.get("snapshot_count") != len(snapshots_df):
            st.info(
                "New snapshot(s) since this search — click **Search** again for up-to-date inactives."
            )
        if last and last.get("rows") is not None:
            st.metric("Matches", len(last["rows"]))
            df_i = pd.DataFrame(last["rows"])
            if not df_i.empty:
                if last.get("hit_cap"):
                    st.warning(
                        f"Result count **{len(df_i):,}** equals your **Max results** cap — there may be "
                        "more in this search area. Increase **Max results** and run **Search** again."
                    )
                snap_id_inactive = int(snapshots_df.iloc[0]["id"])
                idx_inactive = _map_index(server.key, snap_id_inactive)
                _ir = int(last.get("rad_max") or last.get("rad") or 0)
                _vp_inactive: tuple[int, int, int] | None = None
                if _ir > 0:
                    _vp_inactive = (int(last["cx"]), int(last["cy"]), _ir)
                st.markdown("##### Inactive matches — map (full result set)")
                st.caption(
                    f"Highlighted: **{len(df_i):,}** villages — same rows as the CSV and the table below "
                    "(tap/click a marker to pin the village)."
                )
                render_world_map(
                    server_key=server.key,
                    snapshot_id=snap_id_inactive,
                    idx=idx_inactive,
                    hl_village_ids=frozenset(
                        int(v) for v in df_i["village_id"].tolist()
                    ),
                    highlight_label="Inactive matches",
                    palette_key=str(st.session_state["dash_map_palette"]),
                    plotly_key=(
                        f"inactive_map_{server.key}_{snap_id_inactive}_"
                        f"{last['cx']}_{last['cy']}_{_ir}_{len(df_i)}"
                    ),
                    viewport=_vp_inactive,
                    plot_height=_dash_chart_sizes().full_map,
                )
                _exp_cols = [
                    c
                    for c in (
                        "village_id",
                        "village_name",
                        "x",
                        "y",
                        "population",
                        "player_id",
                        "player_name",
                        "alliance_id",
                        "alliance_name",
                        "tribe_name",
                        "snapshots_seen",
                        "distance_tiles",
                    )
                    if c in df_i.columns
                ]
                _exp_df = df_i[_exp_cols].copy()
                _csv_out = _exp_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download CSV — all matches (for in-game lists / sheets)",
                    data=_csv_out,
                    file_name=(
                        f"inactives_{server.key}_snap{snap_id_inactive}_{len(df_i)}.csv"
                    ),
                    mime="text/csv",
                    key=f"inactive_csv_{server.key}",
                )
                show = _apply_coords_game_links(
                    df_i[
                        ["village_id", "village_name", "x", "y", "distance_tiles",
                         "population", "player_total_pop", "player_id", "player_name",
                         "alliance_id", "alliance_name", "tribe_name",
                         "snapshots_seen"]
                    ],
                    server.base_url,
                ).rename(columns={
                    "distance_tiles": "dist",
                    "tribe_name": "tribe",
                    "snapshots_seen": "snapshots",
                }).copy()
                show["village"] = _village_name_link_series(
                    show["village_name"], show["village_id"], server.key
                )
                show = show.drop(columns=["village_name"])
                show["player"] = _player_name_link_series(
                    show["player_name"], show["player_id"], server.key
                )
                show["alliance"] = _alliance_name_link_series(
                    show["alliance_name"], show["alliance_id"], server.key
                )
                show = show.drop(
                    columns=["player_id", "player_name", "alliance_id", "alliance_name"]
                )
                show = show.rename(columns={"player_total_pop": "player pop"})
                show = show[
                    [
                        "village_id",
                        "village",
                        "coords",
                        "dist",
                        "population",
                        "player pop",
                        "tribe",
                        "snapshots",
                        "player",
                        "alliance",
                    ]
                ]
                st.markdown("##### Results table")
                _paginated_dataframe(
                    show,
                    key=f"tbl_inactives_{server.key}",
                    page_size_options=INACTIVE_PAGE_OPTS,
                    default_page_size=INACTIVE_DEFAULT_PAGE_SIZE,
                    min_rows_for_paging=INACTIVE_PAGING_THRESHOLD,
                    width="stretch",
                    hide_index=True,
                    column_config=_link_column_config_village_player(),
                )



with tab_natars:
    _render_special_tribe_village_search(
        server=server,
        cfg=cfg,
        snapshots_df=snapshots_df,
        tribe_id=5,
        tab_subheader="Natars villages (NPC, tribe 5)",
        count_metric_label="Natars villages (tribe 5) in latest snapshot",
        session_state_key="natars_npc_search_last",
        ui_key_prefix="natars_npc",
        csv_slug="natars_npc",
        map_highlight_label="Natars (tribe 5)",
    )


with tab_nature:
    _render_special_tribe_village_search(
        server=server,
        cfg=cfg,
        snapshots_df=snapshots_df,
        tribe_id=4,
        tab_subheader="Nature villages (tribe 4 oasis / wilderness)",
        count_metric_label="Nature villages (tribe 4) in latest snapshot",
        session_state_key="nature_search_last",
        ui_key_prefix="nature_tls",
        csv_slug="nature_tls",
        map_highlight_label="Nature (tribe 4)",
        after_count_metrics=_dashboard_warn_missing_nature_tiles,
    )


# ---------------------------- Events --------------------------------------- #

with tab_events:
    st.subheader(f"Events — {server.name}")

    if len(snapshots_df) < 2:
        st.warning(
            "Need at least 2 stored snapshots to show events. "
            "Run `python main.py fetch` again later."
        )
    else:
        # Snapshot pickers
        snap_options = snapshots_df.copy()
        snap_options["label"] = snap_options.apply(
            lambda r: f"#{int(r['id'])}  ·  {fmt_dt(r['fetched_at'])}", axis=1
        )

        col_a, col_b, col_c = st.columns([1, 1, 1])
        to_id = col_a.selectbox(
            "Compare TO snapshot",
            options=snap_options["id"].tolist(),
            format_func=lambda i: snap_options.set_index("id").loc[i, "label"],
            index=0,
            key="event_to",
        )
        prev_options = snap_options[snap_options["id"] < to_id]
        if prev_options.empty:
            st.info("No older snapshot exists before the selected one.")
            st.stop()
        from_id = col_b.selectbox(
            "Compare FROM snapshot",
            options=prev_options["id"].tolist(),
            format_func=lambda i: prev_options.set_index("id").loc[i, "label"],
            index=0,
            key="event_from",
        )
        limit = col_c.number_input("Rows per kind", min_value=10, max_value=500, value=50, step=10)

        conn = get_conn(str(DB_PATH))
        from_id, to_id = int(from_id), int(to_id)

        st.markdown(f"Snapshot **#{from_id}** → **#{to_id}**")

        sub = st.tabs(["New", "Removed", "Chiefed", "Grew", "Shrunk", "Alliance moves"])

        with sub[0]:
            data = analyzer.new_villages(conn, from_id, to_id, limit=limit)
            df = pd.DataFrame([
                {
                    "village_id": d.village_id,
                    "village_name": d.village_name,
                    "x": d.x, "y": d.y,
                    "population": d.population,
                    "player": d.player_name,
                    "alliance": d.alliance_name,
                } for d in data
            ])
            st.caption(f"{len(df)} new village(s).")
            _paginated_dataframe(
                _events_village_display_df(df, server),
                key=f"events_new_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_coords_game(),
            )

        with sub[1]:
            data = analyzer.removed_villages(conn, from_id, to_id, limit=limit)
            df = pd.DataFrame([
                {
                    "village_id": d.village_id,
                    "village_name": d.village_name,
                    "x": d.x, "y": d.y,
                    "population": d.population,
                    "former_owner": d.player_name,
                    "alliance": d.alliance_name,
                } for d in data
            ])
            st.caption(f"{len(df)} removed village(s).")
            _paginated_dataframe(
                _events_village_display_df(df, server),
                key=f"events_removed_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_coords_game(),
            )

        with sub[2]:
            data = analyzer.chiefed_villages(conn, from_id, to_id, limit=limit)
            df = pd.DataFrame([
                {
                    "village_id": d.village_id,
                    "village_name": d.village_name,
                    "x": d.x, "y": d.y,
                    "population": d.population,
                    "Δ pop": d.pop_change,
                    "from": d.prev_player_name,
                    "to": d.player_name,
                    "alliance": d.alliance_name,
                } for d in data
            ])
            st.caption(f"{len(df)} chiefed village(s).")
            _paginated_dataframe(
                _events_village_display_df(df, server),
                key=f"events_chiefed_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_coords_game(),
            )

        with sub[3]:
            data = analyzer.village_movers(conn, from_id, to_id, direction="grew", limit=limit)
            df = pd.DataFrame([
                {
                    "village_id": d.village_id,
                    "village_name": d.village_name,
                    "x": d.x, "y": d.y,
                    "prev": d.prev_population, "now": d.curr_population, "Δ pop": d.delta,
                    "player": d.player_name, "alliance": d.alliance_name,
                } for d in data
            ])
            st.caption(f"Top {len(df)} village population gainer(s).")
            _paginated_dataframe(
                _events_village_display_df(df, server),
                key=f"events_grew_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_coords_game(),
            )

        with sub[4]:
            data = analyzer.village_movers(conn, from_id, to_id, direction="shrunk", limit=limit)
            df = pd.DataFrame([
                {
                    "village_id": d.village_id,
                    "village_name": d.village_name,
                    "x": d.x, "y": d.y,
                    "prev": d.prev_population, "now": d.curr_population, "Δ pop": d.delta,
                    "player": d.player_name, "alliance": d.alliance_name,
                } for d in data
            ])
            st.caption(f"Top {len(df)} village population loser(s).")
            _paginated_dataframe(
                _events_village_display_df(df, server),
                key=f"events_shrunk_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
                column_config=_link_column_coords_game(),
            )

        with sub[5]:
            data = analyzer.alliance_moves(conn, from_id, to_id, limit=limit)
            df = pd.DataFrame([
                {
                    "player_id": d.player_id,
                    "player": d.player_name,
                    "from": d.from_alliance_name or "(none)",
                    "to": d.to_alliance_name or "(none)",
                    "population": d.population,
                } for d in data
            ])
            st.caption(f"{len(df)} alliance move(s).")
            _paginated_dataframe(
                df,
                key=f"events_alliance_moves_{server.key}_{from_id}_{to_id}_{limit}",
                width="stretch",
                hide_index=True,
            )


# ---------------------------- Snapshots ------------------------------------ #

with tab_snapshots:
    st.subheader(f"Snapshots — {server.name}")
    df = snapshots_df.copy()
    df["fetched_at"] = pd.to_datetime(df["fetched_at"]).dt.strftime("%Y-%m-%d %H:%M UTC")
    df["size"] = df["byte_size"].apply(lambda b: f"{b / 1024 / 1024:.2f} MB")
    df["sha256"] = df["sha256"].str[:12]
    _paginated_dataframe(
        df[["id", "server_key", "fetched_at", "row_count", "size", "sha256"]]
        .rename(columns={"server_key": "server", "row_count": "villages"}),
        key=f"tbl_snapshots_{server.key}",
        width="stretch",
        hide_index=True,
    )

    st.caption(
        f"Total snapshots stored: **{len(df)}**. "
        "Run `python main.py fetch` to add a new one, then refresh this page."
    )
