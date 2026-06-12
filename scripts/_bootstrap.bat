@echo off
REM Shared setup: project root + python (prefers .venv).
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  set "T_STATS_PYTHON=.venv\Scripts\python.exe"
) else (
  set "T_STATS_PYTHON=python"
)
if not exist "config\servers.json" (
  if exist "config\servers.json.example" (
    echo [t.statistics.stas.bot] Creating config\servers.json from example...
    copy /Y "config\servers.json.example" "config\servers.json" >nul
  )
)
