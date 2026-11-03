@echo off
rem Fills in cat boxes the stock model missed in the newest capture (or --session NAME), from the other cameras
rem and from nearby moments when it stayed in one spot. Run it before label.bat; checked images are never changed.
cd /d "%~dp0.."
.venv\Scripts\python.exe -m cat_tracker.autolabel %*
pause
