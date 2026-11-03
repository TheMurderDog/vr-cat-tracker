@echo off
rem Cat tracker: finds the cat with the room cameras and shows her in SteamVR. Start SteamVR first.
rem Add --reuse-anchor to skip the walk-around and use the last saved anchor.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.run %*
pause
