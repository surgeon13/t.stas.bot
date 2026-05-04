@echo off
REM Starts Streamlit dashboard with embedded daily fetch scheduler (same as python main.py run).
REM Time: config/servers.json -> settings.schedule
cd /d "%~dp0\.."
set T_STATS_EMBED_SCHEDULER=1
python -m streamlit run dashboard.py %*
