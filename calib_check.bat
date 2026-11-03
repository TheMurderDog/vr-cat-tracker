@echo off
rem Shows where SteamVR puts the marked tracker (red) and where each camera sees it (green). Start SteamVR first.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.calib_check %*
pause
