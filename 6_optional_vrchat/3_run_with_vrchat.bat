@echo off
rem The tracker plus VRChat: sends the cat's position to your avatar over OSC, on this PC only.
rem Turn OSC on in VRChat: Action Menu, Options, OSC. Reuses the saved anchor, so no walk-around. Start SteamVR first.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_tracker.run --osc --reuse-anchor %*
if not "%errorlevel%"=="0" goto fail
echo.
echo Next: to have this start by itself with SteamVR, run 4_install_autostart_vrchat.bat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
