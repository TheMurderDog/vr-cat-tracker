@echo off
rem Test mode for lining up the avatar: a pretend cat held 1 m ahead of you (keys 1 / 2 = 1 m / 2 m, q = quit).
rem Start SteamVR and VRChat with OSC on first, and close the real tracker so they do not both send.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.osc_test %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: when the stand-in cat sits on the ring at 1 m and 2 m, run 3_run_with_vrchat.bat.
echo.
echo This window closes in 30 seconds. Press any key to close it now.
timeout /t 30 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
