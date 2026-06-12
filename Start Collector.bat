@echo off
title t.statistics.stas.bot — Collector
call "%~dp0scripts\_bootstrap.bat"
echo.
echo  t.statistics.stas.bot — map.sql collector (no browser UI)
echo  Fetches on schedule from config\servers.json -^> settings.schedule
echo  Close this window to stop.
echo.
"%T_STATS_PYTHON%" main.py run --no-schedule-stdin %*
if errorlevel 1 (
  echo.
  echo Failed. Run scripts\install_requirements.bat first if dependencies are missing.
  pause
)
