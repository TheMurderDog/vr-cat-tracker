@echo off
rem Saves camera frames of the cat for training, no SteamVR needed. Leave it running while it wanders and naps; q stops.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.run --no-vr --capture %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: run 2_label.bat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
