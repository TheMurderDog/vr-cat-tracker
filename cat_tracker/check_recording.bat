@echo off
rem Runs the cat detector over a photo (--image PHOTO), or a recording made with fbt (--session NAME). No cameras or SteamVR needed.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.check_recording %*
pause
