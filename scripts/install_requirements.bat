@echo off
REM Install Python dependencies required by the app.
cd /d "%~dp0\.."
python -m pip install -r requirements.txt
