@echo off
REM Daily scheduled map.sql fetch — runs in the foreground until you close the window.
REM Time is set in config/servers.json under settings.schedule (default daily@00:01 local).
cd /d "%~dp0\.."
python main.py run %*
