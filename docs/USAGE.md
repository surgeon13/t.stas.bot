# Usage handbook

This document is the full reference for **[t.statistics.stas.bot](../README.md)**: configuration, CLI, environment variables, the Streamlit dashboard, scheduling, and handing the project to someone else.

## What the app does

1. For each entry in **`config/servers.json`** → **`servers`**, it downloads **`/map.sql`** (Travian world snapshot).
2. Raw files are optionally kept under **`data/snapshots/<server_key>/`** (ignored by git).
3. Parsed rows go into **`statistics.db`** (SQLite; also gitignored): snapshot metadata plus one row per village per snapshot.
4. Identical consecutive downloads are skipped (SHA-256 deduplication).

Anything that compares “then vs now” needs **at least two snapshots** per server.

## Install and first run

Requires **Python 3.10+**.

```powershell
cd path\to\t.statistics.stas.bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

1. Ensure **`config/servers.json`** exists: after cloning, copy **`config/servers.json.example`** → **`config/servers.json`**, then edit or **`python main.py add-server …`**.
2. Fetch once:

   ```powershell
   python main.py list-servers
   python main.py fetch
   ```

3. Inspect data:

   ```powershell
   python main.py snapshots
   python main.py analyze --server <your-server-key>
   ```

4. Optional browser UI:

   ```powershell
   python -m streamlit run dashboard.py
   ```

## Configuration files

| File | Purpose |
|------|---------|
| **`config/servers.json`** | Single app config for **Travian worlds**: top-level **`servers`** (array) and **`settings`** (object — schedule `daily@HH:MM`, `every@6h`, or `every@30m`; HTTP; inactive-search defaults; optional dashboard pins). Omit **`settings`** keys you want left at defaults. |
| **`config/servers.json.example`** | Full template mirroring shipped defaults. |
| **`config/ui.yaml`** | Dashboard preferences: map palette, chart density, Plotly/chart colors, Altair vs other chart paths, overview bar style, app theme (`app_theme`), light/dark **`appearance`**. The interactive **`menu`** command reads the same **`--ui`** path. |
| **`config/custom_maps.yaml`** | Named map configs for the **Custom** tab (regions, overlays). |

Global CLI overrides:

- **`--config path`** — Travian/app JSON (**default `config/servers.json`**). Streamlit reads **`T_STATS_CONFIG`** (**same default**) because it does not pass **`main.py`’s **`--config`**.
- **`--db path`** — alternate SQLite path (default: **`statistics.db`**).

### Environment variables (dashboard-focused)

These are read when you run **`streamlit run dashboard.py`** (see `dashboard.py` / `src/embed_scheduler.py`):

| Variable | Meaning |
|---------|---------|
| **`T_STATS_DB`** | SQLite path; default **`statistics.db`**. Keeps CLI and dashboard on the same file if both run on one machine. |
| **`T_STATS_CONFIG`** | Path to app JSON (**default `config/servers.json`**). |
| **`T_STATS_EMBED_SCHEDULER`** | If unset, the dashboard **starts the same daily fetch loop** as `python main.py run` in a background thread. Set to **`0`** or **`false`** to disable embedded fetching (dashboard read-only for collection). |
| **`T_STATS_EMBED_SCHED_STDIN`** | Set **`1`** to allow the embedded scheduler’s ad hoc stdin commands (stdin is awkward when shared with Streamlit; usually leave unset). |

### Environment variables (terminal menu)

| Variable | Meaning |
|---------|---------|
| **`T_STATS_MENU_RAW`** | If **`1`**, **`python main.py menu`** defaults to immediate single-character keys unless you override with **`--line-input`**. Useful in raw terminals or when you prefer “press key without Enter”. |

Never run **`python main.py run`** and the dashboard’s embedded fetch at the **same schedule** against the **same DB** unless you deliberately want duplicate work; both implement daily collection.

## CLI reference

Discover everything from the shell:

```powershell
python main.py --help
python main.py fetch --help
```

### Global flags (all subcommands)

- **`--config`** — app JSON (**`config/servers.json`** by default).
- **`--db`** — SQLite path.
- **`-v` / `--verbose`** — DEBUG logging.

### Subcommands

| Command | Purpose |
|---------|---------|
| **`menu`** | Interactive terminal hub: fetch, refresh views, opens settings pointers. **`--ui config/ui.yaml`**, **`--line-input`**, **`--quick-keys`**. |
| **`list-servers`** | Print configured servers and schedule hints. |
| **`add-server`** | Append one object to **`servers`** in **`--config`** (default **`config/servers.json`**). **`--dry-run`** prints JSON only. Flags: **`--key`**, **`--name`**, **`--base-url`**, repeatable **`--tag`**, **`--disable`**. |
| **`fetch`** | Download and ingest **`map.sql`** for all enabled servers, or **`--server <key>`** for one. |
| **`snapshots`** | List stored snapshots; **`--server`**, **`--limit`**. |
| **`analyze`** | Latest snapshot summary + tribe breakdown + top players/alliances; **`--top`**. |
| **`players`** | Player ranking with delta vs previous snapshot; **`--sort`** `population` or `villages`. |
| **`player`** | One player: history + village ledger; **`--id`** or **`--name`**; **`--no-villages`**. |
| **`alliances`** | Alliance ranking; **`--sort`** `population`, `members`, or `villages`. |
| **`alliance`** | One alliance history; **`--id`** or **`--name`**. |
| **`villages`** | Village ranking; **`--sort`** `population`, `growth`, or `loss`; **`--player`** (id or name). |
| **`village`** | One village history; **`--id`** or **`--name`**. |
| **`events`** | Diff between snapshots (default: latest pair); **`--kind`**, **`--from-id`**, **`--to-id`**, **`--limit`**. |
| **`inactives`** | Villages near **`--x`** / **`--y`** with flat population over history; **`--radius`**, **`--min-snapshots`**, **`--include-npc`**, **`--limit`**, **`--player-pop-min`**, **`--player-pop-max`**. Requires enough stored snapshots (`inactive_min_snapshots` in settings). |
| **`run`** | Foreground scheduler loop (`settings.schedule`: **`daily@HH:MM`**, **`every@Nh`**, **`every@Nm`**). Ad hoc stdin commands unless **`--no-schedule-stdin`**. **`python main.py`** with no subcommand defaults to **`run --no-schedule-stdin`**. |

Examples:

```powershell
python main.py events --server europe31x3 --kind chiefed
python main.py inactives --server europe31x3 --x 10 --y -20 --radius 15
python main.py run --no-schedule-stdin   # daemon-like: no stdin commands
```

## Streamlit dashboard tabs

Launch: **`python -m streamlit run dashboard.py`** (same DB as **`main.py`** unless you changed **`T_STATS_DB`**).

The UI has **twelve** top-level tabs (order as in code):

1. **Overview** — Server-wide KPIs over time, tribe distribution, charts.
2. **Leaderboards** — Top alliances / players / villages style rankings.
3. **Players** — Search and drill-down; player map uses **green** (current villages), **red** (lost to another player while still observable), **yellow** (destroyed / disappeared at last known coords), grey backdrop for the rest.
4. **Alliances** — Search and drill-down; alliance maps use **green** (current members), **blue** (chiefed away but village still on map), **yellow** (same owner but no longer in this alliance tag), **red** (gone in latest snapshot), with expanders for conquered holdings and losses by opposing alliance where applicable.
5. **Villages** — Table and single-village history.
6. **Map** — Full-world **Plotly** scatter; highlight by player, alliance, or tribe.
7. **Custom** — Maps driven by **`config/custom_maps.yaml`**.
8. **Inactives** — Same idea as CLI **`inactives`**, with UI controls.
9. **Natars (NPC)** — Focus on NPC / Natars-style tribe data (tribe 5 in typical worlds).
10. **Nature** — Separate **Nature** / tribe-4 style tiles when present in **`map.sql`** (some worlds have little or no Nature data).
11. **Events** — Snapshot-to-snapshot diff (new, removed, chiefed, growth, alliance moves).
12. **Snapshots** — List of stored runs.

### Themes and charts

Palettes and **`app_theme`** / **`appearance`** live in **`config/ui.yaml`**. After editing, reload the dashboard (Streamlit rerun). The **`menu`** command’s UI path should match **`config/ui.yaml`** if you want terminal and browser aligned.

### “WebSocketClosedError” / Tornado traceback in the console

Clients disconnecting from Streamlit’s dev server often produce benign WebSocket/stack traces in the terminal. That is runtime noise, not corrupt data — unless UI actions fail reproducibly after a reload.

## Scheduling (choose one pattern)

| Pattern | When to use |
|---------|--------------|
| **Task Scheduler → `python main.py fetch`** once per day | Simplest external trigger; process exits after fetch. |
| **`python main.py run`** (or **`scripts/run_daily_fetch.bat`**) | Long-lived process with built-in **`schedule`** library. |
| **Dashboard embedded scheduler** | Default **`on`**; set **`T_STATS_EMBED_SCHEDULER=0`** if you fetch only via **`main.py`**. |

**Do not** double-schedule the same DB with **`run`** and embedded dashboard fetch without intending duplicate downloads.

Windows examples are in **`README.md`**.

## Export / handoff checklist

When packaging or sending the repo to someone else:

1. Include **source**, **`LICENSE`**, **`config/servers.json.example`**, **`config/ui.yaml`** / **`config/custom_maps.yaml`** if customised (**not** **`config/servers.json`** — that file is gitignored and must stay personal).
2. Include **`requirements.txt`**, **`pyproject.toml`**, and **`README.md`** plus this **`docs/USAGE.md`**.
3. **Exclude** from zips/shares unless needed: **`statistics.db`**, **`data/snapshots/`**, **`.venv/`** (recipient rebuilds venv).
4. Document **`T_STATS_DB`** / **`T_STATS_CONFIG`** if their paths differ from defaults.
5. Run **`pip install -r requirements.txt`** and **`python main.py fetch`** once to validate.
6. For a clean release archive, run **`scripts/export_release.bat`** to package the repository without personal data.

Quick sanity check for syntax (optional):

```powershell
python -m compileall -q src
python -m py_compile main.py dashboard.py
```
