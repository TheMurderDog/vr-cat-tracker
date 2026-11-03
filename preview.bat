@echo off
rem Live view of every camera with fps, dropped frames and brightness. --seconds 600 runs a soak test.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.preview %*
pause
