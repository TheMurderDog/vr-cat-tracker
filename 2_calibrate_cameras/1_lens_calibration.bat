@echo off
rem Lens calibration: goes through every camera in turn and talks you through each one. Turn your speakers on.
rem Advanced: 1_lens_calibration.bat --cam north (one camera), --cam north --from-dir (redo from saved frames),
rem --quiet (no voice or beeps).
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m tools.calib_intrinsics %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: when every camera says FIT GOOD, start SteamVR and run 2_room_calibration.bat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
