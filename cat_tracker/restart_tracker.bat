@echo off
rem Restarts the cat tracker in the background (no window), e.g. after changing config.yaml or the code.
rem Stops the running one first (like stop_tracker.bat), waits for it to let go of the cameras, then starts a
rem new one the way SteamVR does: saved anchor, no window, sending to VRChat. SteamVR must be running.
cd /d "%~dp0"
if not exist data mkdir data
echo stop> data\stop
echo Asking the running tracker to stop ...
rem it deletes data\stop when it sees it (within a second); if nothing is running, go on after 10 seconds
for /l %%i in (1,1,10) do (
  if not exist data\stop goto stopped
  timeout /t 1 >nul
)
echo No tracker seemed to be running.
:stopped
rem a moment for it to close the cameras and SteamVR overlays
timeout /t 3 >nul
cd /d "%~dp0.."
start "" ".venv\Scripts\pythonw.exe" "cat_tracker\autostart.py" --reuse-anchor --headless --osc
echo Started a new tracker in the background (stop_tracker.bat closes it).
timeout /t 3 >nul
