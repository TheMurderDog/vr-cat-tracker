@echo off
rem Check and fix the cat boxes: goes through every session with unchecked images, newest first (or --session NAME).
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.label %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: when you have checked a few hundred images with the cat in them, run 3_train.bat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
