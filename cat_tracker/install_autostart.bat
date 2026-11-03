@echo off
rem Makes the cat tracker start with SteamVR, with no window (SteamVR must be running).
rem Run run.bat once first so there is a saved anchor. Add --osc to send it to VRChat too.
rem To undo: install_autostart.bat --remove
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.install_autostart %*
pause
