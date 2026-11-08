@echo off
rem Opens the Cat Tracker app: start and stop the tracker, see the cameras and the room map, change how the cat's
rem marker looks and the alerts. With SteamVR running it's also a tab in the dashboard. If the app is already
rem running (for example started by SteamVR), this shows its window.
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
"%TOP%\.venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1 || (
  echo The app is not installed yet. Run 1_install_app.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_app.main %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: in VR, open the SteamVR dashboard and pick the cat tab.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
