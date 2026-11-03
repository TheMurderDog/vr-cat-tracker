@echo off
rem Check and fix the cat boxes: goes through every session with unchecked images, newest first (or --session NAME).
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.label %*
pause
