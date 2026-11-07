@echo off
rem Shows where SteamVR puts Board B, the marker card (red) and where each camera sees it (green), FIT GOOD or OFF per camera. Start SteamVR first.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.calib_check %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: when every camera says FIT GOOD, open 3_first_test.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
