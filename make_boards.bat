@echo off
rem Writes the printable lens-calibration board and tracker marker to calibration\data\boards.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.make_boards %*
pause
