@echo off
rem Makes the cat tracker start with SteamVR, with no window. SteamVR must be running.
rem Run run_tracker.bat once first so there is a saved anchor. To undo: remove_autostart.bat
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.install_autostart %*
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
