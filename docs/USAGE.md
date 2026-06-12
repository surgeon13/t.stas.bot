# Usage handbook

Full reference for **[t.statistics.stas.bot](../README.md)** (v1.1.2): configuration, Windows launchers, CLI, environment variables, Streamlit dashboard, scheduling, and handoff.

## What the app does

1. For each entry in **`config/servers.json`** → **`servers`**, it downloads public **`/map.sql`** (Travian world snapshot). **No game login** — only the same public dump the browser can request.
2. Raw files are optionally kept under **`data/snapshots/<server_key>/`** (gitignored).
3. Parsed rows go into **`statistics.db`** (SQLite; gitignored): snapshot metadata plus one row per village per snapshot.
4. Identical consecutive downloads are skipped (SHA-256 deduplication).

Anything that compares “then vs now” needs **at least two snapshots** per server.

## Install and first run

Requires **Python 3.10+**.

### Windows (recommended)

```powershell
cd path\to\t.statistics.stas.bot
scripts\install_requirements.bat
```

That creates **`.venv`** and installs **`requirements.txt`**.

| Launcher | What it does |
|----------|----------------|
| **`Start Dashboard.bat`** (project root) | Streamlit UI + **embedded daily fetch** (recommended) |
| **`Start Collector.bat`** | Fetch loop only, no browser |
| **`scripts\run_dashboard_with_scheduler.bat`** | Same as **Start Dashboard.bat** |
| **`scripts\run_daily_fetch.bat`** | Same as **Start Collector.bat** |

Launchers:

- Use **`.venv\Scripts\python.exe`** when present.
- Create **`config\servers.json`** from **`config\servers.json.example`** if missing.

### Manual setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy config\servers.json.example config\servers.json
python main.py fetch
python -m streamlit run dashboard.py
```

### Default server template

**`config/servers.json.example`** ships with **International 50 (x5)**:

- **key:** `international50x5`
- **base_url:** `https://ts50.x5.international.travian.com`

Edit **`config/servers.json`** or run **`python main.py add-server …`** for other worlds.

## Configuration files

| File | Purpose |
|------|---------|
| **`config/servers.json`** | **`servers[]`** (worlds) and **`settings`** (schedule, HTTP, inactive defaults, optional dashboard watchlists). **Gitignored** — copy from example after clone. |
| **`config/servers.json.example`** | Shipped template. |
| **`config/ui.yaml`** | Dashboard: map palette, chart size/colors, Plotly backend, overview bar style, **`app_theme`**, light/dark **`appearance`**. |
| **`config/custom_maps.yaml`** | Named regions for the **Custom** tab. |

### `settings` highlights (`config/servers.json`)

| Key | Meaning |
|-----|---------|
| **`schedule`** | `daily@00:01` (local time), `every@6h`, or `every@30m` |
| **`inactive_search_radius`** | Default **maximum** radius (tiles) for inactive search in the dashboard |
| **`inactive_min_snapshots`** | Default min observations per village for **entire history** inactive mode |
| **`inactive_exclude_npc`** | Exclude Nature/Natars / unowned when `true` |
| **`keep_raw_snapshots`** | Save raw `map.sql` under **`data/snapshots/`** |

Global CLI overrides:

- **`--config path`** — app JSON (default **`config/servers.json`**).
- **`--db path`** — SQLite path (default **`statistics.db`**).

### Environment variables

| Variable | Used by | Meaning |
|----------|---------|---------|
| **`T_STATS_DB`** | CLI, dashboard | SQLite path (default **`statistics.db`**). |
| **`T_STATS_CONFIG`** | Dashboard | App JSON path (default **`config/servers.json`**). |
| **`T_STATS_EMBED_SCHEDULER`** | Dashboard | Default **on**. Set **`0`** / **`false`** to disable background fetch in Streamlit. |
| **`T_STATS_EMBED_SCHED_STDIN`** | Dashboard | Set **`1`** for stdin ad-hoc schedule commands (rare). |
| **`T_STATS_MENU_RAW`** | `menu` | Set **`1`** for single-key menu mode without Enter. |

**Do not** run **`python main.py run`** and the dashboard embedded fetch on the **same DB** unless you want duplicate downloads.

## Collection and scheduling

| Pattern | When to use |
|---------|-------------|
| **`Start Dashboard.bat`** | Browser UI + daily auto-fetch in one process (default **on**). |
| **`Start Collector.bat`** / **`python main.py`** | Long-lived fetch loop, no UI. |
| **`python main.py fetch`** | One-shot download. |
| Windows Task Scheduler → **`main.py fetch`** | External daily trigger; process exits after fetch. |

**`python main.py`** with no subcommand defaults to **`run --no-schedule-stdin`** (unattended loop).

Schedule string lives in **`config/servers.json`** → **`settings.schedule`**.

### Dashboard sidebar (when using Streamlit)

- **Daily fetch ON** — shows schedule from config.
- **Fetch now** — manual `map.sql` download + DB update; clears dashboard caches.
- **Last automated fetch** — timestamp when the embedded job last completed.

Coordinate columns in tables link to **`position_details.php`** on the configured **`base_url`** (opens Travian map in a new browser tab).

## CLI reference

```powershell
python main.py --help
python main.py fetch --help
```

### Global flags

- **`--config`**, **`--db`**, **`-v` / `--verbose`**

### Subcommands

| Command | Purpose |
|---------|---------|
| **`menu`** | Terminal hub: fetch, UI settings pointers. |
| **`list-servers`** | Configured worlds + schedule. |
| **`add-server`** | Append to **`servers`** (`--key`, `--name`, `--base-url`, `--tag`, `--disable`, `--dry-run`). |
| **`fetch`** | Download + ingest; optional **`--server`**. |
| **`snapshots`** | List stored snapshots. |
| **`analyze`** | Latest summary + tribes + tops; **`--top`**. |
| **`players`**, **`player`** | Rankings and drill-down; **`--sort`**, **`--id`**, **`--name`**. |
| **`alliances`**, **`alliance`** | Alliance rankings and history. |
| **`villages`**, **`village`** | Village rankings and history; **`--sort`**, **`--player`**. |
| **`events`** | Snapshot diff; **`--kind`**, **`--from-id`**, **`--to-id`**. |
| **`inactives`** | Flat-population search near **`--x`** / **`--y`** (see below). |
| **`run`** | Scheduler loop; **`--no-schedule-stdin`** for unattended mode. |

### Inactives (CLI)

Finds villages whose population looks **stuck** (inactive-farm proxy — not login activity).

```powershell
python main.py inactives --server international50x5 --x 10 --y -20
python main.py inactives --server international50x5 --x 10 --y -20 ^
  --radius-min 0 --radius 30 ^
  --flat-mode latest_pair ^
  --player-pop-max 500
```

| Flag | Meaning |
|------|---------|
| **`--radius`** | **Maximum** distance from center (tiles); default **`inactive_search_radius`**. |
| **`--radius-min`** | **Minimum** distance (0 = include center tile). |
| **`--flat-mode`** | **`latest_pair`** (default) — unchanged pop between **last two** snapshots; **`all_history`** — flat across **all** stored snapshots. |
| **`--min-snapshots`** | Min observations per village (mainly for **`all_history`**). |
| **`--player-pop-min`**, **`--player-pop-max`** | Filter by owner’s **total** pop in latest snapshot; **`0`** disables that bound. |
| **`--include-npc`** | Include Nature/Natars / unowned. |
| **`--limit`** | Max rows printed. |

**Tip:** With only **2 daily snapshots**, use **`--flat-mode latest_pair`**.

### Examples

```powershell
python main.py fetch --server international50x5
python main.py events --server international50x5 --kind chiefed
python main.py run --no-schedule-stdin
```

After **`pip install -e .`**, the console entry point **`t-statistics`** is available with the same subcommands.

## Streamlit dashboard tabs

Launch: **`Start Dashboard.bat`** or **`python -m streamlit run dashboard.py`**.

| Tab | Purpose |
|-----|---------|
| **Overview** | Server KPIs over time, tribe charts. |
| **Leaderboards** | Top alliances, players, villages. |
| **Players** | Table + drill-down; player map (green/red/yellow layers). |
| **Alliances** | Table + drill-down; alliance territory maps. |
| **Villages** | Sortable table; village detail. |
| **Map** | Full-world Plotly map; highlight player/alliance/tribe. |
| **Custom** | **`config/custom_maps.yaml`** presets. |
| **Inactives** | Ring search around center; map + table + CSV (see below). |
| **Natars (NPC)** | Tribe 5 / NPC search. |
| **Nature** | Tribe 4 when present in `map.sql`. |
| **Events** | Diff between two snapshots. |
| **Snapshots** | Stored fetch list. |

### Inactives tab (dashboard)

1. Set **center x/y**, **minimum / maximum radius** (tile ring).
2. Choose **Population rule**:
   - **Latest vs previous** (recommended with daily auto-fetch).
   - **Entire history** (strict; needs more snapshots).
3. Optional **min/max player population** (total across all villages; **`0`** = no bound).
4. Click **Search** — map shows **all** matches (up to **Max results**); table is paged (default 25 rows; dropdown when &gt; 10 matches).
5. Use **Fetch now** in the sidebar after new snapshots land, then **Search** again.

### Themes

Edit **`config/ui.yaml`**; reload the dashboard. **`python main.py menu`** can adjust some palette settings to the same file.

### Console noise

Streamlit disconnect WebSocket traces in the terminal are usually harmless unless the UI breaks after reload.

## Export / handoff checklist

1. Include source, **`LICENSE`**, **`README.md`**, **`docs/USAGE.md`**, **`config/servers.json.example`**, **`config/ui.yaml`**, **`Start Dashboard.bat`**, **`Start Collector.bat`**, **`scripts/`**.
2. **Do not** ship **`config/servers.json`**, **`statistics.db`**, **`data/snapshots/`**, **`.venv/`** unless intentional.
3. Recipient runs **`scripts\install_requirements.bat`**, edits **`config/servers.json`**, double-clicks **`Start Dashboard.bat`** or runs **`python main.py fetch`** once.
4. Optional archive: **`scripts\export_release.bat`** → **`release-v1.1.2.zip`**.

Sanity check:

```powershell
python -m compileall -q src
python -m py_compile main.py dashboard.py
```

## Project layout (runtime)

```text
Start Dashboard.bat       # double-click: UI + daily fetch
Start Collector.bat       # double-click: fetch loop only
config/servers.json       # your worlds (gitignored)
statistics.db             # SQLite (gitignored)
data/snapshots/           # raw map.sql (gitignored)
main.py                   # CLI
dashboard.py              # Streamlit app
src/                      # library code
scripts/                  # install, export, launcher helpers
```

See **`data/README.md`** for what appears under **`data/`** at runtime.
