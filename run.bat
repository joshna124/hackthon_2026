@echo off
REM One-shot launcher for Windows.
REM Usage:  run.bat
cd /d "%~dp0"

echo ==^> Installing Python dependencies...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo ==^> Starting the Kitchen Order Scheduler...
echo    Open http://localhost:5000 in your browser.
python app.py
pause
