@echo off
rem Runs the cat detector over a photo (--image PHOTO) or a recording made with fbt (--session NAME).
rem No cameras or SteamVR needed. Pictures go to my_data\logs\cat_tracker\snapshots.
set "TOP=%~dp0..\.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.check_recording %*
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
