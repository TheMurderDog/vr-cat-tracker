@echo off
rem Places every camera in SteamVR space with the marked tracker. Start SteamVR first. --resolve re-solves the last recording.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.calib_room %*
pause
