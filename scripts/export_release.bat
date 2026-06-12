@echo off
REM Create a sanitized export archive for release or handoff.
cd /d "%~dp0\.."
set "OUT=release-v1.1.2.zip"
if exist "%OUT%" del "%OUT%"
powershell -NoProfile -Command "Compress-Archive -Path 'LICENSE','README.md','requirements.txt','pyproject.toml','main.py','dashboard.py','Start Dashboard.bat','Start Collector.bat','docs','config\\servers.json.example','config\\ui.yaml','config\\custom_maps.yaml','scripts\\install_requirements.bat','scripts\\run_daily_fetch.bat','scripts\\run_dashboard_with_scheduler.bat','src' -DestinationPath '%OUT%' -Force"
echo Export archive created: %OUT%
