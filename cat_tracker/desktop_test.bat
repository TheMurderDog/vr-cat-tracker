@echo off
rem Cat tracker without SteamVR: detect it and show the cameras on the desktop only.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.run --no-vr %*
pause
