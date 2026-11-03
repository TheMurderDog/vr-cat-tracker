@echo off
rem Lists which camera ids open and which give the mode in config.yaml (cameras.width/height/fourcc/fps).
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.probe_cameras %*
pause
