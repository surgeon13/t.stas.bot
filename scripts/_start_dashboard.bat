@echo off
call "%~dp0_bootstrap.bat"
set T_STATS_EMBED_SCHEDULER=1
"%T_STATS_PYTHON%" -m streamlit run dashboard.py %*
