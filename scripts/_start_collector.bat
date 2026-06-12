@echo off
call "%~dp0_bootstrap.bat"
"%T_STATS_PYTHON%" main.py run --no-schedule-stdin %*
