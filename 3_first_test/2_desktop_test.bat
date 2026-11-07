@echo off
rem The cat tracker without SteamVR: finds the cat and shows the cameras on the desktop only. q quits.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.run --no-vr %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: open 4_teach_it_your_cat. The stock model misses a lot until it has learned your cat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
