# t.statistics.stas.bot

**Version 1.1.1**

A small app that downloads `map.sql` from one or more Travian servers, parses it,
and stores each snapshot in SQLite so you can build a persistent, time-aware view
of the world: player rosters, alliance composition, population movement,
new/abandoned villages, etc.

For a complete handbook (every CLI subcommand, environment variables, dashboard tabs,
scheduling patterns, export checklist), see **[docs/USAGE.md](docs/USAGE.md)**.

This is **unofficial tooling** for players who already use public `map.sql` world dumps: it does not log into the game or bypass access controls. You are responsible for complying with **Travian’s terms** and your kingdom’s etiquette. Use a **private** GitHub/Git repo if your alliance treats stats as sensitive.

When **publishing to Git**:

- **`config/servers.json`** is **gitignored** — copy **`config/servers.json.example`** to **`config/servers.json`** after clone (never commit worlds you care about).
- **`statistics.db`** and **`data/snapshots/`** stay local ([`.gitignore`](.gitignore)).

See **[GitHub](#github)** below.

## Release / export

This release is prepared as version **1.1.1**.

To create a clean handoff archive without personal data, run:

```powershell
scripts\export_release.bat
```

The archive includes source, docs, example config files, and scripts, but excludes
user-only data such as `statistics.db`, `data/snapshots/`, and `.venv/`.

## How it works

For each configured server it does this:

1. `GET https://<server>/map.sql`
2. Save the raw body to `data/snapshots/<server_key>/<timestamp>.map.sql`
3. Parse the `INSERT INTO x_world VALUES (...)` rows
4. Insert a row in `snapshots` and one row per village in `villages` (keyed by snapshot)
5. Skip silently if the file's sha256 matches an already-stored snapshot

Because every snapshot is kept, queries across snapshots give you the full
history (e.g. "did this player exist last week?", "how did this alliance grow?").

## Project layout

```text
config/servers.json       # create locally — copy servers.json.example (not in git)
config/servers.json.example
LICENSE
.gitignore
config/ui.yaml            # dashboard + menu: themes, map palette, chart options
config/custom_maps.yaml   # optional regions for the Custom map tab
.streamlit/config.toml    # Streamlit chrome (toolbar, theme, usage stats off)
docs/USAGE.md         # full usage reference (CLI, env vars, export checklist)
data/README.md        # what lands under data/ at runtime
data/snapshots/       # raw map.sql files (gitignored)
src/                  # modules: config / downloader / parser / storage / analyzer / scheduler / view
main.py               # CLI entry point (terminal UI with rich tables)
dashboard.py          # Streamlit web dashboard (browser UI, reads same DB)
statistics.db         # SQLite database (gitignored, created on first run)
```

## Setup

Requires Python 3.10+.

**New clone:** create your app config from the template (the real file is never committed):

```powershell
copy config\servers.json.example config\servers.json
# then edit config\servers.json or: python main.py add-server --key ... --name ... --base-url https://...
```

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

On Windows, you can also use the helper:

```powershell
scripts\install_requirements.bat
```

## Quick start

1. Ensure `config/servers.json` exists by copying the example and editing the server entries:

```powershell
copy config\servers.json.example config\servers.json
```

2. Run a one-time fetch to download the latest map snapshot:

```powershell
python main.py fetch
```

3. Open the dashboard in your browser:

```powershell
streamlit run dashboard.py
```

4. Run the scheduler loop so fetches repeat automatically (no keyboard input; reads `settings.schedule`):

```powershell
python main.py run --no-schedule-stdin
# or simply (same unattended default):
python main.py
```

Schedule in `config/servers.json`: `daily@00:01` (default), `every@6h`, or `every@30m`. On Windows, **`scripts\run_daily_fetch.bat`** starts the same loop.

If you want to install the app as a local package after export:

```powershell
python -m pip install -e .
```

The CLI uses [`rich`](https://github.com/Textualize/rich) to render output as
colored tables. For best results run it in a terminal that supports ANSI
colors (Windows Terminal, PowerShell 7+, Cursor's integrated terminal — all
fine).

For a browser-based UI, see [Web dashboard](#web-dashboard) below.

## Usage

### Collection

```powershell
python main.py list-servers                       # show configured servers
python main.py add-server --key k --name "N" --base-url https://...  # append to config/servers.json
python main.py menu                               # interactive terminal hub (fetch, UI paths, quit)
python main.py fetch                              # fetch all enabled servers once
python main.py fetch --server europe31x3
python main.py snapshots                          # list stored snapshots
python main.py run                                # daily scheduled loop (foreground)
```

### Snapshot summary

```powershell
python main.py analyze --server europe31x3       # summary + tribe + top 10
python main.py analyze --server europe31x3 --top 25
```

### Player population

```powershell
# Ranking with delta vs previous snapshot (only when 2+ snapshots stored)
python main.py players --server europe31x3 --top 25
python main.py players --server europe31x3 --sort villages

# Full history for a single player (with sparkline) + per-village ledger
python main.py player --server europe31x3 --name "Angry Mokki"
python main.py player --server europe31x3 --id 3865

# Skip the ledger (just show the population history)
python main.py player --server europe31x3 --id 3865 --no-villages
```

The `player` command now prints three sections:

1. **Summary** — tribe, alliance, snapshots, sparkline.
2. **Snapshot history** — population & villages per snapshot.
3. **Village ledger** — for *each* village this player currently owns:
   - `status`: `settled` (founded by them inside our observation window),
     `conquered` (chiefed from another player) or `pre-existing` (already
     theirs in the very first snapshot we have, so we cannot tell).
   - `from`: the previous owner if conquered.
   - `at`: the snapshot timestamp at which they took the village.
   - `coords`: x|y of the village.

   The ledger is reconstructed from the snapshot history, so the more
   snapshots you have stored the more `pre-existing` rows turn into real
   `settled` / `conquered` events as the world evolves.

### Alliance population

```powershell
python main.py alliances --server europe31x3 --top 25
python main.py alliances --server europe31x3 --sort members

python main.py alliance --server europe31x3 --name "IMX"   # shows disambiguation if ambiguous
python main.py alliance --server europe31x3 --id 42
```

### Village population

```powershell
# Top villages by current population (with per-village delta vs previous snapshot)
python main.py villages --server europe31x3 --top 25

# Top gainers / losers in the latest snapshot only
python main.py villages --server europe31x3 --sort growth --top 25
python main.py villages --server europe31x3 --sort loss --top 25

# All villages owned by one player (with per-village delta)
python main.py villages --server europe31x3 --player "Angry Mokki"
python main.py villages --server europe31x3 --player 3865

# Full history of one village (population + owner timeline + sparkline)
python main.py village --server europe31x3 --name "Capital"   # disambiguates
python main.py village --server europe31x3 --id 77304
```

### Inactive villages (flat population near coordinates)

Uses the latest snapshot plus enough history so “flat” population is meaningful.
Thresholds come from **`settings`** in **`config/servers.json`** unless you override flags.

```powershell
python main.py inactives --server europe31x3 --x 10 --y -20
python main.py inactives --server europe31x3 --x 10 --y -20 --radius 20 --include-npc
```

### Cross-snapshot events

Compares the two latest snapshots by default. Pass `--from-id` / `--to-id` to
compare any two specific snapshots. Use `--kind` to filter to one event type.

```powershell
python main.py events --server europe31x3                   # all event kinds
python main.py events --server europe31x3 --kind new        # newly founded villages
python main.py events --server europe31x3 --kind chiefed    # chiefed villages (owner changed)
python main.py events --server europe31x3 --kind ally-move  # players who switched alliance
python main.py events --server europe31x3 --kind removed    # villages destroyed/disappeared
python main.py events --server europe31x3 --kind grew       # top village pop gainers (same owner)
python main.py events --server europe31x3 --kind shrunk     # top village pop losers (same owner)
python main.py events --server europe31x3 --from-id 1 --to-id 5
```

### Scheduling vs one-shot

`python main.py run` blocks the foreground and uses `schedule` to run the job
daily at `settings.schedule` (default `daily@00:01`, **machine local time**).
You can double-click **`scripts/run_daily_fetch.bat`** on Windows to start that loop.

**Dashboard + automatic fetch:** enabled **by default** when you launch Streamlit — the dashboard
runs the same daily loop as **`python main.py run`** in a background thread. Use
**`T_STATS_EMBED_SCHEDULER=0`** (or `false`) before **`streamlit run dashboard.py`** for
dashboard-only (no builtin fetches — e.g. you run **`python main.py run`** or Task Scheduler
elsewhere instead). Avoid running **`python main.py run`** and the dashboard’s embedded fetch on the **same DB** schedule, or you will collect duplicate **`map.sql`** snapshots.

The helper **`scripts/run_dashboard_with_scheduler.bat`** sets `T_STATS_EMBED_SCHEDULER=1`
explicitly; it is optional now that fetching defaults on.

For a true background service, register **`python main.py run`** (or the `.bat`)
in Task Scheduler — see the bottom of this README for a sample entry.

## Servers and scheduling

Everything for **which worlds to track** (and **when** / **HTTP** options / **inactive** defaults / dashboard **pins**) lives in one file: **`config/servers.json`**.

**From the terminal (append a world):**

```powershell
python main.py add-server --key another --name "Another server" --base-url https://tsX.X.region.travian.com --tag europe
python main.py add-server ... --dry-run   # preview JSON without writing
```

**By hand:** copy **`config/servers.json.example`** or edit **`config/servers.json`**. Fields:

- **`servers`**: array of `{ "key", "name", "base_url", "enabled", "tags" }`.
- **`settings`**: optional object; omit keys you keep at built-in defaults (see **`config/servers.json.example`**).

Each **`key`** must be unique across **`servers`**. **`base_url`** is the site root (**`map.sql`** is **`{base_url}/map.sql`**). Use **`python main.py --config path\to\other.json …`** or **`T_STATS_CONFIG`** on the dashboard to point at another JSON file.

To temporarily disable a world without deleting it, set **`"enabled": false`** on that server object.

## Database schema

Two tables:

- `snapshots(id, server_key, fetched_at, source_url, raw_path, byte_size, sha256, row_count)`
- `villages(snapshot_id, village_id, x, y, tribe_id, vid, village_name, player_id, player_name, alliance_id, alliance_name, population, region, extra_json)`

Identical fetches (same sha256 per server) are deduplicated.

## Web dashboard

For a browser-based UI instead of the terminal:

```powershell
python -m streamlit run dashboard.py
```

Streamlit prints a `Local URL` (default `http://localhost:8501`) — open it
in any browser. The dashboard reads the same `statistics.db`, so it stays in
sync with whatever `main.py fetch` collects.

It has **twelve** tabs (same SQLite as the CLI):

- **Overview** — Server-wide population / players / alliances over time, tribe distribution, charts.
- **Leaderboards** — Top alliances, players, and villages (ranking-style views).
- **Players** — Sortable / filterable table; drill-down with history chart, per-village ledger (settled / conquered / pre-existing). Player map: **green** current, **red** lost to others, **yellow** destroyed / off-map at last coords, grey backdrop.
- **Alliances** — Table + drill-down; alliance maps: **green** current members, **blue** chiefed away (still on map), **yellow** same owner but left this tag, **red** gone in latest snapshot (last-known coords), with expanders for conquered holdings and losses.
- **Villages** — Table and single-village history.
- **Map** — Full-world **Plotly** scatter; highlight by **Player**, **Alliance**, or **Tribe** (highlighted set in color on a faded grey field). Centroid, bounding box, and per-village lists in the UI.
- **Custom** — Named regions / views from **`config/custom_maps.yaml`**.
- **Inactives** — Same idea as **`python main.py inactives`**, with controls in the browser.
- **Natars (NPC)** — Natars / NPC-focused village search (typical **tribe 5** worlds).
- **Nature** — Nature tiles when present in **`map.sql`** (some worlds have little or no tribe-4 data).
- **Events** — Diff between any two stored snapshots: new / removed / chiefed / growth / shrink / alliance moves.
- **Snapshots** — List of stored fetches.

Appearance (light/dark, chart themes, map palette) is driven by **`config/ui.yaml`** — see **[docs/USAGE.md](docs/USAGE.md)**.

If `streamlit` isn't on your PATH, always invoke it as `python -m streamlit run …`.

## Running on a schedule

For a background service on Windows, pick one:

**Trigger once per day at 00:01** (single process, exits after fetch):

```text
Action:    Start a program
Program:   C:\path\to\.venv\Scripts\python.exe
Arguments: main.py fetch
Start in:  C:\Users\path\to\t.statistics.stas.bot
Trigger:   Daily at 00:01
```

**Or** start the in-app scheduler at login (runs forever, respects `settings.schedule`):

```text
Program:   C:\path\to\scripts\run_daily_fetch.bat
Start in:  C:\Users\path\to\t.statistics.stas.bot
Trigger:   At log on (or Daily if you restart the PC daily)
```

## GitHub

Canonical repo (maintainer: [surgeon13](https://github.com/surgeon13/)):  
**[github.com/surgeon13/t.stas.bot](https://github.com/surgeon13/t.stas.bot)** — use **Private** if you treat alliance stats as sensitive.

**Create the GitHub repo once:** open [github.com/new](https://github.com/new), name **`t.stas.bot`**, owner **surgeon13**, choose **Private**, and do **not** add README / .gitignore / license (this tree already has them).

**Push from this folder** (`origin` may already be set):

```powershell
git remote add origin https://github.com/surgeon13/t.stas.bot.git   # skip if remote origin exists
git branch -M main
git push -u origin main
```

**Clone elsewhere:**

```powershell
git clone https://github.com/surgeon13/t.stas.bot.git
cd t.stas.bot
copy config\servers.json.example config\servers.json
```

Then edit **`config\servers.json`** or run **`python main.py add-server …`** before **`fetch`**.
