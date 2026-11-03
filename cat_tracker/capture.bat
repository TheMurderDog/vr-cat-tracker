@echo off
rem Saves camera frames of the cat for training (no SteamVR needed). Leave it running while she wanders and naps; q stops.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.run --no-vr --capture %*
pause
