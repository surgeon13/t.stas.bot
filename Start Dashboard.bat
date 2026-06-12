@echo off
title t.statistics.stas.bot — Dashboard
call "%~dp0scripts\_bootstrap.bat"
echo.
echo  t.statistics.stas.bot — Dashboard + daily map fetch
echo  Browser: http://localhost:8501
echo  Schedule: config\servers.json -^> settings.schedule
echo  Close this window to stop the dashboard and background fetch.
echo.
set T_STATS_EMBED_SCHEDULER=1
"%T_STATS_PYTHON%" -m streamlit run dashboard.py %*
if errorlevel 1 (
  echo.
  echo Failed. Run scripts\install_requirements.bat first if dependencies are missing.
  pause
)
