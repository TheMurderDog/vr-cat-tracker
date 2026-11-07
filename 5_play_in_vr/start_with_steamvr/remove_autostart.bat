@echo off
rem Stops the cat tracker starting with SteamVR. SteamVR must be running.
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.install_autostart --remove
if not "%errorlevel%"=="0" goto fail
echo.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
