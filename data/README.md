# Runtime data directory

The app writes optional files here at runtime (all gitignored except this README).

| Path | When created |
|------|----------------|
| **`snapshots/<server_key>/`** | Raw `map.sql` bodies when **`keep_raw_snapshots`** is `true` in **`config/servers.json`**. |
| **`statistics.db`** | Lives in the **project root** (not under `data/`), created on first fetch. |

Windows launchers (**`Start Dashboard.bat`**, **`Start Collector.bat`**) use the project root as the working directory, so paths above resolve correctly.

See **[docs/USAGE.md](../docs/USAGE.md)** for scheduling, inactive search, and dashboard usage.
