@echo off
rem Reports any camera that has moved since the room calibration.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.drift_check %*
if not "%errorlevel%"=="0" goto fail
echo.
echo If it says MOVED: run 2_calibrate_cameras\2_room_calibration.bat, then 3_check_calibration.bat.
echo Then back to 5_play_in_vr.
echo.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
