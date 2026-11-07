@echo off
rem Places every camera in SteamVR space with Board B, the marker card (wave it to pick its tracker or controller). Start SteamVR first.
rem --resolve solves the last recording again without walking around.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.calib_room %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: run 3_check_calibration.bat with SteamVR up and Board B's tracker or controller on.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
