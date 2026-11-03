@echo off
rem Reports any camera that has moved since the room calibration.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.drift_check %*
pause
