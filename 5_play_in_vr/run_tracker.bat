@echo off
rem The cat tracker: finds the cat with the room cameras and shows it in SteamVR. Start SteamVR first.
rem The first time, put the headset on and walk slowly around the room for about 20 seconds (the anchor).
rem After that it uses the saved anchor. Add --new-anchor to walk for a new one anyway.
rem With the app installed (app\1_install_app.bat), the app opens too and is the tracker's window.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
cd /d "%TOP%\engine"
"%TOP%\.venv\Scripts\python.exe" -m cat_app.launch -- %*
if not "%errorlevel%"=="0" goto fail
echo.
echo To make it start by itself with SteamVR, see start_with_steamvr.
echo For VRChat, open 6_optional_vrchat.
timeout /t 4 >nul
exit /b 0

:fail
echo.
echo Something went wrong. The details are above. Press any key to close.
pause >nul
exit /b 1
