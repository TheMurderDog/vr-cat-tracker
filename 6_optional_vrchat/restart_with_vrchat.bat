@echo off
rem Restarts the cat tracker in the background (no window) with VRChat sending on, e.g. after changing a settings file.
rem Stops the running one first (like 5_play_in_vr\stop_tracker.bat), waits for it to let go of the cameras, then
rem starts a new one the way SteamVR does: saved anchor, no window, sending to VRChat. SteamVR must be running.
set "TOP=%~dp0.."
if not exist "%TOP%\.venv\Scripts\python.exe" (
  echo The tracker is not installed yet. Run 0_start_here\1_install.bat first.
  pause
  exit /b 1
)
if not exist "%TOP%\my_data\tracker" mkdir "%TOP%\my_data\tracker"
echo stop> "%TOP%\my_data\tracker\stop"
echo Asking the running tracker to stop ...
rem it deletes the stop file when it sees it (within a second); if nothing is running, go on after 10 seconds
for /l %%i in (1,1,10) do (
  if not exist "%TOP%\my_data\tracker\stop" goto stopped
  "%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul
)
echo No tracker seemed to be running.
del "%TOP%\my_data\tracker\stop" >nul 2>&1
:stopped
rem a moment for it to close the cameras and SteamVR overlays
"%SystemRoot%\System32\ping.exe" -n 4 127.0.0.1 >nul
cd /d "%TOP%\engine"
start "" "%TOP%\.venv\Scripts\pythonw.exe" "%TOP%\engine\cat_tracker\autostart.py" --reuse-anchor --headless --osc
echo Started a new tracker in the background, sending to VRChat. 5_play_in_vr\stop_tracker.bat closes it.
timeout /t 3 >nul
