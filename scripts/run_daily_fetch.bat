@echo off
REM Scheduled map.sql fetch — runs until you close the window (no keyboard input needed).
REM Schedule: config/servers.json -> settings.schedule (daily@HH:MM, every@6h, every@30m).
cd /d "%~dp0\.."
python main.py run --no-schedule-stdin %*
